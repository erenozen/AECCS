"""
HTML report generator for GDPR cookie-consent compliance analysis.

Produces a single self-contained HTML report with embedded base64 images,
inline CSS, and automatically generated prose from the analysis data.

Usage:
    python -m reporting.report_generator
    python -m reporting.report_generator --open
"""

from __future__ import annotations

import argparse
import base64
import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import DEFAULT_SOURCE_MODE, PROCESSED_DIR, get_dataset_layout


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """\
:root {
  --primary: #2563EB;
  --danger: #DC2626;
  --success: #059669;
  --warning: #D97706;
  --bg: #f9fafb;
  --card-bg: #ffffff;
  --border: #e5e7eb;
  --text: #111827;
  --muted: #6b7280;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: var(--text);
  background: var(--bg);
  line-height: 1.6;
  font-size: 15px;
}

.container { max-width: 920px; margin: 0 auto; padding: 2rem 1.5rem; }

header { background: var(--primary); color: #fff; padding: 2.5rem 0; text-align: center; }
header h1 { font-size: 1.8rem; margin-bottom: .3rem; }
header .subtitle { font-size: 1rem; opacity: .85; }
header .meta { font-size: .8rem; opacity: .7; margin-top: .6rem; }

nav { background: var(--card-bg); border-bottom: 1px solid var(--border); padding: .8rem 0; position: sticky; top: 0; z-index: 10; }
nav .container { display: flex; flex-wrap: wrap; gap: .5rem 1.2rem; }
nav a { color: var(--primary); text-decoration: none; font-size: .85rem; font-weight: 500; }
nav a:hover { text-decoration: underline; }

section { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; margin: 1.5rem 0; padding: 1.8rem; }
h2 { font-size: 1.35rem; margin-bottom: 1rem; color: var(--primary); border-bottom: 2px solid var(--primary); padding-bottom: .35rem; }
h3 { font-size: 1.1rem; margin: 1.2rem 0 .6rem; }
p { margin-bottom: .8rem; }

figure { margin: 1.2rem 0; text-align: center; }
figure img { max-width: 100%; height: auto; border: 1px solid var(--border); border-radius: 4px; }
figure figcaption { font-size: .8rem; color: var(--muted); margin-top: .3rem; }

table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .85rem; }
th, td { padding: .45rem .6rem; text-align: left; border-bottom: 1px solid var(--border); }
th { background: #f3f4f6; font-weight: 600; position: sticky; top: 0; }
tr:nth-child(even) { background: #f9fafb; }

.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin: 1rem 0; }
.stat-card { border-left: 4px solid var(--primary); background: #eff6ff; border-radius: 4px; padding: .8rem 1rem; }
.stat-card.danger { border-left-color: var(--danger); background: #fef2f2; }
.stat-card.success { border-left-color: var(--success); background: #ecfdf5; }
.stat-card.warning { border-left-color: var(--warning); background: #fffbeb; }
.stat-card .number { font-size: 1.6rem; font-weight: 700; }
.stat-card .label { font-size: .8rem; color: var(--muted); }

.placeholder { background: #f3f4f6; border: 2px dashed #d1d5db; border-radius: 6px; padding: 2rem; text-align: center; color: var(--muted); font-style: italic; }

footer { text-align: center; padding: 2rem 0; font-size: .8rem; color: var(--muted); border-top: 1px solid var(--border); margin-top: 2rem; }

@media print {
  nav { display: none; }
  body { background: #fff; }
  section { break-inside: avoid; border: none; box-shadow: none; }
  header { background: var(--primary); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _embed_image(path: Path) -> str:
    """Return base64 <img> tag, or placeholder div."""
    if path.exists():
        data = base64.b64encode(path.read_bytes()).decode()
        ext = path.suffix.lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}.get(ext, "image/png")
        return f'<img src="data:{mime};base64,{data}" alt="{path.stem}">'
    return f'<div class="placeholder">Figure not available: {path.name}</div>'


def _stat_card(number: str, label: str, variant: str = "") -> str:
    cls = f"stat-card {variant}" if variant else "stat-card"
    return f'<div class="{cls}"><div class="number">{number}</div><div class="label">{label}</div></div>'


def _pct_prose(pct: float) -> str:
    """Return a natural-language qualifier for a percentage."""
    if pct >= 90:
        return f"Nearly all sites ({pct:.1f}%)"
    if pct >= 70:
        return f"A large majority of sites ({pct:.1f}%)"
    if pct >= 50:
        return f"A majority of sites ({pct:.1f}%)"
    if pct >= 30:
        return f"A substantial minority of sites ({pct:.1f}%)"
    return f"A minority of sites ({pct:.1f}%)"


def _df_to_html(df: pd.DataFrame, max_rows: int = 30) -> str:
    """Convert a DataFrame to a styled HTML table."""
    return df.head(max_rows).to_html(index=False, classes="data-table", border=0,
                                      float_format=lambda x: f"{x:.1f}")


def _collect_source_modes(processed_dir: Path) -> tuple[set[str], list[str]]:
    """Collect source_mode values from processed JSON and CSV artifacts."""
    modes: set[str] = set()
    missing: list[str] = []

    for path in sorted(processed_dir.glob("*_classified.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        mode = data.get("source_mode") if isinstance(data, dict) else None
        if mode:
            modes.add(str(mode))
        else:
            missing.append(path.name)

    for path in sorted(processed_dir.glob("*_dark_patterns.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        mode = data.get("source_mode") if isinstance(data, dict) else None
        if mode:
            modes.add(str(mode))
        else:
            missing.append(path.name)

    for path in sorted(processed_dir.glob("*_score.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        mode = data.get("source_mode") if isinstance(data, dict) else None
        if mode:
            modes.add(str(mode))
        else:
            missing.append(path.name)

    for name in (
        "aggregate_metrics.json",
        "dp_aggregate_metrics.json",
        "cmp_comparison_detailed.json",
        "pets_summary.json",
    ):
        path = processed_dir / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        mode = data.get("source_mode") if isinstance(data, dict) else None
        if mode:
            modes.add(str(mode))
        else:
            missing.append(name)

    for name in ("compliance_scores.csv", "pets_effectiveness.csv", "cmp_comparison.csv"):
        path = processed_dir / name
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if df.empty:
            continue
        if "source_mode" not in df.columns:
            missing.append(name)
            continue
        modes.update({str(v) for v in df["source_mode"].dropna().unique()})

    return modes, missing


def _validate_processed_inputs(processed_dir: Path, expected_source_mode: str) -> str:
    """Reject mixed or provenance-free processed directories."""
    modes, missing = _collect_source_modes(processed_dir)
    if missing:
        raise ValueError(
            "Processed inputs are missing provenance fields for: " + ", ".join(sorted(missing))
        )
    if len(modes) > 1:
        raise ValueError(
            "Mixed processed inputs detected; report generation requires a single source_mode."
        )
    if modes and modes != {expected_source_mode}:
        raise ValueError(
            f"Processed inputs are tagged as {sorted(modes)} but source_mode={expected_source_mode!r} was requested."
        )
    return next(iter(modes)) if modes else expected_source_mode


# ── Report builder ────────────────────────────────────────────────────────────


def generate_html_report(
    processed_dir: str | None = None,
    figures_dir: str | None = None,
    output_path: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
) -> Path:
    layout = get_dataset_layout(source_mode)
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir
    f_dir = Path(figures_dir) if figures_dir else layout.figures_dir
    out = Path(output_path) if output_path else layout.html_report
    out.parent.mkdir(parents=True, exist_ok=True)
    effective_source_mode = _validate_processed_inputs(p_dir, source_mode)

    # ── Load data ─────────────────────────────────────────────────────────
    metrics: dict = {}
    metrics_path = p_dir / "aggregate_metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    scores_df = pd.DataFrame()
    scores_path = p_dir / "compliance_scores.csv"
    if scores_path.exists():
        scores_df = pd.read_csv(scores_path)

    pets_df = pd.DataFrame()
    pets_path = p_dir / "pets_effectiveness.csv"
    if pets_path.exists():
        pets_df = pd.read_csv(pets_path)

    dp_report: dict = {}
    dp_path = p_dir / "dp_aggregate_metrics.json"
    if dp_path.exists():
        dp_report = json.loads(dp_path.read_text(encoding="utf-8"))

    cmp_df = pd.DataFrame()
    cmp_path = p_dir / "cmp_comparison.csv"
    if cmp_path.exists():
        cmp_df = pd.read_csv(cmp_path)

    cmp_detailed: dict = {}
    cmp_det_path = p_dir / "cmp_comparison_detailed.json"
    if cmp_det_path.exists():
        cmp_detailed = json.loads(cmp_det_path.read_text(encoding="utf-8"))

    pets_summary: dict = {}
    ps_path = p_dir / "pets_summary.json"
    if ps_path.exists():
        pets_summary = json.loads(ps_path.read_text(encoding="utf-8"))

    # ── Derived values ────────────────────────────────────────────────────
    summary = metrics.get("summary", {})
    n_sites = summary.get("total_sites_crawled", len(scores_df))
    n_success = summary.get("successful_crawls", n_sites)
    pv = metrics.get("pre_consent_violations", {})
    pv_pct = pv.get("percentage", 0)
    cs = metrics.get("compliance_scores", {})
    avg_score = cs.get("avg_score", 0)
    dp_data = metrics.get("dark_patterns", {})
    dp_any_pct = 0
    dp_any = dp_data.get("sites_with_any_dark_pattern", {})
    if isinstance(dp_any, dict):
        dp_any_pct = dp_any.get("percentage", 0)
    elif isinstance(dp_any, (int, float)):
        dp_any_pct = dp_any / n_success * 100 if n_success else 0

    bva = metrics.get("tracker_analysis", {}).get("before_vs_after_consent", {})
    n_pets = pets_df["pet_name"].nunique() if not pets_df.empty else 0

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── HTML sections ─────────────────────────────────────────────────────
    parts: list[str] = []

    # Header
    parts.append(f"""
