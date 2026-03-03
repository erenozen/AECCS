"""
Cookie and tracker classifier.

Classifies cookies and network requests captured during crawling using
public filter lists:
- EasyList / EasyPrivacy: ad and tracker blocking rules
- Disconnect: tracker entity mapping

Each cookie is classified as:
- First-party vs. third-party (based on domain matching with tldextract)
- Purpose category (analytics, advertising, functional, essential, unknown)
- Associated vendor/tracker entity (if matched against filter lists)
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import (
    DEFAULT_SOURCE_MODE,
    PROCESSED_DIR,
    RAW_DIR,
    TRACKER_LISTS_DIR,
    build_provenance,
    get_dataset_layout,
    TLD_EXTRACT,
)

# ── Fallback tracker map (used when filter list downloads fail) ───────────────

FALLBACK_TRACKERS: dict[str, dict[str, str]] = {
    # Advertising
    "doubleclick.net": {"vendor": "Google", "category": "Advertising"},
    "googlesyndication.com": {"vendor": "Google", "category": "Advertising"},
    "googleadservices.com": {"vendor": "Google", "category": "Advertising"},
    "googleads.g.doubleclick.net": {"vendor": "Google", "category": "Advertising"},
    "adnxs.com": {"vendor": "Xandr/Microsoft", "category": "Advertising"},
    "criteo.com": {"vendor": "Criteo", "category": "Advertising"},
    "criteo.net": {"vendor": "Criteo", "category": "Advertising"},
    "amazon-adsystem.com": {"vendor": "Amazon", "category": "Advertising"},
    "adsrvr.org": {"vendor": "The Trade Desk", "category": "Advertising"},
    "rubiconproject.com": {"vendor": "Rubicon Project", "category": "Advertising"},
    "pubmatic.com": {"vendor": "PubMatic", "category": "Advertising"},
    "casalemedia.com": {"vendor": "Casale Media", "category": "Advertising"},
    "openx.net": {"vendor": "OpenX", "category": "Advertising"},
    "taboola.com": {"vendor": "Taboola", "category": "Advertising"},
    "outbrain.com": {"vendor": "Outbrain", "category": "Advertising"},
    # Analytics
    "google-analytics.com": {"vendor": "Google", "category": "Analytics"},
    "googletagmanager.com": {"vendor": "Google", "category": "Analytics"},
    "hotjar.com": {"vendor": "Hotjar", "category": "Analytics"},
    "hotjar.io": {"vendor": "Hotjar", "category": "Analytics"},
    "mouseflow.com": {"vendor": "Mouseflow", "category": "Analytics"},
    "newrelic.com": {"vendor": "New Relic", "category": "Analytics"},
    "segment.io": {"vendor": "Segment", "category": "Analytics"},
    "segment.com": {"vendor": "Segment", "category": "Analytics"},
    "amplitude.com": {"vendor": "Amplitude", "category": "Analytics"},
    "mixpanel.com": {"vendor": "Mixpanel", "category": "Analytics"},
    "clarity.ms": {"vendor": "Microsoft", "category": "Analytics"},
    "scorecardresearch.com": {"vendor": "comScore", "category": "Analytics"},
    "chartbeat.com": {"vendor": "Chartbeat", "category": "Analytics"},
    "chartbeat.net": {"vendor": "Chartbeat", "category": "Analytics"},
    # Social
    "facebook.net": {"vendor": "Meta", "category": "Social"},
    "facebook.com": {"vendor": "Meta", "category": "Social"},
    "fbcdn.net": {"vendor": "Meta", "category": "Social"},
    "connect.facebook.net": {"vendor": "Meta", "category": "Social"},
    "twitter.com": {"vendor": "X/Twitter", "category": "Social"},
    "platform.twitter.com": {"vendor": "X/Twitter", "category": "Social"},
    "linkedin.com": {"vendor": "LinkedIn", "category": "Social"},
    "snap.licdn.com": {"vendor": "LinkedIn", "category": "Social"},
    "tiktok.com": {"vendor": "TikTok", "category": "Social"},
    # Fingerprinting / Tracking
    "demdex.net": {"vendor": "Adobe", "category": "Fingerprinting"},
    "omtrdc.net": {"vendor": "Adobe", "category": "Fingerprinting"},
    "krxd.net": {"vendor": "Salesforce/Krux", "category": "Fingerprinting"},
    "bluekai.com": {"vendor": "Oracle", "category": "Fingerprinting"},
    "exelator.com": {"vendor": "Nielsen", "category": "Fingerprinting"},
    "quantserve.com": {"vendor": "Quantcast", "category": "Fingerprinting"},
}

# Heuristic cookie-name patterns: (regex, vendor, category)
_COOKIE_HEURISTICS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^_ga$|^_ga_", re.I), "Google", "Analytics"),
    (re.compile(r"^_gid$", re.I), "Google", "Analytics"),
    (re.compile(r"^_gat", re.I), "Google", "Analytics"),
    (re.compile(r"^__utm", re.I), "Google", "Analytics"),
    (re.compile(r"_fbp|_fbc|fbp", re.I), "Meta", "Social"),
    (re.compile(r"^_hjid|^_hj", re.I), "Hotjar", "Analytics"),
    (re.compile(r"^_tt_", re.I), "TikTok", "Social"),
    (re.compile(r"^li_|^bcookie|^lidc", re.I), "LinkedIn", "Social"),
    (re.compile(r"^IDE$|^test_cookie$|^DSID$", re.I), "Google", "Advertising"),
    (re.compile(r"^NID$|^APISID$|^SAPISID$|^SID$|^SSID$|^HSID$", re.I), "Google", "Functional"),
    (re.compile(r"^_pin_|^_pinterest_", re.I), "Pinterest", "Social"),
    (re.compile(r"^amp_", re.I), "Amplitude", "Analytics"),
    (re.compile(r"^mp_", re.I), "Mixpanel", "Analytics"),
]

# ── Filter list URLs ──────────────────────────────────────────────────────────

_FILTER_LIST_URLS = {
    "easyprivacy.txt": "https://easylist.to/easylist/easyprivacy.txt",
    "easylist.txt": "https://easylist.to/easylist/easylist.txt",
}

_DISCONNECT_URLS = [
    "https://raw.githubusercontent.com/nicedayzhu/nicedayzhu.github.io/master/nicedayzhu.github.io/master/disconnect-tracking-protection/services.json",
    "https://raw.githubusercontent.com/nicedayzhu/nicedayzhu.github.io/master/disconnect-tracking-protection/services.json",
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_registered_domain(domain_str: str) -> str:
    """Return the registered domain from a cookie domain or URL."""
    cleaned = domain_str.lstrip(".")
    ext = TLD_EXTRACT(cleaned)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def _is_stale(path: Path, max_age_days: int = 7) -> bool:
    """Return True if *path* doesn't exist or is older than *max_age_days*."""
    if not path.exists():
        return True
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds > max_age_days * 86400


