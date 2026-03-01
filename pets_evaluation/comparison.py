"""
PETs comparison and synthesis.

Produces a unified comparison of every privacy-enhancing mechanism studied:
- Browser-level PETs (uBlock Origin, Privacy Badger, Firefox ETP, Brave Shields)
- Consent Management Platforms (OneTrust, Cookiebot, Quantcast, …)
- Differential privacy reporting as a transparency tool

Outputs a single ``pets_summary.json`` containing rankings, combination
estimates, and actionable user recommendations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from config import (
    DEFAULT_SOURCE_MODE,
    PROCESSED_DIR,
    build_provenance,
    get_dataset_layout,
    infer_common_field,
)


# ── Load all PET results ──────────────────────────────────────────────────────


def load_all_pet_results(
    processed_dir: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
) -> dict:
    """Load results from all three Phase 3 modules.

    Returns a dict with keys:
      ``browser_pets``  – DataFrame rows from pets_effectiveness.csv
      ``dp_report``     – Full JSON from dp_aggregate_metrics.json
      ``cmp_detailed``  – Full JSON from cmp_comparison_detailed.json
      ``cmp_csv``       – DataFrame rows from cmp_comparison.csv
    Any file that does not exist is returned as ``None``.
    """
    layout = get_dataset_layout(source_mode)
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir

    results: dict = {}

    # Browser PETs
    bp_csv = p_dir / "pets_effectiveness.csv"
    if bp_csv.exists():
        df = pd.read_csv(bp_csv)
        results["browser_pets"] = df.to_dict(orient="records")
    else:
        results["browser_pets"] = None

    # DP report
    dp_json = p_dir / "dp_aggregate_metrics.json"
    if dp_json.exists():
        results["dp_report"] = json.loads(dp_json.read_text(encoding="utf-8"))
    else:
        results["dp_report"] = None

    # CMP detailed
    cmp_json = p_dir / "cmp_comparison_detailed.json"
    if cmp_json.exists():
        results["cmp_detailed"] = json.loads(cmp_json.read_text(encoding="utf-8"))
    else:
        results["cmp_detailed"] = None

    # CMP CSV
    cmp_csv = p_dir / "cmp_comparison.csv"
    if cmp_csv.exists():
        df = pd.read_csv(cmp_csv)
        results["cmp_csv"] = df.to_dict(orient="records")
    else:
        results["cmp_csv"] = None

    return results


# ── Build browser PETs ranking ────────────────────────────────────────────────


def _build_browser_pets_ranking(browser_pets: list[dict] | None) -> list[dict]:
    """Rank browser PETs by average tracker-blocking effectiveness.

    For each PET we compute the mean percentage of trackers blocked
    compared to the baseline (no PET) across all tested sites.
    """
    if not browser_pets:
        return []

    df = pd.DataFrame(browser_pets)

    # We need a baseline tracker count per site to compute reduction %
    baselines: dict[str, float] = {}
    for _, row in df[df["pet_name"] == "baseline"].iterrows():
        baselines[row["domain"]] = float(row.get("tracker_domains", 0) or 0)

    pet_stats: dict[str, dict] = {}

    for pet_name in df["pet_name"].unique():
        if pet_name == "baseline":
            continue
        sub = df[df["pet_name"] == pet_name]

        tracker_counts: list[float] = []
        cookie_counts: list[float] = []
        reduction_pcts: list[float] = []

        for _, row in sub.iterrows():
            td = float(row.get("tracker_domains", 0) or 0)
            tc = float(row.get("tracker_cookies", 0) or 0)
            tracker_counts.append(td)
            cookie_counts.append(tc)

            base = baselines.get(row["domain"])
            if base and base > 0:
                reduction_pcts.append((base - td) / base * 100)

        avg_trackers = round(sum(tracker_counts) / len(tracker_counts), 1) if tracker_counts else 0
        avg_cookies = round(sum(cookie_counts) / len(cookie_counts), 1) if cookie_counts else 0
        avg_reduction = round(sum(reduction_pcts) / len(reduction_pcts), 1) if reduction_pcts else 0

        pet_stats[pet_name] = {
            "pet_name": pet_name,
            "sites_tested": len(sub),
            "avg_tracker_domains": avg_trackers,
            "avg_tracker_cookies": avg_cookies,
            "avg_tracker_reduction_pct": avg_reduction,
        }

    # Sort by reduction percentage (higher is better)
    ranking = sorted(pet_stats.values(), key=lambda x: x["avg_tracker_reduction_pct"], reverse=True)
    for i, r in enumerate(ranking, 1):
        r["rank"] = i
    return ranking


# ── Build CMP-as-PET ranking ─────────────────────────────────────────────────


def _build_cmp_as_pets_ranking(cmp_detailed: dict | None) -> list[dict]:
    """Extract CMP rankings from CMP analysis output."""
    if not cmp_detailed:
        return []
    return cmp_detailed.get("rankings", [])


# ── Combination analysis ─────────────────────────────────────────────────────


def _build_combination_analysis(
    browser_ranking: list[dict],
    cmp_ranking: list[dict],
) -> list[dict]:
    """Estimate combined effectiveness of a browser PET + CMP combination.

    Uses the formula:
        combined = 1 - (1 - pet/100) * (1 - cmp_compliance/100)

    This models the two defences as independent layers.
    """
    combos: list[dict] = []

    for pet in browser_ranking:
        pet_reduction = pet.get("avg_tracker_reduction_pct", 0)
        for cmp in cmp_ranking:
            cmp_score = cmp.get("pet_score", 0)  # 0-100 CMP score
            # Normalise CMP score to fraction
            cmp_frac = cmp_score / 100 if cmp_score else 0
            pet_frac = pet_reduction / 100 if pet_reduction else 0

            combined = round((1 - (1 - pet_frac) * (1 - cmp_frac)) * 100, 1)

            combos.append({
                "browser_pet": pet["pet_name"],
                "cmp": cmp["cmp"],
                "browser_reduction_pct": pet_reduction,
                "cmp_pet_score": cmp_score,
                "estimated_combined_effectiveness_pct": combined,
            })

    combos.sort(key=lambda x: x["estimated_combined_effectiveness_pct"], reverse=True)
    return combos


# ── DP privacy-cost summary ──────────────────────────────────────────────────


def _build_dp_privacy_cost(dp_report: dict | None) -> dict:
    """Summarise the differential-privacy privacy/utility trade-off."""
    if not dp_report:
        return {}

    tradeoff = dp_report.get("privacy_utility_tradeoff", {})
    metadata = dp_report.get("metadata", {})

    summary: dict = {
        "mechanism": "Laplace + Gaussian + Randomized Response",
        "epsilons_tested": metadata.get("epsilons_tested", []),
        "trials_per_epsilon": metadata.get("trials_per_epsilon", 0),
        "recommended_epsilon": metadata.get("recommended_epsilon", None),
    }

    # tradeoff format: metric_name -> {"true_value": ..., "by_epsilon": {...}}
    per_epsilon_maes: dict[str, list[float]] = {}
    for metric_data in tradeoff.values():
        if not isinstance(metric_data, dict):
            continue
        by_epsilon = metric_data.get("by_epsilon", {})
        if not isinstance(by_epsilon, dict):
            continue
        for eps_key, eps_stats in by_epsilon.items():
            if not isinstance(eps_stats, dict):
                continue
            per_epsilon_maes.setdefault(str(eps_key), []).append(float(eps_stats.get("mae", 0)))

    for eps_key, maes in per_epsilon_maes.items():
        avg_mae = round(sum(maes) / len(maes), 3) if maes else 0
        summary[f"epsilon_{eps_key}"] = {
            "avg_mae": avg_mae,
            "num_queries": len(maes),
        }

    return summary


# ── Overall findings & recommendations ────────────────────────────────────────


def _build_overall_findings(
    browser_ranking: list[dict],
    cmp_ranking: list[dict],
    combos: list[dict],
    dp_summary: dict,
) -> dict:
    """Synthesise high-level findings from all analyses."""
    findings: dict = {}

    # Best browser PET
    if browser_ranking:
        best_bp = browser_ranking[0]
        findings["best_browser_pet"] = {
            "name": best_bp["pet_name"],
            "avg_tracker_reduction_pct": best_bp["avg_tracker_reduction_pct"],
        }

    # Best CMP
    if cmp_ranking:
        best_cmp = cmp_ranking[0]
        findings["best_cmp"] = {
            "name": best_cmp["cmp"],
            "pet_score": best_cmp["pet_score"],
        }

    # Best combination
    if combos:
        best_combo = combos[0]
        findings["best_combination"] = {
            "browser_pet": best_combo["browser_pet"],
            "cmp": best_combo["cmp"],
            "estimated_effectiveness_pct": best_combo["estimated_combined_effectiveness_pct"],
        }

    # DP recommendation
    rec_eps = dp_summary.get("recommended_epsilon")
    if rec_eps is not None:
        findings["dp_recommendation"] = {
            "recommended_epsilon": rec_eps,
            "interpretation": (
                f"Use epsilon={rec_eps} for a balanced privacy/utility trade-off "
                "when publishing aggregate cookie-consent statistics."
            ),
        }

    return findings


def _build_user_recommendations(
    browser_ranking: list[dict],
    cmp_ranking: list[dict],
    combos: list[dict],
) -> list[str]:
    """Generate plain-English recommendations for end users."""
    recs: list[str] = []

    if browser_ranking:
        best = browser_ranking[0]
        recs.append(
            f"Install {best['pet_name']} for the strongest browser-level tracker blocking "
            f"(avg. {best['avg_tracker_reduction_pct']}% reduction)."
        )
        if len(browser_ranking) > 1:
            second = browser_ranking[1]
            recs.append(
                f"{second['pet_name']} is a good alternative with "
                f"{second['avg_tracker_reduction_pct']}% avg reduction."
            )

    if cmp_ranking:
        best_cmp = cmp_ranking[0]
        recs.append(
            f"When a site uses {best_cmp['cmp']}, the reject/decline mechanism "
            f"is most effective (PET score: {best_cmp['pet_score']})."
        )
        worst_cmp = cmp_ranking[-1]
        if worst_cmp["cmp"] != best_cmp["cmp"]:
            recs.append(
                f"Be cautious with {worst_cmp['cmp']}-powered banners — "
                f"they scored lowest as a privacy tool (PET score: {worst_cmp['pet_score']})."
            )

    if combos:
        best_combo = combos[0]
        recs.append(
            f"For maximum protection, combine {best_combo['browser_pet']} with a "
            f"site using {best_combo['cmp']} (est. {best_combo['estimated_combined_effectiveness_pct']}% effective)."
        )

    recs.append(
        "Always click 'Reject All' when possible — some CMPs actually honour it."
    )
    recs.append(
        "Differential privacy with a moderate epsilon can protect individual "
        "browsing data when publishing aggregate compliance statistics."
    )

    return recs


# ── Main comparison entry-point ───────────────────────────────────────────────


def compare_all_pets(
    processed_dir: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
) -> dict:
    """Run the full comparison and return structured results."""
    all_results = load_all_pet_results(processed_dir, source_mode=source_mode)

    browser_ranking = _build_browser_pets_ranking(all_results["browser_pets"])
    cmp_ranking = _build_cmp_as_pets_ranking(all_results["cmp_detailed"])
    combos = _build_combination_analysis(browser_ranking, cmp_ranking)
    dp_summary = _build_dp_privacy_cost(all_results["dp_report"])
    findings = _build_overall_findings(browser_ranking, cmp_ranking, combos, dp_summary)
    recs = _build_user_recommendations(browser_ranking, cmp_ranking, combos)

    return {
        "browser_pets_ranking": browser_ranking,
        "cmp_as_pets_ranking": cmp_ranking,
        "combination_analysis": combos[:20],  # top 20 combos
        "dp_privacy_cost": dp_summary,
        "overall_findings": findings,
        "user_recommendations": recs,
    }


def _infer_upstream_provenance(all_results: dict) -> dict[str, str | None]:
    """Infer shared provenance from upstream PET artifacts."""
    primary_sources: list[dict | None] = []
    if all_results.get("dp_report"):
        primary_sources.append(all_results["dp_report"])
    if all_results.get("cmp_detailed"):
        primary_sources.append(all_results["cmp_detailed"])

    secondary_sources: list[dict | None] = []
    secondary_sources.extend(all_results.get("browser_pets") or [])
    secondary_sources.extend(all_results.get("cmp_csv") or [])
    return {
        "run_id": infer_common_field(primary_sources, "run_id")
        or infer_common_field(secondary_sources, "run_id"),
        "site_list_source": infer_common_field(primary_sources, "site_list_source")
        or infer_common_field(secondary_sources, "site_list_source"),
    }


def run_comparison(
    processed_dir: str | None = None,
    output_path: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> None:
    """Run the comparison and save results."""
    layout = get_dataset_layout(source_mode)
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir
    out = Path(output_path) if output_path else p_dir / "pets_summary.json"
    p_dir.mkdir(parents=True, exist_ok=True)

    print("Loading all PET evaluation results …")
    all_results = load_all_pet_results(processed_dir, source_mode=source_mode)
    summary = compare_all_pets(processed_dir, source_mode=source_mode)
    upstream = _infer_upstream_provenance(all_results)
    summary.update(
        build_provenance(
            source_mode=source_mode,
            run_id=run_id or upstream.get("run_id"),
            site_list_source=upstream.get("site_list_source"),
        )
    )

    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"PETs summary saved to {out}")

    _print_summary(summary)


def _print_summary(summary: dict) -> None:
    """Print a formatted PETs comparison summary."""
    print(f"\n{'=' * 80}")
    print("PETS COMPARISON SUMMARY")
    print(f"{'=' * 80}")

    # Browser PETs
    br = summary.get("browser_pets_ranking", [])
    if br:
        print(f"\nBrowser PETs Ranking:")
        print(f"  {'Rank':<5s} {'PET':<25s} {'Reduction %':>12s} {'Avg Trackers':>13s}")
        print(f"  {'-' * 58}")
        for r in br:
            print(
                f"  {r['rank']:<5d} {r['pet_name']:<25s} "
                f"{r['avg_tracker_reduction_pct']:>12.1f} "
                f"{r['avg_tracker_domains']:>13.1f}"
            )
    else:
        print("\nBrowser PETs: No data available (run browser_pets.py first)")

    # CMP-as-PET
    cmp = summary.get("cmp_as_pets_ranking", [])
    if cmp:
        print(f"\nCMP-as-PET Ranking:")
        print(f"  {'Rank':<5s} {'CMP':<22s} {'PET Score':>10s}")
        print(f"  {'-' * 40}")
        for r in cmp:
            print(f"  {r.get('rank', '?'):<5} {r['cmp']:<22s} {r['pet_score']:>10.1f}")
    else:
        print("\nCMP-as-PET: No data available (run cmp_analysis.py first)")

    # Top combinations
    combos = summary.get("combination_analysis", [])
    if combos:
        print(f"\nTop 5 PET Combinations:")
        print(f"  {'Browser PET':<22s} {'CMP':<22s} {'Est. Effectiveness':>19s}")
        print(f"  {'-' * 65}")
        for c in combos[:5]:
            print(
                f"  {c['browser_pet']:<22s} {c['cmp']:<22s} "
                f"{c['estimated_combined_effectiveness_pct']:>18.1f}%"
            )

    # DP
    dp = summary.get("dp_privacy_cost", {})
    if dp:
        rec_eps = dp.get("recommended_epsilon")
        if rec_eps is not None:
            print(f"\nDP Recommended Epsilon: {rec_eps}")

    # Recommendations
    recs = summary.get("user_recommendations", [])
    if recs:
        print(f"\nUser Recommendations:")
        for i, r in enumerate(recs, 1):
            print(f"  {i}. {r}")

    # Overall findings
    findings = summary.get("overall_findings", {})
    if findings:
        best_bp = findings.get("best_browser_pet")
        best_cmp = findings.get("best_cmp")
        best_combo = findings.get("best_combination")
        if best_bp:
            print(f"\nBest Browser PET: {best_bp['name']} ({best_bp['avg_tracker_reduction_pct']}% reduction)")
        if best_cmp:
            print(f"Best CMP-as-PET: {best_cmp['name']} (score: {best_cmp['pet_score']})")
        if best_combo:
            print(
                f"Best Combination: {best_combo['browser_pet']} + {best_combo['cmp']} "
                f"({best_combo['estimated_effectiveness_pct']}% est.)"
            )

    print(f"\n{'=' * 80}")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AECCS PETs Comparison")
    parser.add_argument("--processed-dir", type=str, default=None, help="Processed data directory")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    parser.add_argument(
        "--source-mode",
        choices=["real", "mock"],
        default=DEFAULT_SOURCE_MODE,
        help="Dataset/output mode to use (default: real)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional run identifier to stamp onto generated artifacts",
    )
    args = parser.parse_args()

    run_comparison(
        processed_dir=args.processed_dir,
        output_path=args.output,
        source_mode=args.source_mode,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