<header>
  <div class="container">
    <h1>GDPR Cookie Consent Compliance Analysis Report</h1>
    <p class="subtitle">Automated Analysis of Privacy Risks on Popular Websites</p>
    <p class="meta">Generated: {timestamp} &nbsp;|&nbsp; Dataset: {effective_source_mode} &nbsp;|&nbsp; Sites analyzed: {n_sites} &nbsp;|&nbsp; PETs evaluated: {n_pets}</p>
  </div>
</header>
""")

    # Nav
    parts.append("""
<nav><div class="container">
  <a href="#executive-summary">Executive Summary</a>
  <a href="#compliance-overview">Compliance Overview</a>
  <a href="#cmp-distribution">CMP Distribution</a>
  <a href="#pre-consent-violations">Pre-Consent Violations</a>
  <a href="#tracker-ecosystem">Tracker Ecosystem</a>
  <a href="#consent-banners">Consent Banners</a>
  <a href="#dark-patterns">Dark Patterns</a>
  <a href="#pets-evaluation">PETs Evaluation</a>
  <a href="#methodology">Methodology</a>
</div></nav>
""")

    parts.append('<div class="container">')

    # ── Executive Summary ─────────────────────────────────────────────
    best_pet = ""
    bp_ranking = pets_summary.get("browser_pets_ranking", [])
    if bp_ranking:
        best_pet = bp_ranking[0].get("pet_name", "N/A")

    exec_p1 = (
        f"This report presents the findings of an automated GDPR compliance analysis "
        f"covering {n_sites} websites across multiple categories and regions. "
        f"The analysis examines pre-consent tracking behavior, dark pattern usage in "
        f"cookie consent banners, and the effectiveness of various privacy-enhancing "
        f"technologies (PETs) as countermeasures."
    )
    exec_p2 = (
        f"{_pct_prose(pv_pct)} were found to set tracking cookies before any user "
        f"consent was given, violating GDPR Article 5(3). The average compliance score "
        f"across all sites was {avg_score:.1f} out of 100."
    )
    exec_p3 = ""
    if dp_any_pct:
        exec_p3 = (
            f"{_pct_prose(dp_any_pct)} employed at least one dark pattern in their "
            f"cookie consent interface, undermining the principle of freely given consent."
        )
    exec_p4 = ""
    if best_pet:
        rd = bp_ranking[0].get("avg_tracker_reduction_pct", 0) if bp_ranking else 0
        exec_p4 = (
            f"Among the browser-based PETs evaluated, <strong>{best_pet}</strong> proved most "
            f"effective, reducing tracker exposure by an average of {rd:.1f}%."
        )

    parts.append(f"""