def _parse_adblock_domains(text: str) -> set[str]:
    """Extract domain names from an Adblock Plus filter list.

    Only parses ``||domain.com^`` style rules (simple domain blocks).
    """
    domains: set[str] = set()
    pattern = re.compile(r"^\|\|([a-zA-Z0-9._-]+)\^")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("!") or "##" in line or "#@#" in line:
            continue
        m = pattern.match(line)
        if m:
            domains.add(m.group(1).lower())
    return domains


def _parse_disconnect_services(data: dict) -> dict[str, dict[str, str]]:
    """Parse Disconnect ``services.json`` into a flat domain -> info map."""
    tracker_map: dict[str, dict[str, str]] = {}
    categories = data.get("categories", {})
    for category_name, entries in categories.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for company_name, details in entry.items():
                if not isinstance(details, dict):
                    continue
                for key, val in details.items():
                    if key in ("dnt", "performance"):
                        continue
                    if isinstance(val, list):
                        for domain in val:
                            if isinstance(domain, str):
                                tracker_map[domain.lower()] = {
                                    "vendor": company_name,
                                    "category": category_name,
                                }
                    elif isinstance(val, str) and "." in key:
                        tracker_map[key.lower()] = {
                            "vendor": company_name,
                            "category": category_name,
                        }
    return tracker_map


