"""
Browser-based PET evaluation.

Re-runs the crawling pipeline under different browser PET configurations
to measure their effectiveness at blocking trackers and enforcing consent
preferences. Configurations are defined in ``config.PET_CONFIGURATIONS``.

Tested PETs include:
- uBlock Origin (extension-based tracker blocker)
- Privacy Badger (EFF heuristic tracker blocker)
- Firefox Enhanced Tracking Protection (Standard and Strict modes)
- Brave Shields (simulated via filter lists)
- Consent-O-Matic (auto-reject consent extension)

For each PET, the module records:
- Number of trackers blocked vs. baseline
- Cookies blocked vs. baseline
- Third-party requests blocked vs. baseline
- Whether consent banners were auto-handled
"""

from __future__ import annotations

from config import PET_CONFIGURATIONS, WEBSITES_CSV


async def crawl_with_pet(domain: str, pet_config: dict) -> dict:
    """Crawl a single website with a specific PET configuration active.

    Launches the browser specified in ``pet_config``, loads any required
    extensions, applies configuration (e.g., Firefox ETP mode), then
    crawls the domain and records cookies, requests, and tracker counts.

    Args:
        domain: The website domain to crawl.
        pet_config: A PET configuration dict from ``PET_CONFIGURATIONS``.

    Returns:
        A dict with crawl results including tracker/cookie counts and
        the PET configuration used.
    """
    raise NotImplementedError("Implemented in Phase 4")


async def run_pet_evaluation(websites_csv: str, output_path: str) -> None:
    """Run the full PET evaluation across all sites and configurations.

    For each website in the CSV and each PET in ``PET_CONFIGURATIONS``,
    crawls the site and records tracker reduction metrics. Writes a
    consolidated results file.

    Args:
        websites_csv: Path to the websites CSV file.
        output_path: Path to write the PET evaluation results.
    """
    raise NotImplementedError("Implemented in Phase 4")