<section id="executive-summary">
  <h2>Executive Summary</h2>
  <p>{exec_p1}</p>
  <p>{exec_p2}</p>
  {"<p>" + exec_p3 + "</p>" if exec_p3 else ""}
  {"<p>" + exec_p4 + "</p>" if exec_p4 else ""}

  <div class="stat-grid">
    {_stat_card(f"{pv_pct:.0f}%", "Pre-Consent Tracker Violations", "danger")}
    {_stat_card(f"{avg_score:.0f}", "Average Compliance Score (0-100)", "warning")}
    {_stat_card(f"{dp_any_pct:.0f}%", "Sites with Dark Patterns", "danger")}
    {_stat_card(f"{n_pets}", "PETs Evaluated", "")}
  </div>

  <figure>
    {_embed_image(f_dir / "summary_dashboard.png")}
    <figcaption>Figure 0: Key findings overview dashboard.</figcaption>
  </figure>
</section>
""")

    # ── Compliance Overview ───────────────────────────────────────────
    grade_dist = cs.get("grade_distribution", {})
    grade_table_rows = ""
    for g in ["A", "B", "C", "D", "F"]:
        v = grade_dist.get(g, {})
        cnt = v.get("count", 0) if isinstance(v, dict) else int(v)
        pct = v.get("percentage", 0) if isinstance(v, dict) else 0
        grade_table_rows += f"<tr><td>{g}</td><td>{cnt}</td><td>{pct:.1f}%</td></tr>\n"

    top5_html = ""
    bottom5_html = ""
    if not scores_df.empty:
        top5 = scores_df.nlargest(5, "overall_score")[["domain", "category", "overall_score", "grade"]]
        bottom5 = scores_df.nsmallest(5, "overall_score")[["domain", "category", "overall_score", "grade"]]
        top5_html = f"<h3>Most Compliant Sites</h3>\n{_df_to_html(top5)}"
        bottom5_html = f"<h3>Least Compliant Sites</h3>\n{_df_to_html(bottom5)}"

    parts.append(f"""
