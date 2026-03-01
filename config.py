"""
Central configuration for the AECCS project.

Contains all paths, constants, scoring weights, proxy settings,
consent button keywords, CMP signatures, PET configurations,
and dataset/provenance helpers.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import tldextract

# ── Project Paths ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
REPORTING_DIR = PROJECT_ROOT / "reporting"
TLD_CACHE_DIR = DATA_DIR / ".cache" / "tldextract"
TLD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
TLD_EXTRACT = tldextract.TLDExtract(
    cache_dir=str(TLD_CACHE_DIR),
    suffix_list_urls=(),
)

VALID_SOURCE_MODES = ("real", "mock")
DEFAULT_SOURCE_MODE = "real"
PET_EFFECTIVENESS_FIELDS = [
    "domain",
    "source_mode",
    "run_id",
    "category",
    "pet_name",
    "measurement_mode",
    "browser_name",
    "browser_version",
    "extension_name",
    "extension_version",
    "extension_path",
    "extension_enabled",
    "consent_banner_detected",
    "page_load_time_ms",
    "total_cookies",
    "tracker_cookies",
    "tracker_domains",
    "total_third_party_domains",
    "total_requests",
    "blocked_requests",
    "success",
    "error",
]


@dataclass(frozen=True)
class DatasetLayout:
    source_mode: str
    data_root: Path
    raw_dir: Path
    processed_dir: Path
    screenshots_dir: Path
    banners_dir: Path
    tracker_lists_dir: Path
    websites_csv: Path
    report_dir: Path
    figures_dir: Path
    html_report: Path


def normalize_source_mode(source_mode: str | None) -> str:
    """Return a validated source mode."""
    mode = (source_mode or DEFAULT_SOURCE_MODE).strip().lower()
    if mode not in VALID_SOURCE_MODES:
        raise ValueError(
            f"Invalid source_mode={source_mode!r}; expected one of {VALID_SOURCE_MODES}"
        )
    return mode


def get_dataset_layout(source_mode: str | None = None) -> DatasetLayout:
    """Return dataset-aware paths for a given source mode."""
    mode = normalize_source_mode(source_mode)
    data_root = DATA_DIR / mode
    raw_dir = data_root / "raw"
    processed_dir = data_root / "processed"
    report_dir = REPORTING_DIR / mode
    return DatasetLayout(
        source_mode=mode,
        data_root=data_root,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        screenshots_dir=raw_dir / "screenshots",
        banners_dir=raw_dir / "banners",
        tracker_lists_dir=DATA_DIR / "tracker_lists",
        websites_csv=DATA_DIR / "websites.csv",
        report_dir=report_dir,
        figures_dir=report_dir / "figures",
        html_report=report_dir / "compliance_report.html",
    )


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def redact_proxy_url(proxy_url: str | None) -> str | None:
    """Return a provenance-safe proxy label without embedded credentials."""
    if not proxy_url:
        return None

    try:
        parsed = urlsplit(proxy_url)
    except ValueError:
        return "configured"

    if not parsed.scheme or not parsed.hostname:
        return "configured"

    host = parsed.hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}"


def generate_run_id(prefix: str | None = None) -> str:
    """Generate a readable run identifier."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{ts}" if prefix else ts


def build_provenance(
    *,
    source_mode: str | None = None,
    run_id: str | None = None,
    generated_at: str | None = None,
    proxy_used: str | None = None,
    browser_name: str | None = None,
    browser_version: str | None = None,
    site_list_source: str | None = None,
    pet_config: str | None = None,
    measurement_mode: str | None = None,
    extension_name: str | None = None,
    extension_version: str | None = None,
    extension_path: str | None = None,
    extension_enabled: bool | None = None,
) -> dict[str, object]:
    """Build a consistent provenance payload."""
    data = {
        "source_mode": normalize_source_mode(source_mode),
        "run_id": run_id or generate_run_id("aeccs"),
        "generated_at": generated_at or utc_now_iso(),
        "proxy_used": proxy_used,
        "browser_name": browser_name,
        "browser_version": browser_version,
        "site_list_source": site_list_source,
    }
    if pet_config is not None:
        data["pet_config"] = pet_config
    if measurement_mode is not None:
        data["measurement_mode"] = measurement_mode
    if extension_name is not None:
        data["extension_name"] = extension_name
    if extension_version is not None:
        data["extension_version"] = extension_version
    if extension_path is not None:
        data["extension_path"] = extension_path
    if extension_enabled is not None:
        data["extension_enabled"] = extension_enabled
    return data


def get_doc_source_mode(document: dict | None, default: str | None = None) -> str | None:
    """Extract source mode from a document if present."""
    if isinstance(document, dict) and document.get("source_mode"):
        return str(document["source_mode"])
    return default


def get_doc_run_id(document: dict | None, default: str | None = None) -> str | None:
    """Extract run id from a document if present."""
    if isinstance(document, dict) and document.get("run_id"):
        return str(document["run_id"])
    return default


