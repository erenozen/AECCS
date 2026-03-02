"""
Visualization suite for GDPR cookie-consent compliance analysis.

Generates 11 publication-quality figures (300 DPI) for the final report:
 1. Pre-consent violation rates by category
 2. Tracker vendor market share (donut)
 3. Cookie count comparison before/after consent
 4. Compliance score distribution (histogram + KDE)
 5. Compliance heatmap (category × region or CMP)
 6. Dark pattern prevalence
 7. PET effectiveness comparison
 8. PET effectiveness heatmap
 9. DP privacy-utility tradeoff
10. CMP comparison
11. Summary dashboard (2×2)

All figures are saved to ``reporting/{source_mode}/figures/``.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

from config import DEFAULT_SOURCE_MODE, FIGURES_DIR, PROCESSED_DIR, get_dataset_layout

# ── Style ─────────────────────────────────────────────────────────────────────

STYLE_CONFIG = {
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.figsize": (7, 4),
}
plt.rcParams.update(STYLE_CONFIG)

COLORS = {
    "primary": "#2563EB",
    "secondary": "#7C3AED",
    "success": "#059669",
    "danger": "#DC2626",
    "warning": "#D97706",
    "neutral": "#6B7280",
    "categories": sns.color_palette("Set2", 8),
    "pets": sns.color_palette("tab10", 7),
    "sequential": "YlOrRd",
    "diverging": "RdYlGn",
}

FIGURE_DIR = FIGURES_DIR

PET_LABELS = {
    "baseline": "Baseline",
    "ublock_origin": "uBlock Origin",
    "privacy_badger": "Privacy Badger",
    "firefox_etp_standard": "Firefox ETP Std",
    "firefox_etp_strict": "Firefox ETP Strict",
    "brave_shields": "Brave Shields",
    "consent_o_matic": "Consent-O-Matic",
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _ensure_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)


def _save(fig: plt.Figure, path: Path, fmt: str = "png") -> Path:
    _ensure_dir(path.parent)
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white", format=fmt)
    plt.close(fig)
    return path


def _snake_to_title(s: str) -> str:
    return s.replace("_", " ").title()


# ── Figure 1: Pre-Consent Violation Rates by Category ────────────────────────


def plot_violation_rates_by_category(
    metrics: dict, output_dir: Path | None = None, fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"violation_rates_by_category.{fmt}"
    by_cat = metrics.get("pre_consent_violations", {}).get("by_category", {})
    if not by_cat:
        return _empty_figure(out, "No pre-consent violation data", fmt)

    cats = sorted(by_cat.keys(), key=lambda c: by_cat[c].get("percentage", 0))
    pcts = [by_cat[c].get("percentage", 0) for c in cats]

    cmap = matplotlib.colormaps.get_cmap("RdYlGn_r")
    norm = plt.Normalize(0, 100)
    bar_colors = [cmap(norm(p)) for p in pcts]

    fig, ax = plt.subplots(figsize=(7, max(3, len(cats) * 0.45)))
    bars = ax.barh(cats, pcts, color=bar_colors, edgecolor="white", linewidth=0.5)

    for bar, pct in zip(bars, pcts):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%", va="center", fontsize=8)

    overall = metrics["pre_consent_violations"].get("percentage", 0)
    ax.axvline(overall, color=COLORS["neutral"], linestyle="--", linewidth=1)
    ax.text(overall + 1, len(cats) - 0.5, f"Avg {overall:.1f}%",
            fontsize=7, color=COLORS["neutral"])

    ax.set_xlabel("Sites with Pre-Consent Trackers (%)")
    ax.set_title("Pre-Consent Tracker Violations by Website Category")
    ax.set_xlim(0, max(pcts) * 1.15 if pcts else 100)
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 2: Tracker Vendor Market Share ─────────────────────────────────────


def plot_tracker_vendor_share(
    metrics: dict, output_dir: Path | None = None, fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"tracker_vendor_share.{fmt}"
    vendors_raw = metrics.get("tracker_analysis", {}).get("top_tracker_vendors", [])
    if not vendors_raw:
        return _empty_figure(out, "No tracker vendor data", fmt)

    # vendors_raw is a list of dicts
    top8 = vendors_raw[:8]
    labels = [v["vendor"] for v in top8]
    sizes = [v["sites_present"] for v in top8]

    others = sum(v["sites_present"] for v in vendors_raw[8:])
    if others > 0:
        labels.append("Others")
        sizes.append(others)

    total_tracker_domains = metrics["tracker_analysis"].get("total_unique_tracker_domains", "?")

    fig, ax = plt.subplots(figsize=(7, 5))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.1f%%",
        startangle=140, pctdistance=0.78,
        colors=COLORS["categories"][:len(sizes)],
        wedgeprops=dict(width=0.45, edgecolor="white"),
    )
    for t in autotexts:
        t.set_fontsize(7)
    for t in texts:
        t.set_fontsize(8)

    ax.text(0, 0, f"{total_tracker_domains}\ntrackers", ha="center", va="center",
            fontsize=11, fontweight="bold")
    ax.set_title("Tracker Vendor Prevalence Across Analyzed Websites")
    return _save(fig, out, fmt)


# ── Figure 3: Cookie Count Comparison (Before/After Consent) ─────────────────


def plot_cookie_comparison(
    metrics: dict,
    scores_path: str | None = None,
    raw_dir: str | None = None,
    output_dir: Path | None = None,
    fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"cookie_comparison_by_category.{fmt}"
    bva = metrics.get("tracker_analysis", {}).get("before_vs_after_consent", {})

    # Try per-category breakdown from compliance_scores by_category
    by_cat = metrics.get("pre_consent_violations", {}).get("by_category", {})
    cats = sorted(by_cat.keys())

    if not cats:
        return _empty_figure(out, "No category data", fmt)

    # Load individual site data for per-category breakdown
    sp = Path(scores_path) if scores_path else PROCESSED_DIR / "compliance_scores.csv"
    if sp.exists():
        df = pd.read_csv(sp)
    else:
        df = pd.DataFrame()

    # We'll compute from raw json files per site
    no_int: dict[str, list[float]] = {c: [] for c in cats}
    after_acc: dict[str, list[float]] = {c: [] for c in cats}
    after_rej: dict[str, list[float]] = {c: [] for c in cats}

    src_raw_dir = Path(raw_dir) if raw_dir else get_dataset_layout().raw_dir
    for f in sorted(src_raw_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data.get("success"):
            continue
        domain = data.get("domain", f.stem)
        # Get category from scores df
        if not df.empty:
            row = df[df["domain"] == domain]
            if not row.empty:
                cat = row.iloc[0].get("category")
                if pd.isna(cat) or cat not in no_int:
                    continue
            else:
                continue
        else:
            continue

        pre = data.get("pre_consent", {})
        post_a = data.get("post_consent_accept", {})
        post_r = data.get("post_consent_reject", {})
        no_int[cat].append(len(pre.get("third_party_domains", [])))
        after_acc[cat].append(len(post_a.get("third_party_domains", [])) if post_a else len(pre.get("third_party_domains", [])))
        after_rej[cat].append(len(post_r.get("third_party_domains", [])) if post_r else len(pre.get("third_party_domains", [])))

    display_cats = [c for c in cats if no_int[c]]
    if not display_cats:
        # Fallback: single overall bar
        display_cats = ["Overall"]
        no_int = {"Overall": [bva.get("avg_trackers_no_interaction", 0)]}
        after_acc = {"Overall": [bva.get("avg_trackers_after_accept", 0)]}
        after_rej = {"Overall": [bva.get("avg_trackers_after_reject", 0)]}

    x = np.arange(len(display_cats))
    width = 0.25

    means_ni = [np.mean(no_int[c]) if no_int[c] else 0 for c in display_cats]
    means_aa = [np.mean(after_acc[c]) if after_acc[c] else 0 for c in display_cats]
    means_ar = [np.mean(after_rej[c]) if after_rej[c] else 0 for c in display_cats]

    fig, ax = plt.subplots(figsize=(max(7, len(display_cats) * 1.2), 4.5))
    b1 = ax.bar(x - width, means_ni, width, label="No Interaction", color=COLORS["warning"])
    b2 = ax.bar(x, means_aa, width, label="After Accept", color=COLORS["danger"])
    b3 = ax.bar(x + width, means_ar, width, label="After Reject", color=COLORS["success"])

    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.2,
                        f"{h:.1f}", ha="center", va="bottom", fontsize=7)

    ax.set_xticks(x)
    ax.set_xticklabels(display_cats, rotation=30, ha="right")
    ax.set_ylabel("Average Number of Trackers")
    ax.set_title("Average Tracker Count by Consent State and Category")
    ax.legend(loc="upper right")
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 4: Compliance Score Distribution ───────────────────────────────────


def plot_compliance_distribution(
    scores_path: str | None = None, output_dir: Path | None = None, fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"compliance_score_distribution.{fmt}"
    sp = Path(scores_path) if scores_path else PROCESSED_DIR / "compliance_scores.csv"
    if not sp.exists():
        return _empty_figure(out, "compliance_scores.csv not found", fmt)

    df = pd.read_csv(sp)
    scores = df["overall_score"].dropna()

    fig, ax = plt.subplots(figsize=(7, 4))

    # Grade background shading
    grade_bands = [
        (90, 100, COLORS["success"], "A"),
        (75, 89.99, "#34D399", "B"),
        (60, 74.99, COLORS["warning"], "C"),
        (40, 59.99, "#F59E0B", "D"),
        (0, 39.99, COLORS["danger"], "F"),
    ]
    for lo, hi, color, label in grade_bands:
        ax.axvspan(lo, hi, alpha=0.12, color=color)
        ax.text((lo + hi) / 2, ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1,
                label, ha="center", va="bottom", fontsize=9, fontweight="bold",
                color=color, alpha=0.7)

    ax.hist(scores, bins=20, range=(0, 100), color=COLORS["primary"],
            edgecolor="white", alpha=0.75, label="Sites")

    # KDE
    try:
        from scipy.stats import gaussian_kde
        kde_x = np.linspace(0, 100, 200)
        kde = gaussian_kde(scores, bw_method=0.3)
        ax2 = ax.twinx()
        ax2.plot(kde_x, kde(kde_x), color="#1E3A8A", linewidth=1.5, label="Density (KDE)")
        ax2.set_ylabel("")
        ax2.set_yticks([])
    except Exception:
        pass

    mean_s = scores.mean()
    med_s = scores.median()
    ax.axvline(mean_s, color=COLORS["primary"], linestyle="-", linewidth=1.2)
    ax.axvline(med_s, color=COLORS["primary"], linestyle="--", linewidth=1.2)
    ymax = ax.get_ylim()[1]
    ax.text(mean_s + 1, ymax * 0.92, f"Mean {mean_s:.1f}", fontsize=7, color=COLORS["primary"])
    ax.text(med_s + 1, ymax * 0.82, f"Median {med_s:.1f}", fontsize=7, color=COLORS["primary"])

    # Re-draw grade labels at proper y
    for lo, hi, color, label in grade_bands:
        ax.text((lo + hi) / 2, ymax * 0.97, label, ha="center", va="top",
                fontsize=9, fontweight="bold", color=color, alpha=0.8)

    ax.set_xlabel("Compliance Score (0–100)")
    ax.set_ylabel("Number of Websites")
    ax.set_title("Distribution of GDPR Compliance Scores")
    ax.set_xlim(0, 100)
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 5: Compliance Score Heatmap ────────────────────────────────────────


def plot_compliance_heatmap(
    scores_path: str | None = None, output_dir: Path | None = None, fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"compliance_heatmap.{fmt}"
    sp = Path(scores_path) if scores_path else PROCESSED_DIR / "compliance_scores.csv"
    if not sp.exists():
        return _empty_figure(out, "compliance_scores.csv not found", fmt)

    df = pd.read_csv(sp)
    df["category"] = df["category"].fillna("Unknown")
    df["region"] = df["region"].fillna("Unknown")

    # Decide: category × region  or  category × cmp_detected
    n_regions = df["region"].nunique()
    if n_regions >= 3:
        pivot = df.pivot_table(values="overall_score", index="category",
                               columns="region", aggfunc="mean")
        xlabel, ylabel = "Region", "Category"
    else:
        df["cmp_detected"] = df["cmp_detected"].fillna("None")
        pivot = df.pivot_table(values="overall_score", index="category",
                               columns="cmp_detected", aggfunc="mean")
        xlabel, ylabel = "CMP", "Category"

    fig, ax = plt.subplots(figsize=(max(7, pivot.shape[1] * 1.1), max(4, pivot.shape[0] * 0.6)))
    sns.heatmap(pivot, annot=True, fmt=".1f", cmap=COLORS["diverging"],
                vmin=0, vmax=100, linewidths=0.5, ax=ax, cbar_kws={"label": "Score"})
    ax.set_title("Average Compliance Score by Category and " + xlabel)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 6: Dark Pattern Prevalence ─────────────────────────────────────────


def plot_dark_pattern_prevalence(
    metrics: dict, output_dir: Path | None = None, fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"dark_pattern_prevalence.{fmt}"
    by_type_raw = metrics.get("dark_patterns", {}).get("by_type", {})
    if not by_type_raw:
        return _empty_figure(out, "No dark pattern data", fmt)

    # by_type is {pattern_name: {count: N, percentage: P}}
    items = []
    for name, val in by_type_raw.items():
        if isinstance(val, dict):
            items.append((name, val.get("percentage", 0), val.get("count", 0)))
        else:
            items.append((name, float(val), 0))

    items.sort(key=lambda x: x[1])
    names = [_snake_to_title(i[0]) for i in items]
    pcts = [i[1] for i in items]
    counts = [i[2] for i in items]

    max_pct = max(pcts) if pcts else 1
    alphas = [0.4 + 0.6 * (p / max_pct) for p in pcts]
    bar_colors = [(0.86, 0.15, 0.15, a) for a in alphas]

    fig, ax = plt.subplots(figsize=(7, max(3, len(names) * 0.45)))
    bars = ax.barh(names, pcts, color=bar_colors, edgecolor="white", linewidth=0.5)

    for bar, pct, cnt in zip(bars, pcts, counts):
        label = f"{pct:.1f}%"
        if cnt:
            label += f" ({cnt} sites)"
        ax.text(bar.get_width() + 0.8, bar.get_y() + bar.get_height() / 2,
                label, va="center", fontsize=7)

    ax.set_xlabel("Percentage of Sites (%)")
    ax.set_title("Prevalence of Dark Patterns in Cookie Consent Banners")
    ax.set_xlim(0, max(pcts) * 1.2 if pcts else 100)
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 7: PET Effectiveness Comparison ────────────────────────────────────


def plot_pet_effectiveness(
    pets_path: str | None = None, output_dir: Path | None = None, fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"pet_effectiveness_comparison.{fmt}"
    pp = Path(pets_path) if pets_path else PROCESSED_DIR / "pets_effectiveness.csv"
    if not pp.exists():
        return _empty_figure(out, "pets_effectiveness.csv not found", fmt)

    df = pd.read_csv(pp)
    pets = [p for p in df["pet_name"].unique() if p != "baseline"]

    # Baseline averages
    bl = df[df["pet_name"] == "baseline"]
    bl_requests = bl["total_requests"].mean()
    bl_domains = bl["tracker_domains"].mean()
    if bl_requests == 0:
        bl_requests = 1
    if bl_domains == 0:
        bl_domains = 1

    stats: list[dict] = []
    for pet in pets:
        sub = df[df["pet_name"] == pet]
        mr = sub["total_requests"].mean()
        md = sub["tracker_domains"].mean()
        sr = sub["total_requests"].std()
        sd = sub["tracker_domains"].std()
        pct_r = mr / bl_requests * 100
        pct_d = md / bl_domains * 100
        stats.append({
            "pet": pet, "label": PET_LABELS.get(pet, pet),
            "pct_requests": pct_r, "pct_domains": pct_d,
            "std_requests": sr / bl_requests * 100 if bl_requests else 0,
            "std_domains": sd / bl_domains * 100 if bl_domains else 0,
        })

    stats.sort(key=lambda x: x["pct_requests"])
    x = np.arange(len(stats))
    width = 0.35

    fig, ax = plt.subplots(figsize=(max(7, len(stats) * 1.5), 4.5))
    b1 = ax.bar(x - width / 2, [s["pct_requests"] for s in stats], width,
                yerr=[s["std_requests"] for s in stats], capsize=3,
                label="Total Requests", color=COLORS["primary"], alpha=0.85)
    b2 = ax.bar(x + width / 2, [s["pct_domains"] for s in stats], width,
                yerr=[s["std_domains"] for s in stats], capsize=3,
                label="Tracker Domains", color=COLORS["secondary"], alpha=0.85)

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            red = 100 - h
            ax.text(bar.get_x() + bar.get_width() / 2, h + 3,
                    f"−{red:.0f}%", ha="center", va="bottom", fontsize=6.5)

    ax.axhline(100, color=COLORS["neutral"], linestyle="--", linewidth=0.8, label="Baseline (100%)")
    ax.set_xticks(x)
    ax.set_xticklabels([s["label"] for s in stats], rotation=25, ha="right")
    ax.set_ylabel("Remaining (% of Baseline)")
    ax.set_title("Request and Tracker Domain Reduction by PET")
    ax.legend(loc="upper right", fontsize=7)
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 8: PET Effectiveness Heatmap ──────────────────────────────────────


def plot_pet_heatmap(
    pets_path: str | None = None,
    scores_path: str | None = None,
    output_dir: Path | None = None,
    fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"pet_effectiveness_heatmap.{fmt}"
    pp = Path(pets_path) if pets_path else PROCESSED_DIR / "pets_effectiveness.csv"
    if not pp.exists():
        return _empty_figure(out, "pets_effectiveness.csv not found", fmt)

    df = pd.read_csv(pp)

    # New PET CSVs already carry category; fall back to scores.csv only if needed.
    has_category = "category" in df.columns and df["category"].notna().any()
    sp = Path(scores_path) if scores_path else PROCESSED_DIR / "compliance_scores.csv"
    if not has_category and sp.exists():
        cs = pd.read_csv(sp)[["domain", "category"]].drop_duplicates()
        df = df.merge(cs, on="domain", how="left")
    elif "category" not in df.columns:
        df["category"] = "All"

    df["category"] = df["category"].fillna("Unknown")
    df["pet_label"] = df["pet_name"].map(PET_LABELS).fillna(df["pet_name"])

    pivot = df.pivot_table(values="tracker_domains", index="pet_label",
                           columns="category", aggfunc="mean")

    fig, ax = plt.subplots(figsize=(max(7, pivot.shape[1] * 1.0), max(4, pivot.shape[0] * 0.55)))
    sns.heatmap(pivot, annot=True, fmt=".1f", cmap="YlOrRd_r",
                linewidths=0.5, ax=ax, cbar_kws={"label": "Avg Tracker Domains"})
    ax.set_title("Average Tracker Domains by PET and Website Category")
    ax.set_xlabel("Website Category")
    ax.set_ylabel("PET")
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 9: DP Privacy-Utility Tradeoff ────────────────────────────────────


def plot_dp_tradeoff(
    dp_path: str | None = None, output_dir: Path | None = None, fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"dp_privacy_utility_tradeoff.{fmt}"
    dp_file = Path(dp_path) if dp_path else PROCESSED_DIR / "dp_aggregate_metrics.json"
    if not dp_file.exists():
        return _empty_figure(out, "dp_aggregate_metrics.json not found", fmt)

    dp = json.loads(dp_file.read_text(encoding="utf-8"))
    pt = dp.get("privacy_utility_tradeoff", {})
    meta = dp.get("metadata", {})
    rec_eps = meta.get("recommended_epsilon")

    # Pick 3-4 representative metrics
    target_metrics = [
        "pre_consent_tracker_percentage",
        "avg_compliance_score",
        "sites_with_reject_button_percentage",
        "sites_with_dark_patterns_percentage",
    ]
    available = [m for m in target_metrics if m in pt]

    if not available:
        return _empty_figure(out, "No DP tradeoff data", fmt)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    colors_cycle = [COLORS["primary"], COLORS["danger"], COLORS["success"], COLORS["secondary"]]

    for idx, metric_name in enumerate(available):
        metric_data = pt[metric_name]
        by_eps = metric_data.get("by_epsilon", {})
        if not by_eps:
            continue

        eps_vals: list[float] = []
        maes: list[float] = []
        ci_lows: list[float] = []
        ci_highs: list[float] = []

        for eps_str, vals in sorted(by_eps.items(), key=lambda x: float(x[0])):
            eps_vals.append(float(eps_str))
            maes.append(vals.get("mae", 0))
            ci = vals.get("ci_95", [0, 0])
            true_val = metric_data.get("true_value", 0)
            # Approximate CI width as error band around MAE
            std = vals.get("std", 0)
            ci_lows.append(max(0, vals.get("mae", 0) - std * 0.3))
            ci_highs.append(vals.get("mae", 0) + std * 0.3)

        color = colors_cycle[idx % len(colors_cycle)]
        label = _snake_to_title(metric_name).replace(" Percentage", " %")
        ax.plot(eps_vals, maes, marker="o", markersize=4, label=label,
                color=color, linewidth=1.5)
        ax.fill_between(eps_vals, ci_lows, ci_highs, alpha=0.15, color=color)

        # Mark where MAE < 5
        for e, m in zip(eps_vals, maes):
            if m < 5:
                ax.annotate("", xy=(e, m), xytext=(e, m + 2),
                            arrowprops=dict(arrowstyle="->", color=color, lw=0.8))
                break

    if rec_eps is not None:
        ax.axvline(rec_eps, color=COLORS["neutral"], linestyle="--", linewidth=1)
        ax.text(rec_eps * 1.1, ax.get_ylim()[1] * 0.9,
                f"Recommended ε={rec_eps}", fontsize=7, color=COLORS["neutral"])

    ax.set_xscale("log")
    ax.set_xlabel("Privacy Budget (ε)")
    ax.set_ylabel("Mean Absolute Error")
    ax.set_title("Privacy-Utility Tradeoff Under Differential Privacy")
    ax.legend(loc="upper right", fontsize=7)
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter())
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 10: CMP Comparison ────────────────────────────────────────────────


def plot_cmp_comparison(
    cmp_path: str | None = None, output_dir: Path | None = None, fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"cmp_comparison.{fmt}"
    cp = Path(cmp_path) if cmp_path else PROCESSED_DIR / "cmp_comparison.csv"
    if not cp.exists():
        return _empty_figure(out, "cmp_comparison.csv not found", fmt)

    df = pd.read_csv(cp)
    # Filter CMPs with enough data (at least 1 site — relax if few CMPs)
    min_sites = 3 if len(df) > 5 else 1
    df = df[df["site_count"] >= min_sites].sort_values("pet_score", ascending=True)

    if df.empty:
        return _empty_figure(out, "No CMPs with enough data", fmt)

    cmp_names = df["cmp_name"].tolist()
    metrics_to_plot = [
        ("avg_compliance_score", "Avg Compliance Score"),
        ("pct_reject_works", "Reject Works %"),
        ("pct_with_reject_button", "Reject Available %"),
    ]
    # Compute inverse DP %
    df["inv_dark_pattern_pct"] = 100 - df["pct_with_dark_patterns"]
    metrics_to_plot.append(("inv_dark_pattern_pct", "No Dark Patterns %"))

    y = np.arange(len(cmp_names))
    height = 0.18
    metric_colors = [COLORS["primary"], COLORS["success"], COLORS["warning"], COLORS["secondary"]]

    fig, ax = plt.subplots(figsize=(8, max(3, len(cmp_names) * 0.7)))

    for i, (col, label) in enumerate(metrics_to_plot):
        vals = df[col].tolist()
        bars = ax.barh(y + i * height, vals, height, label=label,
                       color=metric_colors[i], alpha=0.85)
        for bar, val in zip(bars, vals):
            if val > 0:
                ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                        f"{val:.0f}", va="center", fontsize=6)

    ax.set_yticks(y + height * 1.5)
    ax.set_yticklabels(cmp_names)
    ax.set_xlabel("Score / Percentage")
    ax.set_title("Consent Management Platform Effectiveness as Privacy Tools")
    ax.legend(loc="lower right", fontsize=7)
    ax.set_xlim(0, 115)
    fig.tight_layout()
    return _save(fig, out, fmt)


# ── Figure 11: Summary Dashboard ─────────────────────────────────────────────


def plot_summary_dashboard(
    metrics: dict,
    scores_path: str | None = None,
    output_dir: Path | None = None,
    fmt: str = "png",
) -> Path:
    out = (output_dir or FIGURE_DIR) / f"summary_dashboard.{fmt}"
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    fig.suptitle("GDPR Cookie Consent Compliance: Key Findings", fontsize=14, fontweight="bold")

    # ── Subplot 1: Grade distribution pie ─────────────────────────────
    ax1 = axes[0, 0]
    gd = metrics.get("compliance_scores", {}).get("grade_distribution", {})
    if gd:
        labels = list(gd.keys())
        # Values may be int or dict with "count" key
        sizes = []
        for v in gd.values():
            sizes.append(v["count"] if isinstance(v, dict) else int(v))
        grade_colors = {"A": "#059669", "B": "#34D399", "C": "#D97706", "D": "#F59E0B", "F": "#DC2626"}
        colors = [grade_colors.get(g, "#6B7280") for g in labels]
        non_zero = [(l, s, c) for l, s, c in zip(labels, sizes, colors) if s > 0]
        if non_zero:
            ax1.pie([x[1] for x in non_zero],
                    labels=[f"{x[0]} ({x[1]})" for x in non_zero],
                    colors=[x[2] for x in non_zero],
                    autopct="%1.0f%%", startangle=90, textprops={"fontsize": 8})
    ax1.set_title("Compliance Grade Distribution", fontsize=10)

    # ── Subplot 2: Pre-consent violation donut ────────────────────────
    ax2 = axes[0, 1]
    pv = metrics.get("pre_consent_violations", {})
    pct_violating = pv.get("percentage", 0)
    pct_ok = 100 - pct_violating
    ax2.pie([pct_violating, pct_ok],
            colors=[COLORS["danger"], COLORS["success"]],
            startangle=90, wedgeprops=dict(width=0.4))
    ax2.text(0, 0, f"{pct_violating:.0f}%", ha="center", va="center",
             fontsize=20, fontweight="bold", color=COLORS["danger"])
    ax2.set_title("Sites with Pre-Consent Trackers", fontsize=10)

    # ── Subplot 3: Top 5 dark patterns ────────────────────────────────
    ax3 = axes[1, 0]
    dp_raw = metrics.get("dark_patterns", {}).get("by_type", {})
    if dp_raw:
        dp_items = []
        for name, val in dp_raw.items():
            if isinstance(val, dict):
                pct = val.get("percentage", 0)
            else:
                pct = float(val)
            dp_items.append((_snake_to_title(name), pct))
        dp_items.sort(key=lambda x: x[1], reverse=True)
        top5 = dp_items[:5]
        top5.reverse()
        ax3.barh([t[0] for t in top5], [t[1] for t in top5],
                 color=COLORS["danger"], alpha=0.7)
        for i, (n, p) in enumerate(top5):
            ax3.text(p + 0.5, i, f"{p:.0f}%", va="center", fontsize=7)
    ax3.set_title("Top 5 Dark Patterns", fontsize=10)
    ax3.set_xlabel("% of Sites", fontsize=8)

    # ── Subplot 4: Consent state bars ─────────────────────────────────
    ax4 = axes[1, 1]
    bva = metrics.get("tracker_analysis", {}).get("before_vs_after_consent", {})
    if bva:
        states = ["No Interaction", "After Accept", "After Reject"]
        vals = [
            bva.get("avg_trackers_no_interaction", 0),
            bva.get("avg_trackers_after_accept", 0),
            bva.get("avg_trackers_after_reject", 0),
        ]
        bar_cols = [COLORS["warning"], COLORS["danger"], COLORS["success"]]
        bars = ax4.bar(states, vals, color=bar_cols, width=0.5)
        for bar, v in zip(bars, vals):
            ax4.text(bar.get_x() + bar.get_width() / 2, v + 0.2,
                     f"{v:.1f}", ha="center", fontsize=8)
    ax4.set_title("Avg Trackers by Consent State", fontsize=10)
    ax4.set_ylabel("Trackers", fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return _save(fig, out, fmt)


# ── Empty figure placeholder ──────────────────────────────────────────────────


def _empty_figure(path: Path, message: str, fmt: str = "png") -> Path:
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12, color="gray")
    ax.set_axis_off()
    return _save(fig, path, fmt)


# ── Master generator ─────────────────────────────────────────────────────────


FIGURE_REGISTRY: dict[str, dict] = {
    "violation_rates": {
        "func": "plot_violation_rates_by_category",
        "needs": ["metrics"],
        "desc": "Pre-consent violation rates by category",
    },
    "tracker_vendors": {
        "func": "plot_tracker_vendor_share",
        "needs": ["metrics"],
        "desc": "Tracker vendor market share (donut)",
    },
    "cookie_comparison": {
        "func": "plot_cookie_comparison",
        "needs": ["metrics", "scores_path"],
        "desc": "Cookie count comparison before/after consent",
    },
    "compliance_distribution": {
        "func": "plot_compliance_distribution",
        "needs": ["scores_path"],
        "desc": "Compliance score distribution (histogram + KDE)",
    },
    "compliance_heatmap": {
        "func": "plot_compliance_heatmap",
        "needs": ["scores_path"],
        "desc": "Compliance heatmap (category × region/CMP)",
    },
    "dark_patterns": {
        "func": "plot_dark_pattern_prevalence",
        "needs": ["metrics"],
        "desc": "Dark pattern prevalence",
    },
    "pet_effectiveness": {
        "func": "plot_pet_effectiveness",
        "needs": ["pets_path"],
        "desc": "PET effectiveness comparison",
    },
    "pet_heatmap": {
        "func": "plot_pet_heatmap",
        "needs": ["pets_path"],
        "desc": "PET effectiveness heatmap",
    },
    "dp_tradeoff": {
        "func": "plot_dp_tradeoff",
        "needs": ["dp_path"],
        "desc": "DP privacy-utility tradeoff",
    },
    "cmp_comparison": {
        "func": "plot_cmp_comparison",
        "needs": ["cmp_path"],
        "desc": "CMP comparison",
    },
    "summary_dashboard": {
        "func": "plot_summary_dashboard",
        "needs": ["metrics", "scores_path"],
        "desc": "Summary dashboard (2×2)",
    },
}


def generate_all_visualizations(
    processed_dir: str | None = None,
    output_dir: str | None = None,
    figures: list[str] | None = None,
    fmt: str = "png",
    source_mode: str = DEFAULT_SOURCE_MODE,
) -> list[Path]:
    layout = get_dataset_layout(source_mode)
    p_dir = Path(processed_dir) if processed_dir else layout.processed_dir
    o_dir = Path(output_dir) if output_dir else layout.figures_dir
    _ensure_dir(o_dir)

    # Load data files (once)
    metrics: dict | None = None
    metrics_path = p_dir / "aggregate_metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    scores_path = str(p_dir / "compliance_scores.csv")
    pets_path = str(p_dir / "pets_effectiveness.csv")
    dp_path = str(p_dir / "dp_aggregate_metrics.json")
    cmp_path = str(p_dir / "cmp_comparison.csv")
    raw_dir = str(layout.raw_dir)

    targets = figures if figures else list(FIGURE_REGISTRY.keys())
    generated: list[Path] = []

    for name in targets:
        reg = FIGURE_REGISTRY.get(name)
        if not reg:
            print(f"  [SKIP] Unknown figure: {name}")
            continue

        fn = globals()[reg["func"]]
        needs = reg["needs"]

        try:
            kwargs: dict = {"output_dir": o_dir, "fmt": fmt}
            if "metrics" in needs:
                if metrics is None:
                    print(f"  [SKIP] {name} — aggregate_metrics.json not found")
                    continue
                kwargs["metrics"] = metrics
            if "scores_path" in needs:
                kwargs["scores_path"] = scores_path
            if name == "cookie_comparison":
                kwargs["raw_dir"] = raw_dir
            if "pets_path" in needs:
                kwargs["pets_path"] = pets_path
                if name == "pet_heatmap":
                    kwargs["scores_path"] = scores_path
            if "dp_path" in needs:
                kwargs["dp_path"] = dp_path
            if "cmp_path" in needs:
                kwargs["cmp_path"] = cmp_path

            path = fn(**kwargs)
            generated.append(path)
            print(f"  [OK] {name} → {path}")
        except Exception as exc:
            print(f"  [ERROR] {name}: {exc}")

    # Summary
    total_kb = sum(p.stat().st_size for p in generated if p.exists()) / 1024
    print(f"\nGenerated {len(generated)}/{len(targets)} figures ({total_kb:.0f} KB total)")
    for p in generated:
        print(f"  {p.name}")
    return generated


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AECCS Visualization Suite")
    parser.add_argument("--processed-dir", type=str, default=None,
                        help="Processed data directory")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Figure output directory")
    parser.add_argument("--figures", nargs="*", default=None,
                        help="Specific figures to generate (by short name)")
    parser.add_argument("--list", action="store_true",
                        help="List available figures and exit")
    parser.add_argument("--format", type=str, default="png",
                        choices=["png", "pdf", "svg"],
                        help="Output format (default: png)")
    parser.add_argument(
        "--source-mode",
        choices=["real", "mock"],
        default=DEFAULT_SOURCE_MODE,
        help="Dataset/output mode to use (default: real)",
    )
    args = parser.parse_args()

    if args.list:
        print("Available figures:")
        for name, info in FIGURE_REGISTRY.items():
            print(f"  {name:<25s}  {info['desc']}")
        return

    warnings.filterwarnings("ignore", category=UserWarning)
    print("Generating visualizations …\n")
    generate_all_visualizations(
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        figures=args.figures,
        fmt=args.format,
        source_mode=args.source_mode,
    )


if __name__ == "__main__":
    main()