<section id="compliance-overview">
  <h2>GDPR Compliance Overview</h2>

  <figure>
    {_embed_image(f_dir / "compliance_score_distribution.png")}
    <figcaption>Figure 1: Distribution of GDPR compliance scores across all analyzed sites.</figcaption>
  </figure>

  <h3>Grade Distribution</h3>
  <table>
    <thead><tr><th>Grade</th><th>Count</th><th>Percentage</th></tr></thead>
    <tbody>{grade_table_rows}</tbody>
  </table>

  <figure>
    {_embed_image(f_dir / "compliance_heatmap.png")}
    <figcaption>Figure 2: Average compliance score broken down by category and region/CMP.</figcaption>
  </figure>

  <div class="stat-grid">
    {_stat_card(f"{avg_score:.1f}", "Average Score", "warning")}
    {_stat_card(f"{cs.get('median_score', 0):.1f}", "Median Score", "warning")}
    {_stat_card(f"{cs.get('min_score', 0):.0f} - {cs.get('max_score', 0):.0f}", "Score Range", "")}
    {_stat_card(f"{cs.get('std_dev', 0):.1f}", "Std Deviation", "")}
  </div>
""")

    # Category breakdown table
    by_cat = cs.get("by_category", {})
    if by_cat:
        cat_score_rows = ""
        for cat_name, cat_val in sorted(by_cat.items(),
                                         key=lambda x: x[1].get("avg_score", 0) if isinstance(x[1], dict) else 0,
                                         reverse=True):
            if isinstance(cat_val, dict):
                cat_score_rows += (
                    f"<tr><td>{cat_name}</td>"
                    f"<td>{cat_val.get('avg_score', 0):.1f}</td>"
                    f"<td>{cat_val.get('median', 0):.1f}</td></tr>\n"
                )
        parts.append(f"""
  <h3>Compliance by Category</h3>
  <table>
    <thead><tr><th>Category</th><th>Avg Score</th><th>Median</th></tr></thead>
    <tbody>{cat_score_rows}</tbody>
  </table>
""")

    parts.append(f"""
  {top5_html}
  {bottom5_html}
</section>
""")

    # ── CMP Distribution ──────────────────────────────────────────────
    cmp_preview = metrics.get("cmp_analysis_preview", {})
    cmp_dist = cmp_preview.get("cmp_distribution", {})
    if cmp_dist:
        cmp_dist_rows = ""
        for cmp_name, cnt in sorted(cmp_dist.items(), key=lambda x: x[1], reverse=True):
            cmp_dist_rows += f"<tr><td>{cmp_name}</td><td>{cnt}</td></tr>\n"
        parts.append(f"""
<section id="cmp-distribution">
  <h2>CMP Distribution</h2>
  <p>Consent Management Platforms identified across the {n_sites} analyzed sites:</p>
  <table>
    <thead><tr><th>CMP</th><th>Sites</th></tr></thead>
    <tbody>{cmp_dist_rows}</tbody>
  </table>
</section>
""")

    # ── Pre-Consent Violations ────────────────────────────────────────
    avg_trackers = pv.get("avg_pre_consent_trackers_per_site", 0)
    parts.append(f"""
<section id="pre-consent-violations">
  <h2>Pre-Consent Tracking Violations</h2>

  <div class="stat-grid">
    {_stat_card(f"{pv_pct:.0f}%", "Sites Setting Pre-Consent Trackers", "danger")}
    {_stat_card(f"{avg_trackers:.1f}", "Avg Trackers Per Site (Before Consent)", "warning")}
    {_stat_card(f"{bva.get('avg_trackers_after_accept', 0):.1f}", "Avg Trackers After Accept", "danger")}
    {_stat_card(f"{bva.get('avg_trackers_after_reject', 0):.1f}", "Avg Trackers After Reject", "success")}
  </div>

  <figure>
    {_embed_image(f_dir / "violation_rates_by_category.png")}
    <figcaption>Figure 3: Pre-consent tracker violation rates by website category.</figcaption>
  </figure>

  <figure>
    {_embed_image(f_dir / "cookie_comparison_by_category.png")}
    <figcaption>Figure 4: Average tracker count by consent state and website category.</figcaption>
  </figure>

  <figure>
    {_embed_image(f_dir / "tracker_vendor_share.png")}
    <figcaption>Figure 5: Tracker vendor prevalence across analyzed websites.</figcaption>
  </figure>
""")

    # ── Pre-Consent Violations by Category ───────────────────────────
    pv_by_cat = pv.get("by_category", {})
    if pv_by_cat:
        pv_cat_rows = ""
        for cat_name, cat_data in sorted(pv_by_cat.items(),
                                          key=lambda x: x[1].get("percentage", 0),
                                          reverse=True):
            pv_cat_rows += (
                f"<tr><td>{cat_name}</td>"
                f"<td>{cat_data.get('count', 0)}/{cat_data.get('total', 0)}</td>"
                f"<td>{cat_data.get('percentage', 0):.1f}%</td>"
                f"<td>{cat_data.get('avg_trackers', 0):.1f}</td></tr>\n"
            )
        parts.append(f"""
  <h3>Pre-Consent Violations by Category</h3>
  <table>
    <thead><tr><th>Category</th><th>Sites Affected</th><th>Violation Rate</th><th>Avg Trackers</th></tr></thead>
    <tbody>{pv_cat_rows}</tbody>
  </table>
