"""
Central configuration for the AECCS project.

Contains all paths, constants, scoring weights, proxy settings,
consent button keywords, CMP signatures, and PET configurations.
"""

from pathlib import Path

# ── Project Paths ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SCREENSHOTS_DIR = RAW_DIR / "screenshots"
BANNERS_DIR = RAW_DIR / "banners"
TRACKER_LISTS_DIR = DATA_DIR / "tracker_lists"

WEBSITES_CSV = DATA_DIR / "websites.csv"

# ── Proxy Configuration ───────────────────────────────────────────────────────
# Set this to an EU-based proxy (e.g., SOCKS5 or HTTP proxy) so that websites
# serve their GDPR-compliant cookie banners. Example:
#   PROXY_URL = "socks5://user:pass@eu-proxy.example.com:1080"
# Leave as None to connect directly (may not trigger EU cookie banners).
PROXY_URL: str | None = None

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