# ── Public API ────────────────────────────────────────────────────────────────


def download_filter_lists(tracker_lists_dir: str | None = None) -> None:
    """Download EasyList, EasyPrivacy, and Disconnect filter lists.

    Files are saved to *tracker_lists_dir* (default ``config.TRACKER_LISTS_DIR``).
    Skips files that already exist and are less than 7 days old.
    """
    dest = Path(tracker_lists_dir) if tracker_lists_dir else TRACKER_LISTS_DIR
    dest.mkdir(parents=True, exist_ok=True)

    for filename, url in _FILTER_LIST_URLS.items():
        path = dest / filename
        if not _is_stale(path):
            print(f"[SKIP] {filename} -- up-to-date")
            continue
        print(f"[DOWNLOAD] {filename} ...")
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            path.write_text(resp.text, encoding="utf-8")
            print(f"  -> saved ({len(resp.text) / 1024:.0f} KB)")
        except Exception as exc:
            print(f"  [WARN] Failed to download {filename}: {exc}")

    disc_path = dest / "disconnect_services.json"
    if not _is_stale(disc_path):
        print("[SKIP] disconnect_services.json -- up-to-date")
        return
    for url in _DISCONNECT_URLS:
        print(f"[DOWNLOAD] disconnect_services.json ...")
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            disc_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"  -> saved ({len(resp.text) / 1024:.0f} KB)")
            return
        except Exception as exc:
            print(f"  [WARN] {exc}")
    print("[WARN] All Disconnect URLs failed -- will use fallback tracker map.")


def load_filter_lists(tracker_lists_dir: str | None = None) -> dict:
    """Load and parse all tracker filter lists from disk.

    Returns a dict with keys ``easyprivacy_domains``, ``easylist_domains``,
    ``disconnect_services``, and ``tracker_domain_map``.
    """
    src = Path(tracker_lists_dir) if tracker_lists_dir else TRACKER_LISTS_DIR

    easyprivacy_domains: set[str] = set()
    easylist_domains: set[str] = set()
    disconnect_services: dict = {}
    tracker_domain_map: dict[str, dict[str, str]] = {}

    ep_path = src / "easyprivacy.txt"
    if ep_path.exists():
        easyprivacy_domains = _parse_adblock_domains(
            ep_path.read_text(encoding="utf-8")
        )
        print(f"[LOAD] EasyPrivacy: {len(easyprivacy_domains)} domains")
    else:
        print("[WARN] easyprivacy.txt not found")

    el_path = src / "easylist.txt"
    if el_path.exists():
        easylist_domains = _parse_adblock_domains(
            el_path.read_text(encoding="utf-8")
        )
        print(f"[LOAD] EasyList: {len(easylist_domains)} domains")
    else:
        print("[WARN] easylist.txt not found")

    disc_path = src / "disconnect_services.json"
    if disc_path.exists():
        try:
            disc_data = json.loads(disc_path.read_text(encoding="utf-8"))
            disconnect_services = disc_data
            tracker_domain_map = _parse_disconnect_services(disc_data)
            print(f"[LOAD] Disconnect: {len(tracker_domain_map)} tracker domains")
        except Exception as exc:
            print(f"[WARN] Failed to parse disconnect_services.json: {exc}")

    # Merge fallback (lower priority)
    for domain, info in FALLBACK_TRACKERS.items():
        tracker_domain_map.setdefault(domain, info)

    return {
        "easyprivacy_domains": easyprivacy_domains,
        "easylist_domains": easylist_domains,
        "disconnect_services": disconnect_services,
        "tracker_domain_map": tracker_domain_map,
    }