""")

    # ── Tracker Ecosystem ─────────────────────────────────────────────
    ta = metrics.get("tracker_analysis", {})
    top_vendors = ta.get("top_tracker_vendors", [])
    tracker_cats = ta.get("tracker_categories", {})

    vendor_rows = ""
    for v in top_vendors[:10]:
        vendor_rows += (
            f"<tr><td>{v.get('vendor', '')}</td>"
            f"<td>{v.get('sites_present', 0)}</td>"
            f"<td>{v.get('percentage', 0):.1f}%</td>"
            f"<td>{v.get('cookie_count', 0)}</td></tr>\n"
        )

    cat_rows = ""
    for cat_name, cat_val in sorted(tracker_cats.items(),
                                     key=lambda x: x[1].get("percentage", 0) if isinstance(x[1], dict) else 0,
                                     reverse=True):
        if isinstance(cat_val, dict):
            cat_rows += (
                f"<tr><td>{cat_name}</td>"
                f"<td>{cat_val.get('count', 0)}</td>"
                f"<td>{cat_val.get('percentage', 0):.1f}%</td></tr>\n"
            )

    tracker_eco_html = ""
    if vendor_rows or cat_rows:
        tracker_eco_html = f"""
<section id="tracker-ecosystem">
  <h2>Tracker Ecosystem</h2>
  <div class="stat-grid">
    {_stat_card(str(ta.get("total_unique_trackers", 0)), "Unique Tracker Cookies", "danger")}
    {_stat_card(str(ta.get("total_unique_tracker_domains", 0)), "Unique Tracker Domains", "warning")}
  </div>
"""
        if vendor_rows:
            tracker_eco_html += f"""
  <h3>Top Tracker Vendors</h3>
  <table>
    <thead><tr><th>Vendor</th><th>Sites Present</th><th>Share</th><th>Cookies</th></tr></thead>
    <tbody>{vendor_rows}</tbody>
  </table>
"""
        if cat_rows:
            tracker_eco_html += f"""
  <h3>Tracker Categories</h3>
  <table>
    <thead><tr><th>Category</th><th>Count</th><th>Percentage</th></tr></thead>
    <tbody>{cat_rows}</tbody>
  </table>
"""
        tracker_eco_html += "</section>\n"
        parts.append(tracker_eco_html)

    # ── Consent Banner & Reject Effectiveness ───────────────────────
    cba = metrics.get("consent_banner_analysis", {})
    bva = metrics.get("tracker_analysis", {}).get("before_vs_after_consent", {})
    sum_info = metrics.get("summary", {})
    sites_with_banner = sum_info.get("sites_with_banners", 0)
    reject_btn = cba.get("sites_with_reject_button", {})
    reject_btn_pct = reject_btn.get("percentage", 0) if isinstance(reject_btn, dict) else 0
    reject_btn_cnt = reject_btn.get("count", 0) if isinstance(reject_btn, dict) else 0
    equal_effort = cba.get("sites_with_equal_click_effort", {})
    equal_effort_pct = equal_effort.get("percentage", 0) if isinstance(equal_effort, dict) else 0
    reject_reduces_pct = bva.get("reject_reduces_trackers_percentage", 0)
    reject_eliminates_pct = bva.get("reject_eliminates_all_trackers_percentage", 0)
    avg_after_reject = bva.get("avg_trackers_after_reject", 0)
    avg_no_interaction = bva.get("avg_trackers_no_interaction", 0)

    parts.append(f"""
<section id="consent-banners">
  <h2>Consent Banner & Reject Effectiveness</h2>
  <div class="stat-grid">
    {_stat_card(str(sites_with_banner), "Sites with Consent Banner", "")}
    {_stat_card(f"{reject_btn_cnt} ({reject_btn_pct:.1f}%)", "Visible Reject Button", "warning")}
    {_stat_card(f"{equal_effort_pct:.1f}%", "Equal Accept/Reject Effort", "warning")}
    {_stat_card(f"{reject_reduces_pct:.1f}%", "Reject Actually Reduces Trackers", "danger")}
  </div>
  <p>
    Of the {sites_with_banner} sites that displayed a consent banner, only {reject_btn_cnt}
    ({reject_btn_pct:.1f}%) provided a visible "Reject All" button. {equal_effort_pct:.1f}% of
    sites offered equal click effort for accept and reject.
  </p>
  <p>
    Clicking "Reject All" reduced tracker counts on only {reject_reduces_pct:.1f}% of sites
    and eliminated all trackers on just {reject_eliminates_pct:.1f}%.
    On average, sites retained {avg_after_reject:.1f} trackers after rejection compared to
    {avg_no_interaction:.1f} before interaction.
  </p>
