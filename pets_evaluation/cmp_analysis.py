"""
Consent Management Platform (CMP) analysis.

Evaluates CMPs (OneTrust, Cookiebot, Quantcast, TrustArc, Didomi,
Usercentrics) as privacy-enhancing technologies by comparing compliance
scores and dark-pattern rates across sites grouped by CMP provider.

This analysis reveals:
- Which CMPs lead to higher GDPR compliance
- Which CMPs are associated with more dark patterns
- Whether CMP adoption correlates with fewer pre-consent trackers
- Market share of each CMP among the crawled sites
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path

import pandas as pd

from config import (
    DEFAULT_SOURCE_MODE,
    PROCESSED_DIR,
    RAW_DIR,
    build_provenance,
    get_dataset_layout,
    infer_common_field,
    infer_common_value,
    unwrap_payload,
)


# ── Group sites by CMP ───────────────────────────────────────────────────────


def group_sites_by_cmp(
    raw_dir: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
) -> dict[str, list[str]]:
    """Group crawled sites by their detected CMP provider.

    Returns:
        ``{"OneTrust": ["site1.com", ...], "No CMP Detected": [...], ...}``
    """
    layout = get_dataset_layout(source_mode)
    r_dir = Path(raw_dir) if raw_dir else layout.raw_dir
    groups: dict[str, list[str]] = {}

    for f in sorted(r_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        domain = data.get("domain", f.stem)
        cmp = data.get("cmp_detected") or "No CMP Detected"
        groups.setdefault(cmp, []).append(domain)

    return groups


# ── Evaluate CMP effectiveness ────────────────────────────────────────────────


def evaluate_cmp_effectiveness(
    cmp_groups: dict[str, list[str]],
    scores_path: str | None = None,
    raw_dir: str | None = None,
    processed_dir: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
) -> dict:
    """Compute per-CMP compliance statistics.

    For each CMP group calculates mean/median compliance scores,
    dark-pattern rates, pre-consent tracker rates, reject effectiveness,
    and other metrics.
    """
    layout = get_dataset_layout(source_mode)
    s_path = Path(scores_path) if scores_path else layout.processed_dir / "compliance_scores.csv"
    r_dir = Path(raw_dir) if raw_dir else layout.raw_dir
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir

    # Load compliance scores
    scores_df = pd.read_csv(s_path) if s_path.exists() else pd.DataFrame()
    scores_by_domain: dict[str, dict] = {}
    if not scores_df.empty:
        for _, row in scores_df.iterrows():
            scores_by_domain[row["domain"]] = row.to_dict()

    # Load raw data per site
    raw_cache: dict[str, dict] = {}
    for f in sorted(r_dir.glob("*.json")):
        try:
            raw_cache[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Load dark-pattern data per site
    dp_cache: dict[str, dict] = {}
    for f in sorted(p_dir.glob("*_dark_patterns.json")):
        try:
            domain_key = f.stem.replace("_dark_patterns", "")
            dp_cache[domain_key] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Load classified cookies per site (for precise tracker count)
    classified_cache: dict[str, list[dict]] = {}
    for f in sorted(p_dir.glob("*_classified.json")):
        try:
            domain_key = f.stem.replace("_classified", "")
            classified_doc = json.loads(f.read_text(encoding="utf-8"))
            classified_cache[domain_key] = unwrap_payload(classified_doc, "cookies")
        except Exception:
            pass

    result: dict = {}

    for cmp_name, domains in sorted(cmp_groups.items()):
        site_count = len(domains)

        # ── Compliance scores ─────────────────────────────────────────
        cmp_scores: list[float] = []
        grade_counter: Counter = Counter()
        for d in domains:
            sd = scores_by_domain.get(d)
            if sd and "overall_score" in sd:
                cmp_scores.append(float(sd["overall_score"]))
                grade_counter[sd.get("grade", "?")] += 1

        compliance_info: dict = {}
        if cmp_scores:
            compliance_info = {
                "avg_score": round(statistics.mean(cmp_scores), 1),
                "median_score": round(statistics.median(cmp_scores), 1),
                "min_score": round(min(cmp_scores), 1),
                "max_score": round(max(cmp_scores), 1),
                "std_dev": round(statistics.stdev(cmp_scores), 1) if len(cmp_scores) > 1 else 0.0,
                "grade_distribution": {g: grade_counter.get(g, 0) for g in ["A", "B", "C", "D", "F"]},
            }
        else:
            compliance_info = {
                "avg_score": 0.0, "median_score": 0.0, "min_score": 0.0,
                "max_score": 0.0, "std_dev": 0.0,
                "grade_distribution": {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0},
            }

        # ── Pre-consent tracking ──────────────────────────────────────
        sites_w_trackers = 0
        pre_tracker_counts: list[int] = []
        pre_tracker_domain_counts: list[int] = []

        for d in domains:
            raw = raw_cache.get(d, {})
            if not raw.get("success"):
                continue
            pre = raw.get("pre_consent", {})
            tp = pre.get("third_party_domains", [])
            n_tp = len(tp)
            pre_tracker_domain_counts.append(n_tp)

            # Tracker cookie count from classified data
            classified = classified_cache.get(d, [])
            pre_names = {(c["name"], c["domain"]) for c in pre.get("cookies", [])}
            tracker_count = sum(
                1 for c in classified
                if c.get("is_tracker") and (c.get("name"), c.get("domain")) in pre_names
            )
            pre_tracker_counts.append(tracker_count)
            if n_tp > 0:
                sites_w_trackers += 1

        pre_consent_info = {
            "sites_with_pre_consent_trackers": sites_w_trackers,
            "percentage": round(sites_w_trackers / site_count * 100, 1) if site_count else 0.0,
            "avg_pre_consent_trackers": round(statistics.mean(pre_tracker_counts), 1) if pre_tracker_counts else 0.0,
            "avg_pre_consent_tracker_domains": round(statistics.mean(pre_tracker_domain_counts), 1) if pre_tracker_domain_counts else 0.0,
        }

        # ── Reject functionality ──────────────────────────────────────
        sites_w_reject = 0
        reject_clicks_list: list[int] = []
        reject_actually_works = 0
        sites_with_reject_data = 0

        for d in domains:
            raw = raw_cache.get(d, {})
            if not raw.get("success"):
                continue
            banner = raw.get("consent_banner") or {}
            if banner.get("has_reject_button"):
                sites_w_reject += 1
                rc = banner.get("reject_clicks_required", 999)
                if rc < 999:
                    reject_clicks_list.append(rc)

            # Check if reject reduces trackers
            post_r = raw.get("post_consent_reject") or {}
            pre = raw.get("pre_consent") or {}
            if post_r:
                pre_tp = len(pre.get("third_party_domains", []))
                post_tp = len(post_r.get("third_party_domains", []))
                sites_with_reject_data += 1
                if post_tp < pre_tp:
                    reject_actually_works += 1

        reject_info = {
            "sites_with_reject_button": sites_w_reject,
            "percentage": round(sites_w_reject / site_count * 100, 1) if site_count else 0.0,
            "avg_reject_clicks": round(statistics.mean(reject_clicks_list), 1) if reject_clicks_list else 0.0,
            "reject_actually_works": reject_actually_works,
            "reject_works_percentage": round(reject_actually_works / sites_with_reject_data * 100, 1) if sites_with_reject_data else 0.0,
            "description": "How often rejecting via this CMP actually reduces trackers",
        }

        # ── Post-reject effectiveness ─────────────────────────────────
        tracker_reductions: list[float] = []
        reject_eliminates = 0
        reject_no_effect = 0
        post_reject_tracker_counts: list[int] = []

        for d in domains:
            raw = raw_cache.get(d, {})
            if not raw.get("success"):
                continue
            pre = raw.get("pre_consent") or {}
            post_r = raw.get("post_consent_reject") or {}
            if not post_r:
                continue

            pre_tp = len(pre.get("third_party_domains", []))
            post_tp = len(post_r.get("third_party_domains", []))
            post_reject_tracker_counts.append(post_tp)

            if pre_tp > 0:
                reduction = (pre_tp - post_tp) / pre_tp
                tracker_reductions.append(reduction)
                if post_tp == 0:
                    reject_eliminates += 1
                if post_tp >= pre_tp:
                    reject_no_effect += 1
            else:
                tracker_reductions.append(0.0)
                if post_tp == 0:
                    reject_eliminates += 1

        post_reject_info = {
            "avg_tracker_reduction_after_reject": round(statistics.mean(tracker_reductions), 2) if tracker_reductions else 0.0,
            "sites_where_reject_eliminates_all_trackers": reject_eliminates,
            "sites_where_reject_has_no_effect": reject_no_effect,
            "avg_trackers_after_reject": round(statistics.mean(post_reject_tracker_counts), 1) if post_reject_tracker_counts else 0.0,
        }

        # ── Dark patterns ─────────────────────────────────────────────
        sites_w_dp = 0
        pattern_counter: Counter = Counter()

        for d in domains:
            dp_data = dp_cache.get(d, {})
            dp_count = dp_data.get("dark_pattern_count", 0)
            if dp_count > 0:
                sites_w_dp += 1
            for p in dp_data.get("dark_patterns_detected", []):
                pattern_counter[p] += 1

        most_common = pattern_counter.most_common(1)
        dark_patterns_info = {
            "sites_with_dark_patterns": sites_w_dp,
            "percentage": round(sites_w_dp / site_count * 100, 1) if site_count else 0.0,
            "most_common_pattern": most_common[0][0] if most_common else None,
            "pattern_breakdown": dict(pattern_counter.most_common()),
        }

        # ── TCF support detection ─────────────────────────────────────
        sites_with_tcf = 0
        tcf_keywords = ["__tcfapi", "__cmp", "__tcfapiLocator", "tcfapi"]

        for d in domains:
            raw = raw_cache.get(d, {})
            banner = raw.get("consent_banner") or {}
            banner_html = banner.get("html", "")
            banner_text = banner.get("text_content", "")
            combined = (banner_html + " " + banner_text).lower()
            if any(kw.lower() in combined for kw in tcf_keywords):
                sites_with_tcf += 1
                continue
            # Check HTTP requests for TCF scripts
            pre = raw.get("pre_consent") or {}
            for req in pre.get("http_requests", []):
                if any(kw.lower() in req.get("url", "").lower() for kw in tcf_keywords):
                    sites_with_tcf += 1
                    break

        tcf_info = {
            "sites_with_tcf": sites_with_tcf,
            "percentage": round(sites_with_tcf / site_count * 100, 1) if site_count else 0.0,
        }

        # ── Assemble CMP result ───────────────────────────────────────
        result[cmp_name] = {
            "site_count": site_count,
            "sites": domains,
            "compliance": compliance_info,
            "pre_consent_tracking": pre_consent_info,
            "reject_functionality": reject_info,
            "post_reject_effectiveness": post_reject_info,
            "dark_patterns": dark_patterns_info,
            "tcf_support": tcf_info,
        }

    return result


# ── Rank CMPs ─────────────────────────────────────────────────────────────────


def rank_cmps(cmp_effectiveness: dict) -> list[dict]:
    """Rank CMPs from best to worst as a privacy tool.

    Weighting:
      30% avg compliance score
      25% reject actually reduces trackers
      20% reject button available
      15% inverse dark-pattern percentage (fewer = better)
      10% avg tracker reduction after reject
    """
    rankings: list[dict] = []

    for cmp_name, data in cmp_effectiveness.items():
        comp = data.get("compliance", {})
        avg_score = comp.get("avg_score", 0.0)

        rej = data.get("reject_functionality", {})
        rej_works_pct = rej.get("reject_works_percentage", 0.0)
        rej_avail_pct = rej.get("percentage", 0.0)

        dp = data.get("dark_patterns", {})
        dp_pct = dp.get("percentage", 0.0)
        inv_dp = max(0.0, 100.0 - dp_pct)

        pr = data.get("post_reject_effectiveness", {})
        avg_reduction = pr.get("avg_tracker_reduction_after_reject", 0.0) * 100  # to percentage

        pet_score = (
            0.30 * avg_score
            + 0.25 * rej_works_pct
            + 0.20 * rej_avail_pct
            + 0.15 * inv_dp
            + 0.10 * avg_reduction
        )

        rankings.append({
            "cmp": cmp_name,
            "pet_score": round(pet_score, 1),
            "breakdown": {
                "avg_compliance_score": avg_score,
                "reject_works_pct": rej_works_pct,
                "reject_available_pct": rej_avail_pct,
                "inverse_dark_pattern_pct": round(inv_dp, 1),
                "avg_tracker_reduction_pct": round(avg_reduction, 1),
            },
        })

    rankings.sort(key=lambda x: x["pet_score"], reverse=True)
    for i, r in enumerate(rankings, 1):
        r["rank"] = i

    return rankings


# ── Run CMP analysis ─────────────────────────────────────────────────────────


def run_cmp_analysis(
    raw_dir: str | None = None,
    processed_dir: str | None = None,
    scores_path: str | None = None,
    output_path: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> None:
    """Run the full CMP analysis pipeline."""
    layout = get_dataset_layout(source_mode)
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir
    r_dir = Path(raw_dir) if raw_dir else layout.raw_dir
    s_path = Path(scores_path) if scores_path else p_dir / "compliance_scores.csv"
    out_csv = Path(output_path) if output_path else p_dir / "cmp_comparison.csv"
    out_json = p_dir / "cmp_comparison_detailed.json"
    p_dir.mkdir(parents=True, exist_ok=True)

    raw_docs: list[dict] = []
    for path in sorted(r_dir.glob("*.json")):
        try:
            raw_docs.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue

    score_run_id = None
    if s_path.exists():
        scores_df = pd.read_csv(s_path)
        if not scores_df.empty and "run_id" in scores_df.columns:
            score_run_id = infer_common_value(scores_df["run_id"].tolist())

    effective_run_id = run_id or score_run_id or infer_common_field(raw_docs, "run_id")
    effective_site_list_source = infer_common_field(raw_docs, "site_list_source")

    print("Grouping sites by CMP …")
    groups = group_sites_by_cmp(str(r_dir), source_mode=source_mode)
    for cmp, sites in sorted(groups.items()):
        print(f"  {cmp}: {len(sites)} sites")

    print("\nEvaluating CMP effectiveness …")
    effectiveness = evaluate_cmp_effectiveness(
        groups,
        scores_path,
        raw_dir,
        processed_dir,
        source_mode=source_mode,
    )

    print("Ranking CMPs …")
    rankings = rank_cmps(effectiveness)

    # ── Save CSV ──────────────────────────────────────────────────────────
    csv_fields = [
        "source_mode", "run_id", "cmp_name", "site_count", "avg_compliance_score", "median_compliance_score",
        "pct_with_reject_button", "pct_reject_works", "avg_tracker_reduction",
        "pct_with_dark_patterns", "pet_score", "rank",
    ]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for r in rankings:
            comp = effectiveness[r["cmp"]]["compliance"]
            rej = effectiveness[r["cmp"]]["reject_functionality"]
            pr = effectiveness[r["cmp"]]["post_reject_effectiveness"]
            dp = effectiveness[r["cmp"]]["dark_patterns"]
            writer.writerow({
                "source_mode": source_mode,
                "run_id": effective_run_id or "",
                "cmp_name": r["cmp"],
                "site_count": effectiveness[r["cmp"]]["site_count"],
                "avg_compliance_score": comp.get("avg_score", 0),
                "median_compliance_score": comp.get("median_score", 0),
                "pct_with_reject_button": rej.get("percentage", 0),
                "pct_reject_works": rej.get("reject_works_percentage", 0),
                "avg_tracker_reduction": pr.get("avg_tracker_reduction_after_reject", 0),
                "pct_with_dark_patterns": dp.get("percentage", 0),
                "pet_score": r["pet_score"],
                "rank": r["rank"],
            })
    print(f"\nCMP comparison saved to {out_csv}")

    # ── Save detailed JSON ────────────────────────────────────────────────
    full_report = {
        "cmp_effectiveness": effectiveness,
        "rankings": rankings,
        **build_provenance(
            source_mode=source_mode,
            run_id=effective_run_id,
            site_list_source=effective_site_list_source,
        ),
    }
    out_json.write_text(json.dumps(full_report, indent=2, default=str), encoding="utf-8")
    print(f"Detailed results saved to {out_json}")

    # ── Print summary ─────────────────────────────────────────────────────
    _print_summary(rankings, effectiveness)


def _print_summary(rankings: list[dict], effectiveness: dict) -> None:
    """Print a formatted CMP ranking table."""
    print(f"\n{'=' * 90}")
    print("CMP EFFECTIVENESS RANKING")
    print(f"{'=' * 90}")

    print(f"\n{'Rank':<5s} {'CMP':<22s} {'Sites':>6s} {'Avg Score':>10s} {'Reject %':>9s} "
          f"{'Works %':>8s} {'DP %':>6s} {'PET Score':>10s}")
    print("-" * 80)

    for r in rankings:
        cmp = r["cmp"]
        data = effectiveness[cmp]
        comp = data["compliance"]
        rej = data["reject_functionality"]
        dp_pct = data["dark_patterns"]["percentage"]

        print(
            f"{r['rank']:<5d} {cmp:<22s} {data['site_count']:>6d} "
            f"{comp.get('avg_score', 0):>10.1f} {rej.get('percentage', 0):>9.1f} "
            f"{rej.get('reject_works_percentage', 0):>8.1f} {dp_pct:>6.1f} "
            f"{r['pet_score']:>10.1f}"
        )

    # Key insights
    if rankings:
        best = rankings[0]
        worst = rankings[-1]
        print(f"\nKey Insights:")
        print(f"  Best CMP as PET:  {best['cmp']} (score: {best['pet_score']})")
        print(f"  Worst CMP as PET: {worst['cmp']} (score: {worst['pet_score']})")

        # Pre-consent tracker issue
        total_sites = sum(d["site_count"] for d in effectiveness.values())
        total_w_trackers = sum(
            d["pre_consent_tracking"]["sites_with_pre_consent_trackers"]
            for d in effectiveness.values()
        )
        if total_sites > 0:
            pct = round(total_w_trackers / total_sites * 100, 1)
            print(f"  {pct}% of all sites (with or without CMP) set pre-consent trackers")

    print(f"{'=' * 90}")


# ── CLI Entry Point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AECCS CMP Analysis")
    parser.add_argument("--raw-dir", type=str, default=None, help="Raw data directory")
    parser.add_argument("--processed-dir", type=str, default=None, help="Processed data directory")
    parser.add_argument("--scores", type=str, default=None, help="Compliance scores CSV path")
    parser.add_argument("--output", type=str, default=None, help="Output CSV path")
    parser.add_argument(
        "--source-mode",
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

    run_cmp_analysis(
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        scores_path=args.scores,
        output_path=args.output,
        source_mode=args.source_mode,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