def classify_cookie(
    cookie: dict, filter_data: dict, site_domain: str
) -> dict:
    """Classify a single cookie.

    Determines first/third-party status, matches against filter lists,
    and applies heuristic rules.  Returns an enriched copy of the cookie dict.
    """
    result = dict(cookie)

    cookie_domain = cookie.get("domain", "")
    registered = _extract_registered_domain(cookie_domain)
    site_reg = _extract_registered_domain(site_domain)

    result["registered_domain"] = registered
    result["is_third_party"] = registered != site_reg

    # Expiration days
    expires = cookie.get("expires", 0)
    if not expires or expires <= 0:
        result["expiration_days"] = 0
    else:
        now_ts = datetime.now(timezone.utc).timestamp()
        result["expiration_days"] = max(0, round((expires - now_ts) / 86400))

    vendor = "Unknown"
    category = "Unknown"
    source = "unknown"
    is_tracker = False

    # 1. Disconnect / tracker_domain_map
    tdm = filter_data.get("tracker_domain_map", {})
    if registered in tdm:
        vendor = tdm[registered]["vendor"]
        category = tdm[registered]["category"]
        source = "disconnect"
        is_tracker = True
    elif cookie_domain.lstrip(".") in tdm:
        info = tdm[cookie_domain.lstrip(".")]
        vendor = info["vendor"]
        category = info["category"]
        source = "disconnect"
        is_tracker = True

    # 2. EasyPrivacy
    if not is_tracker:
        ep = filter_data.get("easyprivacy_domains", set())
        if registered in ep or cookie_domain.lstrip(".") in ep:
            category = "Analytics"
            source = "easyprivacy"
            is_tracker = True

    # 3. EasyList
    if not is_tracker:
        el = filter_data.get("easylist_domains", set())
        if registered in el or cookie_domain.lstrip(".") in el:
            category = "Advertising"
            source = "easylist"
            is_tracker = True

    # 4. Fallback trackers
    if not is_tracker and registered in FALLBACK_TRACKERS:
        info_fb = FALLBACK_TRACKERS[registered]
        vendor = info_fb["vendor"]
        category = info_fb["category"]
        source = "fallback"
        is_tracker = True

    # 5. Heuristic cookie-name patterns
    if not is_tracker:
        name = cookie.get("name", "")
        for pattern, h_vendor, h_category in _COOKIE_HEURISTICS:
            if pattern.search(name):
                vendor = h_vendor
                category = h_category
                source = "heuristic"
                is_tracker = True
                break

    # 6. Remaining heuristics for unmatched
    if not is_tracker:
        domain_lower = cookie_domain.lower()
        if not result["is_third_party"]:
            if any(kw in domain_lower for kw in ("cdn", "static", "assets")):
                category = "Functional"
                source = "heuristic"
            elif result["expiration_days"] == 0 or result["expiration_days"] < 1:
                category = "Functional"
                source = "heuristic"
            else:
                category = "Unknown"
        else:
            category = "Unknown"

    result["vendor"] = vendor
    result["category"] = category
    result["is_tracker"] = is_tracker
    result["classification_source"] = source
    return result