</section>
""")

    # Extra consent banner detail (appended right after the section close, re-open not needed)
    avg_accept_clicks = cba.get("avg_accept_clicks", 0)
    avg_reject_clicks = cba.get("avg_reject_clicks", 0)
    no_reject_info = cba.get("sites_without_reject_button", {})
    no_reject_cnt = no_reject_info.get("count", 0) if isinstance(no_reject_info, dict) else 0
    no_reject_pct = no_reject_info.get("percentage", 0) if isinstance(no_reject_info, dict) else 0
    equal_cnt = equal_effort.get("count", 0) if isinstance(equal_effort, dict) else 0

    parts.append(f"""
<section id="consent-banners-detail">
  <h3>Accept vs. Reject Click Effort</h3>
  <p>
    Accepting consent required an average of {avg_accept_clicks} click(s),
    while rejecting required {avg_reject_clicks} click(s) —
    {equal_cnt} sites ({equal_effort_pct:.1f}%) offered equal effort for both actions.
    {no_reject_cnt} sites ({no_reject_pct:.1f}%) had no visible reject button at all.
  </p>
</section>
""")

    # ── Dark Patterns ─────────────────────────────────────────────────
    dp_by_type = dp_data.get("by_type", {})
    dp_table_rows = ""
    for name, val in sorted(dp_by_type.items(),
                            key=lambda x: (x[1].get("percentage", 0) if isinstance(x[1], dict) else 0),
                            reverse=True):
        if isinstance(val, dict):
            cnt = val.get("count", 0)
            pct = val.get("percentage", 0)
        else:
            cnt = int(val)
            pct = 0
        nice_name = name.replace("_", " ").title()
        dp_table_rows += f"<tr><td>{nice_name}</td><td>{cnt}</td><td>{pct:.1f}%</td></tr>\n"

    parts.append(f"""
<section id="dark-patterns">
  <h2>Dark Pattern Analysis</h2>

  <figure>
    {_embed_image(f_dir / "dark_pattern_prevalence.png")}
    <figcaption>Figure 6: Prevalence of dark patterns in cookie consent banners.</figcaption>
  </figure>

  <h3>Dark Pattern Types Detected</h3>
  <table>
    <thead><tr><th>Pattern Type</th><th>Sites Affected</th><th>Percentage</th></tr></thead>
    <tbody>{dp_table_rows}</tbody>
  </table>
</section>
""")

    # ── PETs Evaluation ───────────────────────────────────────────────
    # Browser PETs
    bp_table = ""
    if bp_ranking:
        rows_html = ""
        for r in bp_ranking:
            rows_html += (
                f"<tr><td>{r.get('rank', '')}</td><td>{r.get('pet_name', '')}</td>"
                f"<td>{r.get('avg_tracker_reduction_pct', 0):.1f}%</td>"
                f"<td>{r.get('avg_tracker_domains', 0):.1f}</td>"
                f"<td>{r.get('sites_tested', 0)}</td></tr>\n"
            )
        bp_table = f"""
  <h3>Browser PET Rankings</h3>
  <table>
    <thead><tr><th>Rank</th><th>PET</th><th>Avg Reduction</th><th>Avg Trackers</th><th>Sites</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>"""

    # CMP rankings
    cmp_table = ""
    if not cmp_df.empty:
        cmp_show = cmp_df[["cmp_name", "site_count", "avg_compliance_score",
                            "pct_with_reject_button", "pct_reject_works",
                            "pct_with_dark_patterns", "pet_score", "rank"]].copy()
        cmp_show.columns = ["CMP", "Sites", "Avg Score", "Reject %", "Works %", "DP %", "PET Score", "Rank"]
        cmp_table = f"<h3>CMP Rankings</h3>\n{_df_to_html(cmp_show)}"

    # PET+CMP combinations
    combos = pets_summary.get("combination_analysis", [])
    combo_table = ""
    if combos:
        combo_rows = ""
        for c in combos[:10]:
            combo_rows += (
                f"<tr><td>{c.get('browser_pet', '')}</td>"
                f"<td>{c.get('cmp', '')}</td>"
                f"<td>{c.get('estimated_combined_effectiveness_pct', 0):.1f}%</td></tr>\n"
            )
        combo_table = f"""
  <h3>Best PET + CMP Combinations</h3>
  <table>
    <thead><tr><th>Browser PET</th><th>CMP</th><th>Est. Effectiveness</th></tr></thead>
    <tbody>{combo_rows}</tbody>
  </table>"""

    # DP section with full epsilon tradeoff table
    rec_eps = dp_report.get("metadata", {}).get("recommended_epsilon", "N/A")
    dp_tradeoff = dp_report.get("privacy_utility_tradeoff", {})

    # Compute average MAE per epsilon across all metrics
    eps_mae: dict[str, list[float]] = {}
    for _metric_name, metric_data in dp_tradeoff.items():
        if not isinstance(metric_data, dict):
            continue
        by_eps = metric_data.get("by_epsilon", {})
        for eps_str, eps_data in by_eps.items():
            if isinstance(eps_data, dict) and "mae" in eps_data:
                eps_mae.setdefault(eps_str, []).append(eps_data["mae"])

    eps_table_rows = ""
    utility_labels = {
        "0.1": "Low (high privacy)",
        "0.5": "Moderate",
        "1.0": "Balanced (recommended)",
        "2.0": "Good utility",
        "5.0": "High utility",
        "10.0": "Near-exact",
    }
    for eps_str in sorted(eps_mae.keys(), key=float):
        avg_mae = sum(eps_mae[eps_str]) / len(eps_mae[eps_str])
        label = utility_labels.get(eps_str, "")
        bold_open = "<strong>" if eps_str == str(rec_eps) else ""
        bold_close = "</strong>" if eps_str == str(rec_eps) else ""
        eps_table_rows += (
            f"<tr><td>{bold_open}{eps_str}{bold_close}</td>"
            f"<td>{bold_open}{avg_mae:.2f}{bold_close}</td>"
            f"<td>{bold_open}{label}{bold_close}</td></tr>\n"
        )

    dp_section = f"""
  <h3>Differential Privacy</h3>
  <p>
    Differential privacy mechanisms (Laplace, Gaussian, and Randomized Response) were applied
    to the aggregate compliance metrics to evaluate the feasibility of publishing statistics
    while protecting individual website data. Multiple privacy budgets (epsilon) were tested.
  </p>
  <p><strong>Recommended epsilon for publication: {rec_eps}</strong></p>
