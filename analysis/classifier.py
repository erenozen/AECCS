"""
Cookie and tracker classifier.

Classifies cookies and network requests captured during crawling using
public filter lists:
- EasyList / EasyPrivacy: ad and tracker blocking rules
- Disconnect: tracker entity mapping
- WhoTracksMe: tracker database with vendor/category info

Each cookie is classified as:
- First-party vs. third-party (based on domain matching with tldextract)
- Purpose category (analytics, advertising, functional, essential, unknown)
- Associated vendor/tracker entity (if matched against filter lists)
"""

from __future__ import annotations

from config import TRACKER_LISTS_DIR


def load_filter_lists(tracker_lists_dir: str) -> dict:
    """Load and parse all tracker filter lists from disk.

    Reads EasyList, EasyPrivacy, Disconnect services JSON, and WhoTracksMe
    database files from ``tracker_lists_dir`` and returns a unified data
    structure used by the classifier.

    Args:
        tracker_lists_dir: Path to the directory containing filter list files.

    Returns:
        A dict with parsed filter list data keyed by source name.
    """
    raise NotImplementedError("Implemented in Phase 2")


def classify_cookie(cookie: dict, filter_data: dict, site_domain: str) -> dict:
    """Classify a single cookie.

    Determines whether the cookie is first-party or third-party, matches
    it against filter lists to identify its purpose and vendor, and returns
    an enriched cookie dict.

    Args:
        cookie: Raw cookie dict from the crawler (name, domain, value, etc.).
        filter_data: Parsed filter list data from ``load_filter_lists``.
        site_domain: The domain of the crawled website (for 1st/3rd-party check).

    Returns:
        An enriched dict with added fields: party, category, vendor, matched_list.
    """
    raise NotImplementedError("Implemented in Phase 2")


def classify_site_cookies(
    site_data_path: str, filter_data: dict
) -> list[dict]:
    """Classify all cookies for a single crawled site.

    Reads the site's raw crawl JSON, classifies each cookie using
    ``classify_cookie``, and returns the list of enriched cookie dicts.

    Args:
        site_data_path: Path to the site's raw crawl JSON file.
        filter_data: Parsed filter list data.

    Returns:
        List of classified cookie dicts.
    """
    raise NotImplementedError("Implemented in Phase 2")


def run_classification(raw_dir: str, output_dir: str) -> None:
    """Batch-classify cookies for all crawled sites.

    Iterates over all raw crawl JSON files in ``raw_dir``, classifies
    their cookies, and writes per-site classification results to
    ``output_dir``.

    Args:
        raw_dir: Directory containing raw crawl JSON files.
        output_dir: Directory to write classified cookie JSON files.
    """
    raise NotImplementedError("Implemented in Phase 2")