def _normalize_provenance_value(value: object) -> str | None:
    """Collapse empty and NaN-like values to ``None``."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def infer_common_value(values: list[object] | tuple[object, ...]) -> str | None:
    """Return the single shared non-empty value if one exists."""
    cleaned = {
        normalized
        for normalized in (_normalize_provenance_value(value) for value in values)
        if normalized is not None
    }
    if len(cleaned) == 1:
        return next(iter(cleaned))
    return None


def infer_common_field(
    records: list[dict | None] | tuple[dict | None, ...],
    field: str,
) -> str | None:
    """Infer a shared field value across a set of dict-like records."""
    values: list[object] = []
    for record in records:
        if isinstance(record, dict):
            values.append(record.get(field))
    return infer_common_value(values)


def unwrap_payload(document: object, payload_key: str) -> object:
    """Support both legacy raw JSON and wrapped JSON payloads."""
    if isinstance(document, dict) and payload_key in document:
        return document[payload_key]
    return document


DEFAULT_LAYOUT = get_dataset_layout(DEFAULT_SOURCE_MODE)
RAW_DIR = DEFAULT_LAYOUT.raw_dir
PROCESSED_DIR = DEFAULT_LAYOUT.processed_dir
SCREENSHOTS_DIR = DEFAULT_LAYOUT.screenshots_dir
BANNERS_DIR = DEFAULT_LAYOUT.banners_dir
TRACKER_LISTS_DIR = DEFAULT_LAYOUT.tracker_lists_dir
WEBSITES_CSV = DEFAULT_LAYOUT.websites_csv
FIGURES_DIR = DEFAULT_LAYOUT.figures_dir
HTML_REPORT_PATH = DEFAULT_LAYOUT.html_report

# ── Proxy Configuration ───────────────────────────────────────────────────────
# Set this to an EU-based proxy (e.g., SOCKS5 or HTTP proxy) so that websites
# serve their GDPR-compliant cookie banners. Example:
#   PROXY_URL = "socks5://user:pass@eu-proxy.example.com:1080"
# Leave as None to connect directly (may not trigger EU cookie banners).
_CONFIG_PROXY_URL: str | None = None
PROXY_URL: str | None = os.environ.get("AECCS_PROXY_URL") or _CONFIG_PROXY_URL
PROXY_DISPLAY_URL: str | None = redact_proxy_url(PROXY_URL)

# ── Browser / Crawl Settings ──────────────────────────────────────────────────

USER_AGENTS = [
    # Chrome on Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Firefox on Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    # Edge on Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

# Randomized delay (seconds) between page loads to avoid rate-limiting
REQUEST_DELAY_RANGE: tuple[float, float] = (2.0, 5.0)

# Playwright page-load timeout in milliseconds
PAGE_LOAD_TIMEOUT: int = 30_000

# ── Consent Button Keywords (multilingual) ────────────────────────────────────

CONSENT_BUTTON_KEYWORDS: dict[str, list[str]] = {
    "accept": [
        # English
        "Accept", "Accept All", "Accept Cookies", "I Agree", "Allow All",
        # German
        "Akzeptieren", "Alle akzeptieren", "Zustimmen", "Alle Cookies akzeptieren",
        # French
        "Accepter", "Tout accepter", "J'accepte", "Accepter tout",
        # Dutch
        "Accepteren", "Alle accepteren", "Alle cookies accepteren",
        # Spanish
        "Aceptar", "Aceptar todo", "Aceptar todas",
        # Italian
        "Accetta", "Accetta tutto", "Accetta tutti",
        # Turkish
        "Kabul Et", "Tümünü Kabul Et",
    ],
    "reject": [
        # English
        "Reject", "Reject All", "Decline", "Deny", "Refuse All",
        # German
        "Ablehnen", "Alle ablehnen",
        # French
        "Refuser", "Tout refuser",
        # Dutch
        "Weigeren", "Alle weigeren",
        # Spanish
        "Rechazar", "Rechazar todo", "Rechazar todas",
        # Italian
        "Rifiuta", "Rifiuta tutto", "Rifiuta tutti",
        # Turkish
        "Reddet", "Tümünü Reddet",
    ],
}

# ── CMP Detection Signatures ──────────────────────────────────────────────────

CMP_SIGNATURES: dict[str, list[str]] = {
    "OneTrust": ["onetrust", "optanon", "cookie-consent-banner"],
    "Cookiebot": ["cookiebot", "CookieConsent", "Cybot"],
    "Quantcast": ["quantcast", "__cmpLocator", "cmp2.js"],
    "TrustArc": ["trustarc", "truste", "consent-manager"],
    "Didomi": ["didomi"],
    "Usercentrics": ["usercentrics"],
}

# ── GDPR Compliance Scoring Weights ───────────────────────────────────────────

COMPLIANCE_WEIGHTS: dict[str, float] = {
    "no_pre_consent_trackers": 0.25,
    "reject_option_available": 0.20,
    "equal_accept_reject_effort": 0.15,
    "no_dark_patterns": 0.15,
    "post_reject_compliance": 0.15,
    "transparent_information": 0.10,
}

# ── PET Configurations ────────────────────────────────────────────────────────

PET_CONFIGURATIONS: list[dict] = [
    {
        "name": "baseline",
        "browser": "chromium",
        "extension": None,
        "description": "Vanilla Chromium, no protection",
    },
    {
        "name": "ublock_origin",
        "browser": "chromium",
        "extension": "ublock-origin",
        "description": "uBlock Origin tracker blocker",
    },
    {
        "name": "privacy_badger",
        "browser": "chromium",
        "extension": "privacy-badger",
        "description": "EFF Privacy Badger",
    },
    {
        "name": "firefox_etp_standard",
        "browser": "firefox",
        "extension": None,
        "description": "Firefox ETP Standard mode",
    },
    {
        "name": "firefox_etp_strict",
        "browser": "firefox",
        "extension": None,
        "description": "Firefox ETP Strict mode",
    },
    {
        "name": "brave_shields",
        "browser": "chromium",
        "extension": None,
        "description": "Brave Shields (simulated via filter lists)",
    },
    {
        "name": "consent_o_matic",
        "browser": "chromium",
        "extension": "consent-o-matic",
        "description": "Auto-reject consent manager",
    },
]