"""
    if eps_table_rows:
        dp_section += f"""
  <h3>Privacy-Utility Tradeoff</h3>
  <table>
    <thead><tr><th>Epsilon</th><th>Avg MAE</th><th>Utility</th></tr></thead>
    <tbody>{eps_table_rows}</tbody>
  </table>
"""
    # Per-metric MAE breakdown table
    per_metric_rows = ""
    for metric_name, metric_data in dp_tradeoff.items():
        if not isinstance(metric_data, dict):
            continue
        by_eps = metric_data.get("by_epsilon", {})
        true_val = metric_data.get("true_value", "")
        row = f"<tr><td>{metric_name}</td><td>{true_val}</td>"
        for eps_str in sorted(by_eps.keys(), key=float):
            eps_data = by_eps[eps_str]
            if isinstance(eps_data, dict):
                row += f"<td>{eps_data.get('mae', 0):.2f}</td>"
        row += "</tr>\n"
        per_metric_rows += row

    if per_metric_rows:
        eps_headers = "".join(
            f"<th>\u03b5={e}</th>"
            for e in sorted(
                next(iter(dp_tradeoff.values())).get("by_epsilon", {}).keys(),
                key=float,
            )
            if isinstance(next(iter(dp_tradeoff.values())), dict)
        )
        dp_section += f"""
  <h3>Per-Metric MAE Breakdown</h3>
  <table>
    <thead><tr><th>Metric</th><th>True Value</th>{eps_headers}</tr></thead>
    <tbody>{per_metric_rows}</tbody>
  </table>
"""

    # Randomized Response detail
    rr_data = dp_report.get("randomized_response_analysis", {})
    if rr_data:
        rr_rows = ""
        for attr_name, attr_data in rr_data.items():
            if not isinstance(attr_data, dict):
                continue
            true_prop = attr_data.get("true_proportion", 0)
            rr_rows += f"<tr><td colspan='4'><strong>{attr_name}</strong> (true proportion: {true_prop:.3f})</td></tr>\n"
            by_eps = attr_data.get("by_epsilon", {})
            for eps_str in sorted(by_eps.keys(), key=float):
                eps_info = by_eps[eps_str]
                if isinstance(eps_info, dict):
                    est = eps_info.get("estimated_proportion", 0)
                    err = eps_info.get("error", 0)
                    label = eps_info.get("note", "")
                    rr_rows += (
                        f"<tr><td>\u03b5={eps_str}</td>"
                        f"<td>{est:.3f}</td>"
                        f"<td>{err:.3f}</td>"
                        f"<td>{label}</td></tr>\n"
                    )
        if rr_rows:
            dp_section += f"""
  <h3>Randomized Response Analysis</h3>
  <table>
    <thead><tr><th>Epsilon</th><th>Estimated</th><th>Error</th><th>Privacy Level</th></tr></thead>
    <tbody>{rr_rows}</tbody>
  </table>
"""

    dp_section += f"""
  <figure>
    {_embed_image(f_dir / "dp_privacy_utility_tradeoff.png")}
    <figcaption>Figure 9: Privacy-utility tradeoff under differential privacy.</figcaption>
  </figure>"""

    # User recommendations
    recs = pets_summary.get("user_recommendations", [])
    recs_html = ""
    if recs:
        recs_html = "<h3>User Recommendations</h3><ol>\n"
        for r in recs:
            recs_html += f"  <li>{r}</li>\n"
        recs_html += "</ol>"

    parts.append(f"""
