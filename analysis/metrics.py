"""
Aggregate metrics computation.

Computes summary statistics across all crawled websites, including:
- Mean/median/std compliance scores by category and region
- Tracker prevalence rates
- Most common tracker vendors and their market share
- CMP adoption rates
- Dark pattern prevalence by type
- Cookie counts (first-party vs. third-party, by purpose)
- Violation rates per compliance criterion
"""

from __future__ import annotations

import argparse
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
    unwrap_payload,
)


def _safe_pct(num: int, denom: int) -> float:
    return round(num / denom * 100, 1) if denom > 0 else 0.0


def _safe_stats(values: list[float]) -> dict:
    if not values:
        return {"avg": 0.0, "median": 0.0, "std_dev": 0.0, "min": 0.0, "max": 0.0}
    return {
        "avg": round(statistics.mean(values), 1),
        "median": round(statistics.median(values), 1),
        "std_dev": round(statistics.stdev(values), 1) if len(values) > 1 else 0.0,
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def compute_aggregate_metrics(
    processed_dir: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> dict:
    """Compute aggregate statistics across all processed sites.

    Loads compliance_scores.csv and per-site processed data to compute
    comprehensive metrics.
    """
    layout = get_dataset_layout(source_mode)
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir
    raw_dir = layout.raw_dir

    # ── Load compliance scores CSV ────────────────────────────────────────
    scores_csv = p_dir / "compliance_scores.csv"
    if scores_csv.exists():
        scores_df = pd.read_csv(scores_csv)
    else:
        scores_df = pd.DataFrame()

    # ── Load raw site data for detailed analysis ──────────────────────────
    raw_files = sorted(raw_dir.glob("*.json"))
    sites: list[dict] = []
    for rf in raw_files:
        try:
            sites.append(json.loads(rf.read_text(encoding="utf-8")))
        except Exception:
            pass

    total_sites = len(sites)
    successful = [s for s in sites if s.get("success")]
    failed = [s for s in sites if not s.get("success")]
    with_banners = [s for s in successful if (s.get("consent_banner") or {}).get("found")]
    without_banners = [s for s in successful if not (s.get("consent_banner") or {}).get("found")]

    # ── Summary ───────────────────────────────────────────────────────────
    summary = {
        "total_sites_crawled": total_sites,
        "successful_crawls": len(successful),
        "failed_crawls": len(failed),
        "sites_with_banners": len(with_banners),
        "sites_without_banners": len(without_banners),
    }

    # ── Pre-consent violations ────────────────────────────────────────────
    sites_with_trackers = 0
    tracker_counts: list[int] = []
    cat_tracker_data: dict[str, dict] = {}

    for s in successful:
        pre = s.get("pre_consent") or {}
        tp = pre.get("third_party_domains", [])
        n_trackers = len(tp)
        if n_trackers > 0:
            sites_with_trackers += 1
        tracker_counts.append(n_trackers)

        cat = s.get("category", "") or "Unknown"
        if cat not in cat_tracker_data:
            cat_tracker_data[cat] = {"with_trackers": 0, "total": 0, "counts": []}
        cat_tracker_data[cat]["total"] += 1
        cat_tracker_data[cat]["counts"].append(n_trackers)
        if n_trackers > 0:
            cat_tracker_data[cat]["with_trackers"] += 1

    by_category_violations = {}
    for cat, d in sorted(cat_tracker_data.items()):
        by_category_violations[cat] = {
            "count": d["with_trackers"],
            "total": d["total"],
            "percentage": _safe_pct(d["with_trackers"], d["total"]),
            "avg_trackers": round(statistics.mean(d["counts"]), 1) if d["counts"] else 0.0,
        }

    pre_consent_violations = {
        "sites_with_pre_consent_trackers": sites_with_trackers,
        "percentage": _safe_pct(sites_with_trackers, len(successful)),
        "avg_pre_consent_trackers_per_site": round(statistics.mean(tracker_counts), 1) if tracker_counts else 0.0,
        "median_pre_consent_trackers": round(statistics.median(tracker_counts)) if tracker_counts else 0,
        "by_category": by_category_violations,
    }

    # ── Tracker analysis ──────────────────────────────────────────────────
    all_classified_files = sorted(p_dir.glob("*_classified.json"))
    all_cookies: list[dict] = []
    site_vendor_presence: Counter = Counter()
    cookie_vendor_counter: Counter = Counter()
    category_counter: Counter = Counter()
    unique_tracker_domains: set = set()

    for cf in all_classified_files:
        try:
            cookies_doc = json.loads(cf.read_text(encoding="utf-8"))
            cookies = unwrap_payload(cookies_doc, "cookies")
        except Exception:
            continue
        domain_stem = cf.stem.replace("_classified", "")
        site_vendors_seen: set = set()
        for c in cookies:
            all_cookies.append(c)
            if c.get("is_tracker"):
                unique_tracker_domains.add(c.get("registered_domain", ""))
                vendor = c.get("vendor", "Unknown")
                cat = c.get("category", "Unknown")
                cookie_vendor_counter[vendor] += 1
                category_counter[cat] += 1
                if vendor not in site_vendors_seen:
                    site_vendor_presence[vendor] += 1
                    site_vendors_seen.add(vendor)

    top_vendors = []
    for vendor, site_count in site_vendor_presence.most_common(15):
        top_vendors.append({
            "vendor": vendor,
            "sites_present": site_count,
            "percentage": _safe_pct(site_count, len(successful)),
            "cookie_count": cookie_vendor_counter[vendor],
        })

    total_tracker_cookies = sum(1 for c in all_cookies if c.get("is_tracker"))
    tracker_categories = {}
    for cat, cnt in category_counter.most_common():
        tracker_categories[cat] = {
            "count": cnt,
            "percentage": _safe_pct(cnt, total_tracker_cookies) if total_tracker_cookies > 0 else 0.0,
        }

    # Before vs after consent
    avg_no_interaction: list[int] = []
    avg_after_accept: list[int] = []
    avg_after_reject: list[int] = []
    reject_reduces = 0
    reject_eliminates = 0

    for s in successful:
        pre = s.get("pre_consent") or {}
        post_a = s.get("post_consent_accept") or {}
        post_r = s.get("post_consent_reject") or {}

        pre_tp = len(pre.get("third_party_domains", []))
        avg_no_interaction.append(pre_tp)

        if post_a:
            avg_after_accept.append(len(post_a.get("third_party_domains", [])))
        if post_r:
            r_tp = len(post_r.get("third_party_domains", []))
            avg_after_reject.append(r_tp)
            if r_tp < pre_tp:
                reject_reduces += 1
            if r_tp == 0:
                reject_eliminates += 1

    n_with_reject_data = len(avg_after_reject)
    tracker_analysis = {
        "total_unique_trackers": total_tracker_cookies,
        "total_unique_tracker_domains": len(unique_tracker_domains),
        "top_tracker_vendors": top_vendors,
        "tracker_categories": tracker_categories,
        "before_vs_after_consent": {
            "avg_trackers_no_interaction": round(statistics.mean(avg_no_interaction), 1) if avg_no_interaction else 0.0,
            "avg_trackers_after_accept": round(statistics.mean(avg_after_accept), 1) if avg_after_accept else 0.0,
            "avg_trackers_after_reject": round(statistics.mean(avg_after_reject), 1) if avg_after_reject else 0.0,
            "reject_reduces_trackers_percentage": _safe_pct(reject_reduces, n_with_reject_data),
            "reject_eliminates_all_trackers_percentage": _safe_pct(reject_eliminates, n_with_reject_data),
        },
    }

    # ── Consent banner analysis ───────────────────────────────────────────
    sites_w_reject = 0
    sites_wo_reject = 0
    accept_clicks_list: list[int] = []
    reject_clicks_list: list[int] = []
    equal_effort = 0

    for s in successful:
        banner = s.get("consent_banner") or {}
        if not banner.get("found"):
            continue
        if banner.get("has_reject_button"):
            sites_w_reject += 1
        else:
            sites_wo_reject += 1
        ac = banner.get("accept_clicks_required", 999)
        rc = banner.get("reject_clicks_required", 999)
        if ac < 999:
            accept_clicks_list.append(ac)
        if rc < 999:
            reject_clicks_list.append(rc)
        if ac == rc and ac < 999:
            equal_effort += 1

    banner_total = sites_w_reject + sites_wo_reject
    consent_banner_analysis = {
        "sites_with_reject_button": {
            "count": sites_w_reject,
            "percentage": _safe_pct(sites_w_reject, banner_total),
        },
        "sites_without_reject_button": {
            "count": sites_wo_reject,
            "percentage": _safe_pct(sites_wo_reject, banner_total),
        },
        "avg_accept_clicks": round(statistics.mean(accept_clicks_list), 1) if accept_clicks_list else 0.0,
        "avg_reject_clicks": round(statistics.mean(reject_clicks_list), 1) if reject_clicks_list else 0.0,
        "sites_with_equal_click_effort": {
            "count": equal_effort,
            "percentage": _safe_pct(equal_effort, banner_total),
        },
    }

    # ── Dark patterns ─────────────────────────────────────────────────────
    dp_files = sorted(p_dir.glob("*_dark_patterns.json"))
    dp_type_counter: Counter = Counter()
    dp_count_list: list[int] = []
    sites_w_any_dp = 0

    for dpf in dp_files:
        try:
            dp = json.loads(dpf.read_text(encoding="utf-8"))
        except Exception:
            continue
        count = dp.get("dark_pattern_count", 0)
        dp_count_list.append(count)
        if count > 0:
            sites_w_any_dp += 1
        for dp_name in dp.get("dark_patterns_detected", []):
            dp_type_counter[dp_name] += 1

    dp_total = len(dp_count_list)
    dark_patterns = {
        "sites_with_any_dark_pattern": {
            "count": sites_w_any_dp,
            "percentage": _safe_pct(sites_w_any_dp, dp_total),
        },
        "avg_dark_patterns_per_site": round(statistics.mean(dp_count_list), 1) if dp_count_list else 0.0,
        "by_type": {},
    }
    for dp_name, cnt in dp_type_counter.most_common():
        dark_patterns["by_type"][dp_name] = {
            "count": cnt,
            "percentage": _safe_pct(cnt, dp_total),
        }

    # ── Compliance scores ─────────────────────────────────────────────────
    compliance_scores_section: dict = {}
    if not scores_df.empty and "overall_score" in scores_df.columns:
        sc = scores_df["overall_score"].tolist()
        grade_dist: dict = {}
        if "grade" in scores_df.columns:
            for g in ["A", "B", "C", "D", "F"]:
                cnt = int((scores_df["grade"] == g).sum())
                grade_dist[g] = {
                    "count": cnt,
                    "percentage": _safe_pct(cnt, len(sc)),
                }

        by_cat_scores: dict = {}
        if "category" in scores_df.columns:
            for cat, group in scores_df.groupby("category"):
                vals = group["overall_score"].tolist()
                by_cat_scores[str(cat)] = {
                    "avg_score": round(statistics.mean(vals), 1) if vals else 0.0,
                    "median": round(statistics.median(vals), 1) if vals else 0.0,
                }

        compliance_scores_section = {
            "avg_score": round(statistics.mean(sc), 1),
            "median_score": round(statistics.median(sc), 1),
            "std_dev": round(statistics.stdev(sc), 1) if len(sc) > 1 else 0.0,
            "min_score": round(min(sc), 1),
            "max_score": round(max(sc), 1),
            "grade_distribution": grade_dist,
            "by_category": by_cat_scores,
        }
    else:
        compliance_scores_section = {
            "avg_score": 0.0, "median_score": 0.0, "std_dev": 0.0,
            "min_score": 0.0, "max_score": 0.0,
            "grade_distribution": {}, "by_category": {},
        }

    # ── CMP analysis preview ──────────────────────────────────────────────
    cmp_counter: Counter = Counter()
    for s in successful:
        cmp = s.get("cmp_detected") or "Custom/Unknown"
        cmp_counter[cmp] += 1

    cmp_distribution = dict(cmp_counter.most_common())

    # ── Assemble final metrics ────────────────────────────────────────────
    return {
        "summary": summary,
        "pre_consent_violations": pre_consent_violations,
        "tracker_analysis": tracker_analysis,
        "consent_banner_analysis": consent_banner_analysis,
        "dark_patterns": dark_patterns,
        "compliance_scores": compliance_scores_section,
        "cmp_analysis_preview": {"cmp_distribution": cmp_distribution},
        **build_provenance(
            source_mode=source_mode,
            run_id=run_id or _infer_run_id(sites),
            site_list_source=_infer_site_list_source(sites),
        ),
    }


def _infer_run_id(sites: list[dict]) -> str | None:
    run_ids = {
        s.get("run_id")
        for s in sites
        if isinstance(s, dict) and s.get("run_id")
    }
    if len(run_ids) == 1:
        return next(iter(run_ids))
    return None


def _infer_site_list_source(sites: list[dict]) -> str | None:
    values = {
        s.get("site_list_source")
        for s in sites
        if isinstance(s, dict) and s.get("site_list_source")
    }
    if len(values) == 1:
        return next(iter(values))
    return None


def run_metrics(
    processed_dir: str | None = None,
    output_path: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> None:
    """Compute and save aggregate metrics to a JSON file."""
    layout = get_dataset_layout(source_mode)
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir
    out = Path(output_path) if output_path else p_dir / "aggregate_metrics.json"
    p_dir.mkdir(parents=True, exist_ok=True)

    metrics = compute_aggregate_metrics(
        processed_dir=processed_dir,
        source_mode=source_mode,
        run_id=run_id,
    )

    out.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    print(f"Metrics saved to {out}")

    # Print formatted summary
    s = metrics["summary"]
    print(f"\n{'=' * 60}")
    print("AGGREGATE METRICS SUMMARY")
    print(f"{'=' * 60}")
    print(f"Sites crawled:       {s['total_sites_crawled']}")
    print(f"  Successful:        {s['successful_crawls']}")
    print(f"  Failed:            {s['failed_crawls']}")
    print(f"  With banners:      {s['sites_with_banners']}")
    print(f"  Without banners:   {s['sites_without_banners']}")

    pv = metrics["pre_consent_violations"]
    print(f"\nPre-consent violations:")
    print(f"  Sites with trackers: {pv['sites_with_pre_consent_trackers']} ({pv['percentage']}%)")
    print(f"  Avg trackers/site:   {pv['avg_pre_consent_trackers_per_site']}")

    ta = metrics["tracker_analysis"]
    print(f"\nTrackers:")
    print(f"  Unique tracker cookies: {ta['total_unique_trackers']}")
    print(f"  Unique tracker domains: {ta['total_unique_tracker_domains']}")
    if ta["top_tracker_vendors"]:
        print(f"  Top vendors:")
        for v in ta["top_tracker_vendors"][:5]:
            print(f"    {v['vendor']:20s} {v['sites_present']} sites ({v['percentage']}%)")

    cs = metrics["compliance_scores"]
    print(f"\nCompliance scores:")
    print(f"  Average: {cs['avg_score']}")
    print(f"  Median:  {cs['median_score']}")
    print(f"  Std dev: {cs['std_dev']}")
    if cs["grade_distribution"]:
        print(f"  Grades:")
        for g in ["A", "B", "C", "D", "F"]:
            gd = cs["grade_distribution"].get(g, {})
            print(f"    {g}: {gd.get('count', 0)} ({gd.get('percentage', 0)}%)")

    dp = metrics["dark_patterns"]
    print(f"\nDark patterns:")
    print(f"  Sites with any: {dp['sites_with_any_dark_pattern']['count']} ({dp['sites_with_any_dark_pattern']['percentage']}%)")
    if dp["by_type"]:
        for name, info in dp["by_type"].items():
            print(f"    {name:30s} {info['count']:>3d} ({info['percentage']}%)")

    print(f"{'=' * 60}")


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AECCS aggregate metrics computation"
    )
    parser.add_argument(
        "--processed-dir", type=str, default=None,
        help=f"Processed data directory (default: {PROCESSED_DIR})",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON path (default: PROCESSED_DIR/aggregate_metrics.json)",
    )
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

    run_metrics(
        processed_dir=args.processed_dir,
        output_path=args.output,
        source_mode=args.source_mode,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
