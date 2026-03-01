"""
Aggregate metrics computation.

Computes summary statistics across all crawled websites, including:
- Mean/median/std compliance scores by category and region
- Tracker prevalence rates (% of sites with trackers before consent)
- Most common tracker vendors and their market share
- CMP adoption rates
- Dark pattern prevalence by type
- Cookie counts (first-party vs. third-party, by purpose)
- Violation rates per compliance criterion
"""

from __future__ import annotations


def compute_aggregate_metrics(processed_dir: str) -> dict:
    """Compute aggregate statistics across all processed sites.

    Reads compliance scores, classified cookies, dark pattern results,
    and CMP detections from ``processed_dir`` and calculates overall
    summary metrics.

    Args:
        processed_dir: Directory containing all processed site data.

    Returns:
        A dict of aggregate metrics suitable for visualization and
        differential-privacy reporting.
    """
    raise NotImplementedError("Implemented in Phase 3")


def run_metrics(processed_dir: str, output_path: str) -> None:
    """Compute and save aggregate metrics to a JSON file.

    Args:
        processed_dir: Directory containing all processed site data.
        output_path: Path to write the aggregate metrics JSON.
    """
    raise NotImplementedError("Implemented in Phase 3")