def classify_site_cookies(
    site_data_path: str, filter_data: dict
) -> list[dict]:
    """Classify all cookies for a single crawled site.

    Deduplicates cookies by ``(name, domain)`` and keeps the most
    informative version.
    """
    path = Path(site_data_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    domain = data.get("domain", path.stem)

    all_cookies: list[dict] = []
    for section in ("pre_consent", "post_consent_accept", "post_consent_reject"):
        section_data = data.get(section)
        if not section_data or not isinstance(section_data, dict):
            continue
        cookies = section_data.get("cookies", [])
        for c in cookies:
            enriched = classify_cookie(c, filter_data, domain)
            enriched["_source_phase"] = section
            all_cookies.append(enriched)

    # Deduplicate by (name, domain) -- prefer tracker-classified over unknown
    seen: dict[tuple[str, str], dict] = {}
    for c in all_cookies:
        key = (c.get("name", ""), c.get("domain", ""))
        existing = seen.get(key)
        if existing is None:
            seen[key] = c
        else:
            if c["is_tracker"] and not existing["is_tracker"]:
                seen[key] = c
            elif (
                c["classification_source"] != "unknown"
                and existing["classification_source"] == "unknown"
            ):
                seen[key] = c

    result = []
    for c in seen.values():
        c.pop("_source_phase", None)
        result.append(c)
    return result


def run_classification(
    raw_dir: str | None = None,
    output_dir: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> None:
    """Batch-classify cookies for all crawled sites."""
    layout = get_dataset_layout(source_mode)
    src = Path(raw_dir) if raw_dir else layout.raw_dir
    dest = Path(output_dir) if output_dir else layout.processed_dir
    dest.mkdir(parents=True, exist_ok=True)

    download_filter_lists()
    filter_data = load_filter_lists()

    json_files = sorted(src.glob("*.json"))
    if not json_files:
        print(f"[WARN] No JSON files found in {src}")
        return

    total_cookies = 0
    category_counter: Counter = Counter()
    vendor_counter: Counter = Counter()

    for jf in json_files:
        domain = jf.stem
        try:
            site_doc = json.loads(jf.read_text(encoding="utf-8"))
            classified = classify_site_cookies(str(jf), filter_data)
        except Exception as exc:
            print(f"[ERROR] {domain}: {exc}")
            continue

        out_path = dest / f"{domain}_classified.json"
        provenance = build_provenance(
            source_mode=site_doc.get("source_mode", source_mode),
            run_id=site_doc.get("run_id", run_id),
            proxy_used=site_doc.get("proxy_used"),
            browser_name=site_doc.get("browser_name"),
            browser_version=site_doc.get("browser_version"),
            site_list_source=site_doc.get("site_list_source"),
        )
        out_path.write_text(
            json.dumps(
                {
                    "domain": site_doc.get("domain", domain),
                    **provenance,
                    "cookies": classified,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        total_cookies += len(classified)
        for c in classified:
            category_counter[c["category"]] += 1
            if c["vendor"] != "Unknown":
                vendor_counter[c["vendor"]] += 1

        print(f"[OK] {domain}: {len(classified)} cookies classified")

    print(f"\n{'=' * 60}")
    print(f"Classification complete: {len(json_files)} sites, {total_cookies} cookies")
    print(f"\nBy category:")
    for cat, cnt in category_counter.most_common():
        print(f"  {cat:20s} {cnt:>5d}")
    print(f"\nTop 10 tracker vendors:")
    for vnd, cnt in vendor_counter.most_common(10):
        print(f"  {vnd:20s} {cnt:>5d}")
    print(f"{'=' * 60}")


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AECCS cookie & tracker classifier"
    )
    parser.add_argument(
        "--download-lists",
        action="store_true",
        help="Only download filter lists and exit",
    )
    parser.add_argument(
        "--raw-dir", type=str, default=None,
        help=f"Input directory with raw crawl JSON (default: {RAW_DIR})",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help=f"Output directory for classified JSON (default: {PROCESSED_DIR})",
    )
    parser.add_argument(
        "--domain", type=str, default=None,
        help="Classify a single domain only",
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

    if args.download_lists:
        download_filter_lists()
        return

    if args.domain:
        layout = get_dataset_layout(args.source_mode)
        src = Path(args.raw_dir) if args.raw_dir else layout.raw_dir
        dest = Path(args.output_dir) if args.output_dir else layout.processed_dir
        dest.mkdir(parents=True, exist_ok=True)

        download_filter_lists()
        filter_data = load_filter_lists()

        site_path = src / f"{args.domain}.json"
        if not site_path.exists():
            print(f"[ERROR] {site_path} not found")
            return

        site_doc = json.loads(site_path.read_text(encoding="utf-8"))
        classified = classify_site_cookies(str(site_path), filter_data)
        out_path = dest / f"{args.domain}_classified.json"
        provenance = build_provenance(
            source_mode=site_doc.get("source_mode", args.source_mode),
            run_id=site_doc.get("run_id", args.run_id),
            proxy_used=site_doc.get("proxy_used"),
            browser_name=site_doc.get("browser_name"),
            browser_version=site_doc.get("browser_version"),
            site_list_source=site_doc.get("site_list_source"),
        )
        out_path.write_text(
            json.dumps(
                {
                    "domain": site_doc.get("domain", args.domain),
                    **provenance,
                    "cookies": classified,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"[OK] {args.domain}: {len(classified)} cookies -> {out_path}")
        return

    run_classification(
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        source_mode=args.source_mode,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
