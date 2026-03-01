"""
Visualization module.

Generates publication-quality figures from processed compliance data,
including:
- Violation rates by compliance criterion (bar chart)
- Tracker vendor market share (pie chart)
- Compliance score heatmap by domain and criterion
- PET effectiveness comparison (grouped bar chart)
- Differential privacy utility–privacy tradeoff (line chart)

All figures are saved to the ``reporting/figures/`` directory.
"""

from __future__ import annotations

from config import PROCESSED_DIR


def plot_violation_rates(metrics: dict, output_dir: str) -> None:
    """Generate a bar chart of violation rates by compliance criterion.

    Shows the percentage of sites violating each of the six compliance
    criteria (pre-consent trackers, missing reject, asymmetric effort,
    dark patterns, post-reject non-compliance, missing transparency).

    Args:
        metrics: Aggregate metrics dict from ``analysis.metrics``.
        output_dir: Directory to save the figure.
    """
    raise NotImplementedError("Implemented in Phase 5")


def plot_tracker_vendors(metrics: dict, output_dir: str) -> None:
    """Generate a pie chart of tracker vendor market share.

    Shows the distribution of tracker vendors (Google, Facebook, etc.)
    across all crawled sites.

    Args:
        metrics: Aggregate metrics dict.
        output_dir: Directory to save the figure.
    """
    raise NotImplementedError("Implemented in Phase 5")


def plot_compliance_heatmap(scores_path: str, output_dir: str) -> None:
    """Generate a heatmap of per-site compliance scores.

    Rows are websites (grouped by category), columns are the six
    compliance criteria. Cell colour indicates the criterion score.

    Args:
        scores_path: Path to the compliance scores CSV.
        output_dir: Directory to save the figure.
    """
    raise NotImplementedError("Implemented in Phase 5")


def plot_pet_effectiveness(pets_path: str, output_dir: str) -> None:
    """Generate a grouped bar chart comparing PET effectiveness.

    Shows tracker reduction percentage, cookie reduction percentage,
    and consent handling success rate for each PET configuration.

    Args:
        pets_path: Path to the PET evaluation results JSON.
        output_dir: Directory to save the figure.
    """
    raise NotImplementedError("Implemented in Phase 5")


def plot_dp_tradeoff(dp_metrics_path: str, output_dir: str) -> None:
    """Generate a line chart showing the privacy–utility tradeoff.

    Plots noisy metric values against epsilon, showing how accuracy
    degrades as privacy protection (lower epsilon) increases.

    Args:
        dp_metrics_path: Path to the DP report JSON.
        output_dir: Directory to save the figure.
    """
    raise NotImplementedError("Implemented in Phase 5")


def generate_all_visualizations(processed_dir: str, output_dir: str) -> None:
    """Generate all visualizations from processed data.

    Convenience function that calls all individual plot functions.

    Args:
        processed_dir: Directory containing all processed data files.
        output_dir: Directory to save all figures.
    """
    raise NotImplementedError("Implemented in Phase 5")