<section id="pets-evaluation">
  <h2>Privacy-Enhancing Technologies Evaluation</h2>

  <h3>Browser-Based PETs</h3>
  <figure>
    {_embed_image(f_dir / "pet_effectiveness_comparison.png")}
    <figcaption>Figure 7: Tracker reduction by privacy-enhancing technology.</figcaption>
  </figure>
  <figure>
    {_embed_image(f_dir / "pet_effectiveness_heatmap.png")}
    <figcaption>Figure 8: Average tracker cookies by PET and website category.</figcaption>
  </figure>
  {bp_table}

  <h3>Consent Management Platforms</h3>
  <figure>
    {_embed_image(f_dir / "cmp_comparison.png")}
    <figcaption>Figure 10: CMP effectiveness as privacy tools.</figcaption>
  </figure>
  {cmp_table}

  {combo_table}

  {dp_section}

  {recs_html}
</section>
""")

    # ── Methodology ───────────────────────────────────────────────────
    n_categories = scores_df["category"].nunique() if not scores_df.empty else "N/A"
    n_regions = scores_df["region"].nunique() if not scores_df.empty else "N/A"

    parts.append(f"""
<section id="methodology">
  <h2>Methodology</h2>
  <p>
    This analysis was conducted using an automated pipeline built in Python. Websites were
    crawled using Playwright in three consent states: no interaction, accept all, and reject all.
    Cookies and HTTP requests were captured in each state.
  </p>
  <p>
    <strong>Sites analyzed:</strong> {n_sites} &nbsp;|&nbsp;
    <strong>Categories:</strong> {n_categories} &nbsp;|&nbsp;
    <strong>Regions:</strong> {n_regions}
  </p>
  <h3>Pipeline Components</h3>
  <ol>
    <li><strong>Crawler</strong> — Playwright-based browser automation capturing cookies, HTTP requests, consent banners, and screenshots.</li>
    <li><strong>Classifier</strong> — Cookie/tracker classification using EasyList, EasyPrivacy, Disconnect lists, and a fallback heuristic.</li>
    <li><strong>Dark Pattern Detector</strong> — Detects 7 types of deceptive consent UI patterns.</li>
    <li><strong>Compliance Scorer</strong> — GDPR compliance scoring (0–100) based on 6 weighted criteria.</li>
    <li><strong>Metrics Engine</strong> — Aggregate statistics across all sites.</li>
    <li><strong>PET Evaluator</strong> — Tests 7 browser-level PET configurations.</li>
    <li><strong>DP Reporter</strong> — Applies differential privacy to aggregate metrics.</li>
    <li><strong>CMP Analyzer</strong> — Evaluates consent management platforms as privacy tools.</li>
    <li><strong>Visualizer</strong> — Generates 11 publication-quality figures (300 DPI).</li>
  </ol>
  <h3>Limitations</h3>
  <ul>
    <li>Consent banner interaction relies on keyword-based button detection; some non-standard banners may be missed.</li>
    <li>Analysis is based on a single crawl per site; dynamic content may vary across visits.</li>
    <li>Browser PET evaluation with extensions requires manual extension installation.</li>
    <li>Results may vary depending on geographic location and VPN configuration.</li>
  </ul>
</section>
""")

    parts.append("</div>")  # close .container

    # Footer
    parts.append("""
<footer>
  <p>CS475 Privacy-Enhancing Technologies — Course Project</p>
  <p>Team: Ahmed Hatem Haikal, Atakan Keser, Deniz Şahin, Şeyhmus Eren Özen, Moin Khan</p>
</footer>
""")

    # ── Assemble HTML ─────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GDPR Cookie Consent Compliance Analysis Report</title>
  <style>
{_CSS}
  </style>
</head>
<body>
{"".join(parts)}
</body>
</html>"""

    out.write_text(html, encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"Report generated: {out}  ({size_kb:.0f} KB)")
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AECCS HTML Report Generator")
    parser.add_argument("--processed-dir", type=str, default=None,
                        help="Processed data directory")
    parser.add_argument("--figures-dir", type=str, default=None,
                        help="Figures directory")
    parser.add_argument("--output", type=str, default=None,
                        help="Output HTML path")
    parser.add_argument("--open", action="store_true",
                        help="Open report in browser after generation")
    parser.add_argument(
        "--source-mode",
        default=DEFAULT_SOURCE_MODE,
        help="Dataset/output mode to use (default: real)",
    )
    args = parser.parse_args()

    path = generate_html_report(
        processed_dir=args.processed_dir,
        figures_dir=args.figures_dir,
        output_path=args.output,
        source_mode=args.source_mode,
    )

    if args.open:
        webbrowser.open(f"file://{path.resolve()}")


if __name__ == "__main__":
    main()
