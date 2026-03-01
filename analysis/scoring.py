"""
GDPR compliance scoring.

Computes a 0–100 compliance score for each website based on six weighted
criteria defined in ``config.COMPLIANCE_WEIGHTS``:

1. no_pre_consent_trackers (0.25) — No tracking cookies/requests before
   the user interacts with the consent banner.
2. reject_option_available (0.20) — A visible "Reject All" button exists
   in the consent banner.
3. equal_accept_reject_effort (0.15) — Accept and reject buttons require
   equal effort (same number of clicks, same visibility).
4. no_dark_patterns (0.15) — No deceptive UI patterns detected in the
   consent banner.
5. post_reject_compliance (0.15) — After clicking "Reject All", tracking
   cookies and requests are actually stopped.
6. transparent_information (0.10) — The banner provides clear information
   about cookie purposes and data processing.
"""

from __future__ import annotations

from config import COMPLIANCE_WEIGHTS


def compute_compliance_score(
    site_data: dict, dark_pattern_data: dict, classified_cookies: list[dict]
) -> dict:
    """Compute the GDPR compliance score for a single website.

    Evaluates each of the six criteria, applies the configured weights,
    and produces a total score between 0 and 100.

    Args:
        site_data: Merged crawl data for the site (all three interaction modes).
        dark_pattern_data: Dark pattern detection results for the site's banner.
        classified_cookies: List of classified cookies for the site.

    Returns:
        A dict with per-criterion scores (0.0–1.0), the weighted total (0–100),
        and a human-readable compliance level (e.g., "Good", "Poor").
    """
    raise NotImplementedError("Implemented in Phase 3")


def run_scoring(processed_dir: str, output_path: str) -> None:
    """Batch-score all websites and write results to a CSV file.

    Reads classified cookies and dark pattern results from ``processed_dir``,
    computes compliance scores, and writes ``compliance_scores.csv``.

    Args:
        processed_dir: Directory containing processed/classified site data.
        output_path: Path to write the compliance scores CSV.
    """
    raise NotImplementedError("Implemented in Phase 3")
