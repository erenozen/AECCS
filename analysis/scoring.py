"""
GDPR compliance scoring.

Computes a 0-100 compliance score for each website based on six weighted
criteria defined in ``config.COMPLIANCE_WEIGHTS``:

1. no_pre_consent_trackers (0.30)
2. reject_option_available (0.20)
3. equal_accept_reject_effort (0.10)
4. no_dark_patterns (0.15)
5. post_reject_compliance (0.15)
6. transparent_information (0.10)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from config import (
    COMPLIANCE_WEIGHTS,
    DEFAULT_SOURCE_MODE,
    PROCESSED_DIR,
    RAW_DIR,
    build_provenance,
    get_dataset_layout,
    unwrap_payload,
)
from shared_constants import GRADE_THRESHOLDS, PRIVACY_LINK_KEYWORDS, PURPOSE_KEYWORDS, VENDOR_KEYWORDS

def _score_grade(score: float) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _count_pre_consent_trackers(
    site_data: dict, classified_cookies: list[dict]
) -> int:
    """Count tracker cookies present before any consent interaction."""
    pre = site_data.get("pre_consent") or {}
    pre_cookie_keys = {
        (c.get("name", ""), c.get("domain", ""))
        for c in pre.get("cookies", [])
    }
    count = 0
    for cc in classified_cookies:
        key = (cc.get("name", ""), cc.get("domain", ""))
        if key in pre_cookie_keys and cc.get("is_tracker"):
            count += 1

    # Also count third-party domains as tracker signals
    tp_domains = pre.get("third_party_domains", [])
    count += len(tp_domains)
    return count


def _score_no_pre_consent_trackers(
    site_data: dict, classified_cookies: list[dict]
) -> tuple[int | None, str]:
    """Criterion 1: No pre-consent trackers."""
    n = _count_pre_consent_trackers(site_data, classified_cookies)
    if n == 0:
        return 100, "No pre-consent trackers found"
    elif n <= 2:
        return 60, f"{n} pre-consent trackers found"
    elif n <= 5:
        return 30, f"{n} pre-consent trackers found"
    elif n <= 10:
        return 10, f"{n} pre-consent trackers found"
    else:
        return 0, f"{n} pre-consent trackers found"


def _score_reject_option(site_data: dict) -> tuple[int | None, str]:
    """Criterion 2: Reject option available."""
    banner = site_data.get("consent_banner") or {}
    if not banner.get("found"):
        return 0, "No consent banner found"
    if banner.get("has_reject_button"):
        clicks = banner.get("reject_clicks_required", 1)
        if clicks == 1:
            return 100, "Direct reject button available"
        elif clicks < 999:
            return 50, f"Reject available via {clicks} clicks (through settings)"
    return 0, "No reject option available"


def _score_equal_effort(site_data: dict) -> tuple[int | None, str]:
    """Criterion 3: Equal accept/reject effort."""
    banner = site_data.get("consent_banner") or {}
    a = banner.get("accept_clicks_required", 999)
    r = banner.get("reject_clicks_required", 999)

    if a == 999 and r == 999:
        return 0, "No functional accept/reject buttons"
    if r == 999:
        return 0, "No reject option"

    diff = r - a
    if diff <= 0:
        return 100, f"Equal clicks: {a} vs {r}"
    elif diff == 1:
        return 50, f"Reject requires 1 extra click ({a} vs {r})"
    else:
        return 20, f"Reject requires {diff} extra clicks ({a} vs {r})"


def _score_no_dark_patterns(dark_pattern_data: dict) -> tuple[int | None, str]:
    """Criterion 4: No dark patterns."""
    count = dark_pattern_data.get("dark_pattern_count", 0)
    detected = dark_pattern_data.get("dark_patterns_detected", [])
    names_str = ", ".join(detected) if detected else "none"
    if count == 0:
        return 100, "No dark patterns detected"
    elif count == 1:
        return 60, f"1 dark pattern detected: {names_str}"
    elif count == 2:
        return 30, f"2 dark patterns detected: {names_str}"
    else:
        return 0, f"{count} dark patterns detected: {names_str}"


def _score_post_reject_compliance(
    site_data: dict, classified_cookies: list[dict]
) -> tuple[int | None, str]:
    """Criterion 5: Post-reject compliance."""
    banner = site_data.get("consent_banner") or {}
    post_reject = site_data.get("post_consent_reject")
    post_accept = site_data.get("post_consent_accept")
    pre = site_data.get("pre_consent") or {}

    if not banner.get("found", False):
        return None, "Not available without a visible consent banner"

    has_reject_path = banner.get("has_reject_button", False) or (
        banner.get("reject_clicks_required", 999) < 999
    )

    if not has_reject_path:
        return 0, "No reject option available"

    if not post_reject or not isinstance(post_reject, dict):
        return None, "Not available in baseline audit (no verified post-reject data)"

    if not post_reject.get("reject_successful", False) and not post_reject.get("reject_button_found", False):
        return 0, "Reject was not successful"

    # Compare tracker counts
    pre_tp = set(pre.get("third_party_domains", []))
    reject_tp = set(post_reject.get("third_party_domains", []))
    new_tp_reject = post_reject.get("new_third_party_domains_after_interaction", [])
    new_cookies_reject = post_reject.get("new_cookies_after_interaction", [])

    # Count new tracker cookies after rejection
    new_tracker_count = len(new_tp_reject) + len(new_cookies_reject)

    if new_tracker_count == 0 and len(reject_tp) <= len(pre_tp):
        return 100, "No new trackers after rejection"

    # Compare with post-accept
    if post_accept and isinstance(post_accept, dict):
        accept_tp = set(post_accept.get("third_party_domains", []))
        if len(reject_tp) < len(accept_tp):
            return 50, "Some new trackers after reject, but fewer than accept"
        else:
            return 0, "Post-reject tracker count same or worse than post-accept"

    # No post-accept data for comparison, but new trackers appeared
    if new_tracker_count > 0:
        return 30, f"{new_tracker_count} new tracker signals after rejection"

    return 50, "Partial compliance after rejection"


def _score_transparent_information(site_data: dict) -> tuple[int | None, str]:
    """Criterion 6: Transparent information."""
    banner = site_data.get("consent_banner") or {}
    text = (banner.get("text_content") or "").lower()
    html = (banner.get("html") or "").lower()

    if not text and not html:
        return 0, "No banner text available"

    score = 0
    details = []

    # Mentions specific purposes?
    purpose_found = any(kw in text for kw in PURPOSE_KEYWORDS)
    if purpose_found:
        score += 30
        details.append("mentions purposes")

    # Mentions vendor names?
    vendor_found = any(kw in text for kw in VENDOR_KEYWORDS)
    if vendor_found:
        score += 30
        details.append("mentions vendors")

    # Privacy policy link?
    has_pp_link = False
    if html:
        for kw in PRIVACY_LINK_KEYWORDS:
            if kw in html:
                has_pp_link = True
                break
    if has_pp_link:
        score += 20
        details.append("privacy policy link")

    # Clear language (short sentences)?
    if text:
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if sentences:
            avg_words = sum(len(s.split()) for s in sentences) / len(sentences)
            if avg_words < 30:
                score += 20
                details.append("clear language")

    return min(score, 100), "; ".join(details) if details else "No transparency indicators"


# ── Public API ────────────────────────────────────────────────────────────────


def compute_compliance_score(
    site_data: dict,
    dark_pattern_data: dict,
    classified_cookies: list[dict],
) -> dict:
    """Compute the GDPR compliance score for a single website.

    Returns a dict with per-criterion scores, the weighted total (0-100),
    and a letter grade.
    """
    criteria_funcs = {
        "no_pre_consent_trackers": lambda: _score_no_pre_consent_trackers(site_data, classified_cookies),
        "reject_option_available": lambda: _score_reject_option(site_data),
        "equal_accept_reject_effort": lambda: _score_equal_effort(site_data),
        "no_dark_patterns": lambda: _score_no_dark_patterns(dark_pattern_data),
        "post_reject_compliance": lambda: _score_post_reject_compliance(site_data, classified_cookies),
        "transparent_information": lambda: _score_transparent_information(site_data),
    }

    criterion_scores = {}
    overall = 0.0
    total_weight = 0.0

    for criterion_name, func in criteria_funcs.items():
        raw_score, details = func()
        weight = COMPLIANCE_WEIGHTS.get(criterion_name, 0.0)
        weighted = None
        if isinstance(raw_score, (int, float)):
            weighted = raw_score * weight
            overall += weighted
            total_weight += weight
        criterion_scores[criterion_name] = {
            "score": raw_score,
            "weight": weight,
            "weighted_score": round(weighted, 2) if weighted is not None else None,
            "details": details,
        }

    if total_weight > 0 and total_weight != 1.0:
        overall = overall / total_weight

    overall = round(overall, 2)

    return {
        "domain": site_data.get("domain", ""),
        "category": site_data.get("category", ""),
        "overall_score": overall,
        "criterion_scores": criterion_scores,
        "grade": _score_grade(overall),
    }


def run_scoring(
    raw_dir: str | None = None,
    processed_dir: str | None = None,
    output_path: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> None:
    """Batch-score all websites and write results."""
    layout = get_dataset_layout(source_mode)
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir
    p_dir.mkdir(parents=True, exist_ok=True)
    csv_path = Path(output_path) if output_path else p_dir / "compliance_scores.csv"

    # Find raw site JSONs
    data_dir = Path(raw_dir) if raw_dir else layout.raw_dir
    raw_files = sorted(data_dir.glob("*.json"))
    if not raw_files:
        print(f"[WARN] No raw JSON files found in {data_dir}")
        return

    rows = []
    for rf in raw_files:
        domain = rf.stem
        try:
            site_data = json.loads(rf.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[ERROR] {domain}: cannot read raw data: {exc}")
            continue

        if not site_data.get("success", False):
            print(f"[SKIP] {domain}: crawl was not successful")
            continue

        # Load classified cookies
        cls_path = p_dir / f"{domain}_classified.json"
        classified_cookies = []
        if cls_path.exists():
            try:
                classified_doc = json.loads(cls_path.read_text(encoding="utf-8"))
                classified_cookies = unwrap_payload(classified_doc, "cookies")
            except Exception:
                pass

        # Load dark pattern data
        dp_path = p_dir / f"{domain}_dark_patterns.json"
        dark_pattern_data: dict = {"dark_pattern_count": 0, "dark_patterns_detected": []}
        if dp_path.exists():
            try:
                dark_pattern_data = json.loads(dp_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Compute score
        result = compute_compliance_score(site_data, dark_pattern_data, classified_cookies)

        # Save detailed per-site JSON
        provenance = build_provenance(
            source_mode=site_data.get("source_mode", source_mode),
            run_id=site_data.get("run_id", run_id),
            proxy_used=site_data.get("proxy_used"),
            browser_name=site_data.get("browser_name"),
            browser_version=site_data.get("browser_version"),
            site_list_source=site_data.get("site_list_source"),
        )
        result.update(provenance)

        score_json_path = p_dir / f"{domain}_score.json"
        score_json_path.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )

        # Build CSV row
        cs = result["criterion_scores"]
        pre = site_data.get("pre_consent") or {}
        row = {
            "domain": domain,
            "source_mode": provenance["source_mode"],
            "run_id": provenance["run_id"],
            "category": site_data.get("category", ""),
            "region": site_data.get("region", ""),
            "rank": site_data.get("rank", 0),
            "overall_score": result["overall_score"],
            "grade": result["grade"],
            "no_pre_consent_trackers": cs["no_pre_consent_trackers"]["score"],
            "reject_option_available": cs["reject_option_available"]["score"],
            "equal_accept_reject_effort": cs["equal_accept_reject_effort"]["score"],
            "no_dark_patterns": cs["no_dark_patterns"]["score"],
            "post_reject_compliance": cs["post_reject_compliance"]["score"],
            "transparent_information": cs["transparent_information"]["score"],
            "cmp_detected": site_data.get("cmp_detected", ""),
            "dark_pattern_count": dark_pattern_data.get("dark_pattern_count", 0),
            "pre_consent_tracker_count": pre.get("total_third_party_domains", 0),
            "total_pre_consent_cookies": pre.get("total_cookies", 0),
        }
        rows.append(row)
        print(f"[OK] {domain}: {result['overall_score']:.1f} ({result['grade']})")

    # Write CSV
    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(csv_path, index=False)
        print(f"\nScores saved to {csv_path}")

    # Summary
    if rows:
        scores = [r["overall_score"] for r in rows]
        avg = sum(scores) / len(scores)
        grades = [r["grade"] for r in rows]

        print(f"\n{'=' * 60}")
        print(f"Scoring complete: {len(rows)} sites scored")
        print(f"  Average score: {avg:.1f}")
        print(f"  Score range:   {min(scores):.1f} - {max(scores):.1f}")
        print(f"\nGrade distribution:")
        for g in ["A", "B", "C", "D", "F"]:
            cnt = grades.count(g)
            pct = cnt / len(grades) * 100 if grades else 0
            print(f"  {g}: {cnt} ({pct:.1f}%)")
        print(f"\nBest 5:")
        sorted_rows = sorted(rows, key=lambda r: r["overall_score"], reverse=True)
        for r in sorted_rows[:5]:
            print(f"  {r['domain']:30s} {r['overall_score']:6.1f} ({r['grade']})")
        print(f"\nWorst 5:")
        for r in sorted_rows[-5:]:
            print(f"  {r['domain']:30s} {r['overall_score']:6.1f} ({r['grade']})")

        # Average by category
        categories: dict[str, list[float]] = {}
        for r in rows:
            cat = r.get("category", "") or "Unknown"
            categories.setdefault(cat, []).append(r["overall_score"])
        if categories:
            print(f"\nAverage by category:")
            for cat, sc in sorted(categories.items()):
                print(f"  {cat:20s} {sum(sc)/len(sc):6.1f} (n={len(sc)})")
        print(f"{'=' * 60}")


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AECCS GDPR compliance scorer"
    )
    parser.add_argument(
        "--raw-dir", type=str, default=None,
        help=f"Raw data directory (default: {RAW_DIR})",
    )
    parser.add_argument(
        "--processed-dir", type=str, default=None,
        help=f"Processed data directory (default: {PROCESSED_DIR})",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output CSV path (default: PROCESSED_DIR/compliance_scores.csv)",
    )
    parser.add_argument(
        "--domain", type=str, default=None,
        help="Score a single domain only",
    )
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

    if args.domain:
        layout = get_dataset_layout(args.source_mode)
        p_dir = Path(args.processed_dir) if args.processed_dir else layout.processed_dir
        p_dir.mkdir(parents=True, exist_ok=True)

        site_path = layout.raw_dir / f"{args.domain}.json"
        if args.raw_dir:
            site_path = Path(args.raw_dir) / f"{args.domain}.json"
        if not site_path.exists():
            print(f"[ERROR] {site_path} not found")
            return
        site_data = json.loads(site_path.read_text(encoding="utf-8"))

        cls_path = p_dir / f"{args.domain}_classified.json"
        classified = []
        if cls_path.exists():
            classified_doc = json.loads(cls_path.read_text(encoding="utf-8"))
            classified = unwrap_payload(classified_doc, "cookies")

        dp_path = p_dir / f"{args.domain}_dark_patterns.json"
        dp_data: dict = {"dark_pattern_count": 0, "dark_patterns_detected": []}
        if dp_path.exists():
            dp_data = json.loads(dp_path.read_text(encoding="utf-8"))

        result = compute_compliance_score(site_data, dp_data, classified)
        provenance = build_provenance(
            source_mode=site_data.get("source_mode", args.source_mode),
            run_id=site_data.get("run_id", args.run_id),
            proxy_used=site_data.get("proxy_used"),
            browser_name=site_data.get("browser_name"),
            browser_version=site_data.get("browser_version"),
            site_list_source=site_data.get("site_list_source"),
        )
        result.update(provenance)

        out = p_dir / f"{args.domain}_score.json"
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"[OK] {args.domain}: {result['overall_score']:.1f} ({result['grade']})")
        for cname, cval in result["criterion_scores"].items():
            print(f"  {cname:35s} {cval['score']:>3d} x {cval['weight']:.2f} = {cval['weighted_score']:5.1f}  ({cval['details']})")
        return

    run_scoring(
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        output_path=args.output,
        source_mode=args.source_mode,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
