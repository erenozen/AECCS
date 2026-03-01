"""
Consent Management Platform (CMP) analysis.

Evaluates CMPs (OneTrust, Cookiebot, Quantcast, TrustArc, Didomi,
Usercentrics) as privacy-enhancing technologies by comparing compliance
scores and dark pattern rates across sites grouped by CMP provider.

This analysis reveals:
- Which CMPs lead to higher GDPR compliance
- Which CMPs are associated with more dark patterns
- Whether CMP adoption correlates with fewer pre-consent trackers
- Market share of each CMP among the crawled sites
"""

from __future__ import annotations


def group_sites_by_cmp(processed_dir: str) -> dict:
    """Group crawled sites by their detected CMP provider.

    Reads CMP detection results from processed site data and returns
    a mapping from CMP name to list of domains using that CMP.

    Args:
        processed_dir: Directory containing processed site data with CMP info.

    Returns:
        A dict mapping CMP names (and "none" for sites without a CMP)
        to lists of domain strings.
    """
    raise NotImplementedError("Implemented in Phase 4")


def evaluate_cmp_effectiveness(
    cmp_groups: dict, scores_path: str
) -> dict:
    """Compute per-CMP compliance statistics.

    For each CMP group, calculates mean/median compliance scores,
    dark pattern rates, pre-consent tracker rates, and other metrics
    to evaluate the CMP's effectiveness as a PET.

    Args:
        cmp_groups: Output of ``group_sites_by_cmp``.
        scores_path: Path to the compliance scores CSV.

    Returns:
        A dict mapping each CMP to its aggregate effectiveness metrics.
    """
    raise NotImplementedError("Implemented in Phase 4")


def run_cmp_analysis(
    processed_dir: str, scores_path: str, output_path: str
) -> None:
    """Run the full CMP analysis pipeline.

    Groups sites by CMP, evaluates effectiveness, and writes results.

    Args:
        processed_dir: Directory containing processed site data.
        scores_path: Path to the compliance scores CSV.
        output_path: Path to write the CMP analysis results JSON.
    """
    raise NotImplementedError("Implemented in Phase 4")
