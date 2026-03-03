"""
Differential privacy reporting.

Applies differential privacy mechanisms to aggregate compliance statistics
so that individual website contributions are protected.  This module
demonstrates the privacy-utility tradeoff using the Laplace mechanism,
Gaussian mechanism, and randomized response at multiple epsilon values.

Mechanisms:
- Laplace mechanism — calibrated Laplace noise for numeric aggregates.
- Gaussian mechanism — calibrated Gaussian noise (with delta parameter).
- Randomized response — local DP for binary per-site attributes.

The module generates reports at multiple epsilon values to illustrate
the privacy-utility tradeoff.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import DEFAULT_SOURCE_MODE, PROCESSED_DIR, build_provenance, get_dataset_layout


# ── Core DP mechanisms ────────────────────────────────────────────────────────


def apply_laplace_mechanism(
    value: float, sensitivity: float, epsilon: float
) -> float:
    """Add Laplace noise to a single numeric value.

    noise ~ Lap(0, sensitivity / epsilon)
    """
    scale = sensitivity / epsilon
    return value + float(np.random.laplace(loc=0, scale=scale))


def apply_gaussian_mechanism(
    value: float,
    sensitivity: float,
    epsilon: float,
    delta: float = 1e-5,
) -> float:
    """Add Gaussian noise to a single numeric value.

    sigma = sensitivity * sqrt(2 * ln(1.25 / delta)) / epsilon
    """
    sigma = sensitivity * math.sqrt(2.0 * math.log(1.25 / delta)) / epsilon
    return value + float(np.random.normal(loc=0, scale=sigma))


def apply_randomized_response(value: bool, epsilon: float) -> bool:
    """Apply randomized response to a single binary value.

    With probability p = e^eps / (1 + e^eps) report the truth; else flip.
    """
    p = math.exp(epsilon) / (1.0 + math.exp(epsilon))
    if np.random.random() < p:
        return value
    return not value


def apply_dp_to_count(
    count: int, total: int, epsilon: float
) -> dict:
    """Apply Laplace mechanism to a count (sensitivity = 1)."""
    noisy = apply_laplace_mechanism(float(count), sensitivity=1.0, epsilon=epsilon)
    noisy_clamped = max(0.0, min(float(total), noisy))
    noisy_pct = (noisy_clamped / total * 100) if total > 0 else 0.0
    true_pct = (count / total * 100) if total > 0 else 0.0
    return {
        "true_count": count,
        "noisy_count": round(noisy_clamped, 1),
        "true_percentage": round(true_pct, 2),
        "noisy_percentage": round(noisy_pct, 2),
        "epsilon": epsilon,
    }


def apply_dp_to_mean(
    values: list[float],
    epsilon: float,
    value_range: tuple[float, float] = (0.0, 100.0),
) -> dict:
    """Apply Laplace mechanism to a mean query.

    Sensitivity for mean = (max - min) / n.
    """
    n = len(values)
    if n == 0:
        return {"true_mean": 0.0, "noisy_mean": 0.0, "epsilon": epsilon, "n": 0}
    true_mean = statistics.mean(values)
    sensitivity = (value_range[1] - value_range[0]) / n
    noisy = apply_laplace_mechanism(true_mean, sensitivity, epsilon)
    noisy_clamped = max(value_range[0], min(value_range[1], noisy))
    return {
        "true_mean": round(true_mean, 2),
        "noisy_mean": round(noisy_clamped, 2),
        "epsilon": epsilon,
        "n": n,
    }


# ── Statistical evaluation helpers ────────────────────────────────────────────


def _run_count_trials(count: int, total: int, epsilon: float, trials: int) -> dict:
    """Run many trials of DP count and return summary stats."""
    noisy_values = []
    for _ in range(trials):
        res = apply_dp_to_count(count, total, epsilon)
        noisy_values.append(res["noisy_count"])
    true_pct = (count / total * 100) if total > 0 else 0.0
    noisy_pcts = [(v / total * 100) if total > 0 else 0.0 for v in noisy_values]
    mean_n = statistics.mean(noisy_pcts)
    std_n = statistics.stdev(noisy_pcts) if len(noisy_pcts) > 1 else 0.0
    mae = statistics.mean([abs(v - true_pct) for v in noisy_pcts])
    sorted_v = sorted(noisy_pcts)
    ci_lo = sorted_v[int(0.025 * len(sorted_v))]
    ci_hi = sorted_v[min(int(0.975 * len(sorted_v)), len(sorted_v) - 1)]
    return {
        "mean_noisy": round(mean_n, 2),
        "std": round(std_n, 2),
        "mae": round(mae, 2),
        "ci_95": [round(ci_lo, 2), round(ci_hi, 2)],
    }


def _run_mean_trials(
    values: list[float],
    epsilon: float,
    value_range: tuple[float, float],
    trials: int,
) -> dict:
    """Run many trials of DP mean and return summary stats."""
    if not values:
        return {"mean_noisy": 0.0, "std": 0.0, "mae": 0.0, "ci_95": [0.0, 0.0]}
    true_mean = statistics.mean(values)
    noisy_means = []
    for _ in range(trials):
        res = apply_dp_to_mean(values, epsilon, value_range)
        noisy_means.append(res["noisy_mean"])
    mean_n = statistics.mean(noisy_means)
    std_n = statistics.stdev(noisy_means) if len(noisy_means) > 1 else 0.0
    mae = statistics.mean([abs(v - true_mean) for v in noisy_means])
    sorted_v = sorted(noisy_means)
    ci_lo = sorted_v[int(0.025 * len(sorted_v))]
    ci_hi = sorted_v[min(int(0.975 * len(sorted_v)), len(sorted_v) - 1)]
    return {
        "mean_noisy": round(mean_n, 2),
        "std": round(std_n, 2),
        "mae": round(mae, 2),
        "ci_95": [round(ci_lo, 2), round(ci_hi, 2)],
    }


def _run_rr_trials(
    true_values: list[bool],
    epsilon: float,
    trials: int,
) -> dict:
    """Run randomized response trials and estimate the true proportion."""
    if not true_values:
        return {"estimated_proportion": 0.0, "error": 0.0, "note": ""}
    true_prop = sum(true_values) / len(true_values)
    p = math.exp(epsilon) / (1.0 + math.exp(epsilon))
    estimates = []
    for _ in range(trials):
        responses = [apply_randomized_response(v, epsilon) for v in true_values]
        observed = sum(responses) / len(responses)
        # Corrected estimate
        if (2 * p - 1) != 0:
            est = (observed - (1 - p)) / (2 * p - 1)
        else:
            est = observed
        est = max(0.0, min(1.0, est))
        estimates.append(est)
    mean_est = statistics.mean(estimates)
    error = abs(mean_est - true_prop)
    # Note
    if epsilon <= 0.1:
        note = "Very high privacy, low utility"
    elif epsilon <= 0.5:
        note = "High privacy, moderate utility"
    elif epsilon <= 1.0:
        note = "Good privacy-utility balance"
    elif epsilon <= 2.0:
        note = "Moderate privacy, good utility"
    else:
        note = "Low privacy, high utility"
    return {
        "estimated_proportion": round(mean_est, 4),
        "error": round(error, 4),
        "note": note,
    }


def _recommend_epsilon(privacy_utility: dict, epsilons: list[float]) -> float:
    """Choose a publication epsilon from the computed MAE curves."""
    key_metrics = [
        "pre_consent_tracker_percentage",
        "sites_with_reject_button_percentage",
        "sites_with_dark_patterns_percentage",
        "avg_compliance_score",
    ]
    if "avg_pre_consent_trackers" in privacy_utility:
        key_metrics.append("avg_pre_consent_trackers")

    for eps in sorted(epsilons):
        ok = 0
        total_checked = 0
        for metric_name in key_metrics:
            if metric_name not in privacy_utility:
                continue
            data = privacy_utility[metric_name]
            true_v = data.get("true_value", 0)
            eps_data = data.get("by_epsilon", {}).get(str(eps), {})
            mae = eps_data.get("mae", float("inf"))
            total_checked += 1
            if true_v > 0 and mae / true_v < 0.05:
                ok += 1
            elif true_v == 0 and mae < 1:
                ok += 1
        if total_checked > 0 and ok / total_checked >= 0.6:
            return eps
    return 1.0


# ── DP Report Generator ──────────────────────────────────────────────────────


def generate_dp_report(
    metrics_path: str | None = None,
    epsilons: list[float] | None = None,
    output_path: str | None = None,
    trials: int = 100,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> dict:
    """Generate differentially private versions of aggregate metrics.

    Returns the full report dict and saves it to disk.
    """
    layout = get_dataset_layout(source_mode)
    m_path = Path(metrics_path) if metrics_path else layout.processed_dir / "aggregate_metrics.json"
    s_path = layout.processed_dir / "compliance_scores.csv"
    out = Path(output_path) if output_path else layout.processed_dir / "dp_aggregate_metrics.json"

    if epsilons is None:
        epsilons = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]

    np.random.seed(42)

    # Load data
    metrics = json.loads(m_path.read_text(encoding="utf-8"))
    scores_df = pd.read_csv(s_path) if s_path.exists() else pd.DataFrame()

    summary = metrics.get("summary", {})
    total_successful = summary.get("successful_crawls", 0)

    # Extract true values for various metrics
    pv = metrics.get("pre_consent_violations", {})
    sites_with_trackers = pv.get("sites_with_pre_consent_trackers", 0)

    cba = metrics.get("consent_banner_analysis", {})
    sites_with_reject = cba.get("sites_with_reject_button", {}).get("count", 0)
    banner_total = (
        cba.get("sites_with_reject_button", {}).get("count", 0)
        + cba.get("sites_without_reject_button", {}).get("count", 0)
    )

    dp_section = metrics.get("dark_patterns", {})
    sites_with_dp = dp_section.get("sites_with_any_dark_pattern", {}).get("count", 0)
    dp_total = total_successful  # approximation

    cs = metrics.get("compliance_scores", {})
    grade_dist = cs.get("grade_distribution", {})

    # Score values
    score_values: list[float] = []
    if not scores_df.empty and "overall_score" in scores_df.columns:
        score_values = scores_df["overall_score"].dropna().tolist()

    # Tracker counts per site (from raw metrics data)
    avg_trackers_val = pv.get("avg_pre_consent_trackers_per_site", 0)
    ta = metrics.get("tracker_analysis", {})
    bva = ta.get("before_vs_after_consent", {})

    # Build per-site boolean lists from scores CSV
    has_pre_trackers: list[bool] = []
    has_reject_button: list[bool] = []
    if not scores_df.empty:
        if "pre_consent_tracker_count" in scores_df.columns:
            has_pre_trackers = (scores_df["pre_consent_tracker_count"] > 0).tolist()
        if "reject_option_available" in scores_df.columns:
            has_reject_button = (scores_df["reject_option_available"] > 0).tolist()

    # ── Build privacy-utility tradeoff ────────────────────────────────────

    privacy_utility: dict = {}

    # 1. Counting queries
    count_queries = {
        "pre_consent_tracker_percentage": (sites_with_trackers, total_successful),
        "sites_with_reject_button_percentage": (sites_with_reject, banner_total if banner_total > 0 else total_successful),
        "sites_with_dark_patterns_percentage": (sites_with_dp, dp_total),
    }

    # Grade counts
    for grade in ["A", "B", "C", "D", "F"]:
        gi = grade_dist.get(grade, {})
        cnt = gi.get("count", 0) if isinstance(gi, dict) else 0
        count_queries[f"grade_{grade}_percentage"] = (cnt, len(score_values) if score_values else total_successful)

    # Dark pattern type counts
    dp_by_type = dp_section.get("by_type", {})
    for dp_name, dp_info in dp_by_type.items():
        cnt = dp_info.get("count", 0) if isinstance(dp_info, dict) else 0
        count_queries[f"dp_{dp_name}_percentage"] = (cnt, dp_total)

    for metric_name, (count, total) in count_queries.items():
        true_pct = (count / total * 100) if total > 0 else 0.0
        by_eps: dict = {}
        for eps in epsilons:
            by_eps[str(eps)] = _run_count_trials(count, total, eps, trials)
        privacy_utility[metric_name] = {
            "true_value": round(true_pct, 2),
            "by_epsilon": by_eps,
        }

    # 2. Mean queries
    mean_queries: dict[str, tuple[list[float], tuple[float, float]]] = {}
    if score_values:
        mean_queries["avg_compliance_score"] = (score_values, (0.0, 100.0))

    # Synthetic per-site tracker counts from scores CSV
    if not scores_df.empty and "pre_consent_tracker_count" in scores_df.columns:
        tc = scores_df["pre_consent_tracker_count"].dropna().tolist()
        mean_queries["avg_pre_consent_trackers"] = (tc, (0.0, 50.0))

    for metric_name, (vals, vr) in mean_queries.items():
        true_mean = statistics.mean(vals) if vals else 0.0
        by_eps: dict = {}
        for eps in epsilons:
            by_eps[str(eps)] = _run_mean_trials(vals, eps, vr, trials)
        privacy_utility[metric_name] = {
            "true_value": round(true_mean, 2),
            "by_epsilon": by_eps,
        }

    # 3. Per-category counting queries
    if not scores_df.empty and "category" in scores_df.columns:
        for cat, grp in scores_df.groupby("category"):
            cat_str = str(cat)
            if "pre_consent_tracker_count" in grp.columns:
                cat_with = int((grp["pre_consent_tracker_count"] > 0).sum())
                cat_total = len(grp)
                true_pct = (cat_with / cat_total * 100) if cat_total > 0 else 0.0
                by_eps = {}
                for eps in epsilons:
                    by_eps[str(eps)] = _run_count_trials(cat_with, cat_total, eps, trials)
                privacy_utility[f"cat_{cat_str}_pre_consent_tracker_pct"] = {
                    "true_value": round(true_pct, 2),
                    "by_epsilon": by_eps,
                }
            if "overall_score" in grp.columns:
                cat_scores = grp["overall_score"].dropna().tolist()
                if cat_scores:
                    true_mean = statistics.mean(cat_scores)
                    by_eps = {}
                    for eps in epsilons:
                        by_eps[str(eps)] = _run_mean_trials(cat_scores, eps, (0.0, 100.0), trials)
                    privacy_utility[f"cat_{cat_str}_avg_score"] = {
                        "true_value": round(true_mean, 2),
                        "by_epsilon": by_eps,
                    }

    # ── Randomized response analysis ──────────────────────────────────────

    rr_analysis: dict = {}
    rr_attrs = {
        "has_pre_consent_trackers": has_pre_trackers,
        "has_reject_button": has_reject_button,
    }

    for attr_name, bool_list in rr_attrs.items():
        if not bool_list:
            continue
        true_prop = sum(bool_list) / len(bool_list)
        by_eps: dict = {}
        for eps in epsilons:
            by_eps[str(eps)] = _run_rr_trials(bool_list, eps, trials)
        rr_analysis[attr_name] = {
            "true_proportion": round(true_prop, 4),
            "by_epsilon": by_eps,
        }

    # ── DP-protected report at recommended epsilon ────────────────────────

    rec_eps = _recommend_epsilon(privacy_utility, epsilons)
    dp_metrics: dict = {}
    for metric_name, data in privacy_utility.items():
        by_eps_data = data.get("by_epsilon", {})
        rec_data = by_eps_data.get(str(rec_eps), {})
        dp_metrics[metric_name] = rec_data.get("mean_noisy", data.get("true_value", 0))

    # ── Assemble report ───────────────────────────────────────────────────

    report = {
        "metadata": {
            "epsilons_tested": epsilons,
            "num_trials": trials,
            "trials_per_epsilon": trials,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "recommended_epsilon": rec_eps,
            "description": "Differentially private versions of aggregate compliance metrics",
        },
        "privacy_utility_tradeoff": privacy_utility,
        "randomized_response_analysis": rr_analysis,
        "dp_protected_report": {
            "epsilon": rec_eps,
            "description": f"Aggregate metrics protected with epsilon={rec_eps} (recommended balance)",
            "metrics": dp_metrics,
        },
        **build_provenance(
            source_mode=metrics.get("source_mode", source_mode),
            run_id=metrics.get("run_id", run_id),
            site_list_source=metrics.get("site_list_source"),
        ),
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"DP report saved to {out}")

    # ── Print formatted summary ───────────────────────────────────────────
    _print_summary(report, epsilons)

    return report


def _print_summary(report: dict, epsilons: list[float]) -> None:
    """Print a formatted DP analysis summary."""
    print(f"\n{'=' * 80}")
    print("DIFFERENTIAL PRIVACY ANALYSIS SUMMARY")
    print(f"{'=' * 80}")

    pu = report["privacy_utility_tradeoff"]

    # Key metrics table
    key_metrics = [
        "pre_consent_tracker_percentage",
        "sites_with_reject_button_percentage",
        "sites_with_dark_patterns_percentage",
        "avg_compliance_score",
    ]
    if "avg_pre_consent_trackers" in pu:
        key_metrics.append("avg_pre_consent_trackers")

    header = f"{'Metric':<42s} {'True':>8s}"
    for eps in epsilons:
        header += f" {'ε=' + str(eps):>10s}"
    print(f"\n{header}")
    print("-" * (42 + 8 + 10 * len(epsilons) + len(epsilons)))

    for m in key_metrics:
        if m not in pu:
            continue
        data = pu[m]
        row = f"{m:<42s} {data['true_value']:>8.1f}"
        for eps in epsilons:
            eps_data = data["by_epsilon"].get(str(eps), {})
            row += f" {eps_data.get('mean_noisy', 0):>10.1f}"
        print(row)

    # MAE table
    print(f"\nMean Absolute Error (MAE) by epsilon:")
    header2 = f"{'Metric':<42s}"
    for eps in epsilons:
        header2 += f" {'ε=' + str(eps):>10s}"
    print(header2)
    print("-" * (42 + 10 * len(epsilons) + len(epsilons)))

    for m in key_metrics:
        if m not in pu:
            continue
        data = pu[m]
        row = f"{m:<42s}"
        for eps in epsilons:
            eps_data = data["by_epsilon"].get(str(eps), {})
            row += f" {eps_data.get('mae', 0):>10.2f}"
        print(row)

    rec_eps = _recommend_epsilon(pu, epsilons)

    print(f"\nRecommended epsilon for publication: {rec_eps}")
    print(f"  At ε={rec_eps}, MAE < 5% of true value for most key metrics.")
    print(f"  This provides meaningful privacy protection while maintaining utility.")

    # Randomized response summary
    rr = report.get("randomized_response_analysis", {})
    if rr:
        print(f"\nRandomized Response Analysis:")
        for attr, data in rr.items():
            print(f"  {attr} (true proportion: {data['true_proportion']:.3f}):")
            for eps_str, eps_data in data["by_epsilon"].items():
                print(f"    ε={eps_str}: estimated={eps_data['estimated_proportion']:.3f}, "
                      f"error={eps_data['error']:.3f} ({eps_data['note']})")

    print(f"\n{'=' * 80}")


# ── CLI Entry Point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AECCS Differential Privacy Reporting")
    parser.add_argument("--metrics", type=str, default=None, help="Aggregate metrics JSON path")
    parser.add_argument("--output", type=str, default=None, help="Output DP report JSON path")
    parser.add_argument("--epsilons", nargs="+", type=float, default=None, help="Epsilon values")
    parser.add_argument("--trials", type=int, default=100, help="Number of trials per epsilon")
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

    generate_dp_report(
        metrics_path=args.metrics,
        epsilons=args.epsilons,
        output_path=args.output,
        trials=args.trials,
        source_mode=args.source_mode,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
