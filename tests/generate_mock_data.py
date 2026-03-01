"""
Generate 20 realistic mock website crawl JSON files and banner HTML files.

Creates diverse test data covering:
- High-compliance (clean) sites
- Low-compliance sites with many pre-consent trackers
- Sites with various dark patterns (asymmetric buttons, preselected checkboxes, etc.)
- Different CMPs (OneTrust, Cookiebot, Quantcast, TrustArc, Didomi, Usercentrics)
- Failed crawls
- Sites without consent banners
- Multiple categories and regions

Usage:
    python -m tests.generate_mock_data
"""

from __future__ import annotations

import json
import random
import string
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import build_provenance, generate_run_id, get_dataset_layout

LAYOUT = get_dataset_layout("mock")
BANNERS_DIR = LAYOUT.banners_dir
RAW_DIR = LAYOUT.raw_dir

# ── Tracker definitions ──────────────────────────────────────────────────────

TRACKER_COOKIES = [
    {"domain": ".doubleclick.net", "vendor": "Google", "cat": "Advertising"},
    {"domain": ".google-analytics.com", "vendor": "Google", "cat": "Analytics"},
    {"domain": ".googlesyndication.com", "vendor": "Google", "cat": "Advertising"},
    {"domain": ".facebook.com", "vendor": "Meta", "cat": "Advertising"},
    {"domain": ".facebook.net", "vendor": "Meta", "cat": "Social"},
    {"domain": ".criteo.com", "vendor": "Criteo", "cat": "Advertising"},
    {"domain": ".adnxs.com", "vendor": "Xandr", "cat": "Advertising"},
    {"domain": ".amazon-adsystem.com", "vendor": "Amazon", "cat": "Advertising"},
    {"domain": ".hotjar.com", "vendor": "Hotjar", "cat": "Analytics"},
    {"domain": ".chartbeat.com", "vendor": "Chartbeat", "cat": "Analytics"},
    {"domain": ".optimizely.com", "vendor": "Optimizely", "cat": "Analytics"},
    {"domain": ".rubiconproject.com", "vendor": "Rubicon", "cat": "Advertising"},
    {"domain": ".taboola.com", "vendor": "Taboola", "cat": "Advertising"},
    {"domain": ".outbrain.com", "vendor": "Outbrain", "cat": "Advertising"},
    {"domain": ".quantserve.com", "vendor": "Quantcast", "cat": "Analytics"},
    {"domain": ".newrelic.com", "vendor": "New Relic", "cat": "Analytics"},
    {"domain": ".mixpanel.com", "vendor": "Mixpanel", "cat": "Analytics"},
    {"domain": ".segment.io", "vendor": "Segment", "cat": "Analytics"},
    {"domain": ".pubmatic.com", "vendor": "PubMatic", "cat": "Advertising"},
    {"domain": ".openx.net", "vendor": "OpenX", "cat": "Advertising"},
]

FIRST_PARTY_COOKIES = [
    {"name": "session_id", "cat": "Essential"},
    {"name": "csrf_token", "cat": "Essential"},
    {"name": "lang", "cat": "Functional"},
    {"name": "theme", "cat": "Functional"},
    {"name": "consent_given", "cat": "Essential"},
    {"name": "__cfduid", "cat": "Essential"},
    {"name": "user_pref", "cat": "Functional"},
    {"name": "remember_me", "cat": "Functional"},
]

THIRD_PARTY_DOMAINS_POOL = [
    "doubleclick.net", "google-analytics.com", "googlesyndication.com",
    "facebook.com", "facebook.net", "criteo.com", "adnxs.com",
    "amazon-adsystem.com", "hotjar.com", "chartbeat.com",
    "optimizely.com", "rubiconproject.com", "taboola.com", "outbrain.com",
    "quantserve.com", "newrelic.com", "mixpanel.com", "segment.io",
    "pubmatic.com", "openx.net", "adsrvr.org", "casalemedia.com",
    "moatads.com", "scorecardresearch.com", "cloudflare.com",
]

CMP_OPTIONS = ["OneTrust", "Cookiebot", "Quantcast", "TrustArc", "Didomi", "Usercentrics", None]
CATEGORIES = ["News", "E-Commerce", "Social Media", "Government", "Technology", "Finance", "Entertainment", "Education"]
REGIONS = ["EU", "US", "UK", "DE", "FR", "NL"]


def _rand_hex(n: int = 16) -> str:
    return "".join(random.choices(string.hexdigits[:16], k=n))


def _rand_value() -> str:
    return _rand_hex(random.randint(16, 48))


def _make_cookie(name: str, domain: str, *, http_only: bool = False) -> dict:
    return {
        "name": name,
        "value": _rand_value(),
        "domain": domain,
        "path": "/",
        "expires": int(datetime.now(timezone.utc).timestamp()) + random.randint(3600, 31536000),
        "httpOnly": http_only,
        "secure": random.choice([True, True, False]),
        "sameSite": random.choice(["Lax", "None", "Strict"]),
    }


def _make_first_party_cookies(site_domain: str, count: int) -> list[dict]:
    cookies = []
    templates = random.sample(FIRST_PARTY_COOKIES, min(count, len(FIRST_PARTY_COOKIES)))
    for t in templates:
        cookies.append(_make_cookie(t["name"], f".{site_domain}"))
    # Pad with generic cookies if needed
    for i in range(count - len(templates)):
        cookies.append(_make_cookie(f"_fp_{i}", f".{site_domain}"))
    return cookies


def _make_tracker_cookies(count: int) -> list[dict]:
    cookies = []
    trackers = random.sample(TRACKER_COOKIES, min(count, len(TRACKER_COOKIES)))
    for t in trackers:
        name = f"_{_rand_hex(4)}"
        cookies.append(_make_cookie(name, t["domain"]))
    return cookies


def _pick_third_party_domains(count: int) -> list[str]:
    return sorted(random.sample(THIRD_PARTY_DOMAINS_POOL, min(count, len(THIRD_PARTY_DOMAINS_POOL))))


def _make_http_requests(site_domain: str, third_party_domains: list[str]) -> list[dict]:
    requests_list = [
        {"url": f"https://{site_domain}/", "method": "GET", "resource_type": "document", "domain": site_domain},
    ]
    for tp in third_party_domains:
        requests_list.append({
            "url": f"https://cdn.{tp}/script.js",
            "method": "GET",
            "resource_type": random.choice(["script", "image", "xhr"]),
            "domain": tp,
            "referer": f"https://{site_domain}/",
        })
    return requests_list


def _make_consent_section(
    site_domain: str,
    *,
    n_first_party: int,
    n_tracker: int,
    n_third_party: int,
    is_post: bool = False,
    pre_cookies: list | None = None,
    pre_domains: list | None = None,
) -> dict:
    fp = _make_first_party_cookies(site_domain, n_first_party)
    tp_cookies = _make_tracker_cookies(n_tracker)
    all_cookies = fp + tp_cookies
    third_party = _pick_third_party_domains(n_third_party)
    http_reqs = _make_http_requests(site_domain, third_party)

    section: dict = {
        "cookies": all_cookies,
        "http_requests": http_reqs,
        "third_party_domains": third_party,
        "local_storage": {},
        "session_storage": {},
        "total_cookies": len(all_cookies),
        "total_third_party_domains": len(third_party),
        "total_requests": len(http_reqs),
    }

    if is_post and pre_cookies is not None and pre_domains is not None:
        pre_names = {(c["name"], c["domain"]) for c in pre_cookies}
        new_cookies = [c for c in all_cookies if (c["name"], c["domain"]) not in pre_names]
        new_domains = [d for d in third_party if d not in pre_domains]
        section["new_cookies_after_interaction"] = new_cookies
        section["new_third_party_domains_after_interaction"] = new_domains

    return section


# ── Banner HTML generators ────────────────────────────────────────────────────


def _banner_clean(site_domain: str) -> str:
    """Equal accept/reject buttons, no dark patterns."""
    return f"""<div id="cookie-consent-banner" role="dialog" aria-label="Cookie consent">
  <div class="banner-content">
    <h2>We value your privacy</h2>
    <p>We use cookies to enhance your browsing experience on {site_domain}.
       You can accept or reject non-essential cookies.</p>
    <div class="button-group" style="display:flex; gap:10px;">
      <button id="accept-all" class="btn btn-primary"
              style="width:200px; height:44px; font-size:16px; font-weight:500;
                     background-color:#2563eb; color:#fff;">
        Accept All
      </button>
      <button id="reject-all" class="btn btn-secondary"
              style="width:200px; height:44px; font-size:16px; font-weight:500;
                     background-color:#dc2626; color:#fff;">
        Reject All
      </button>
    </div>
    <a href="/privacy-policy">Privacy Policy</a>
  </div>
</div>"""


def _banner_asymmetric(site_domain: str) -> str:
    """Accept button much bigger than reject — dark pattern."""
    return f"""<div id="cookie-consent" role="dialog">
  <div class="consent-body">
    <h3>Cookie Notice — {site_domain}</h3>
    <p>We and our partners use cookies for analytics and advertising.</p>
    <div class="actions">
      <button id="accept" class="btn-accept"
              style="width:300px; height:60px; font-size:18px; font-weight:700;
                     background-color:#22c55e; color:#fff;">
        Accept All Cookies
      </button>
      <button id="reject" class="btn-reject"
              style="width:100px; height:30px; font-size:11px; font-weight:300;
                     background-color:#e5e7eb; color:#9ca3af;">
        Decline
      </button>
    </div>
  </div>
</div>"""


def _banner_hidden_reject(site_domain: str) -> str:
    """Reject button exists but is hidden via CSS."""
    return f"""<div id="consent-modal" role="dialog">
  <h3>Cookies on {site_domain}</h3>
  <p>We use cookies to personalise content and ads.</p>
  <button id="accept-btn" class="primary"
          style="width:250px; height:48px; font-size:16px; font-weight:600;
                 background-color:#1d4ed8; color:#fff; display:block;">
    Accept All
  </button>
  <button id="reject-btn" class="secondary"
          style="width:250px; height:48px; font-size:16px; font-weight:600;
                 background-color:#ef4444; color:#fff; display:none; visibility:hidden;">
    Reject All
  </button>
</div>"""


def _banner_no_reject(site_domain: str) -> str:
    """No reject button at all."""
    return f"""<div class="cookie-wall" role="dialog">
  <h2>This website uses cookies</h2>
  <p>{site_domain} uses cookies. By continuing to browse, you agree.</p>
  <button id="ok-btn" class="accept-button"
          style="width:250px; height:44px; font-size:16px; font-weight:500;
                 background-color:#059669; color:#fff;">
    OK, I Agree
  </button>
  <a href="/cookie-settings" style="font-size:12px;">Manage Settings</a>
</div>"""


def _banner_preselected(site_domain: str) -> str:
    """Banner with preselected non-essential checkboxes."""
    return f"""<div id="cookie-preferences" role="dialog">
  <h3>Cookie Preferences — {site_domain}</h3>
  <p>Choose which cookies you'd like to allow:</p>
  <form>
    <label><input type="checkbox" checked disabled> Necessary cookies</label>
    <label><input type="checkbox" checked> Analytics cookies</label>
    <label><input type="checkbox" checked> Advertising cookies</label>
    <label><input type="checkbox" checked> Social media cookies</label>
  </form>
  <div class="actions" style="display:flex; gap:10px;">
    <button id="save-prefs" class="btn"
            style="width:200px; height:44px; font-size:16px; font-weight:500;
                   background-color:#2563eb; color:#fff;">
      Accept Selected
    </button>
    <button id="reject-all" class="btn"
            style="width:200px; height:44px; font-size:16px; font-weight:500;
                   background-color:#dc2626; color:#fff;">
      Reject All
    </button>
  </div>
</div>"""


def _banner_confusing(site_domain: str) -> str:
    """Banner with guilt-tripping and confusing double-negative language."""
    return f"""<div class="gdpr-banner" role="dialog">
  <h3>Help us keep {site_domain} free!</h3>
  <p>Without cookies, we cannot provide you with the best experience.
     Don't you not want to miss out on personalised content?</p>
  <p>By declining, you may lose access to premium features and
     the content you love will suffer.</p>
  <div class="choices">
    <button id="accept" class="btn-green"
            style="width:250px; height:48px; font-size:16px; font-weight:600;
                   background-color:#16a34a; color:#fff;">
      Yes, I want the best experience
    </button>
    <button id="decline" class="btn-gray"
            style="width:250px; height:48px; font-size:16px; font-weight:600;
                   background-color:#6b7280; color:#fff;">
      No, I don't want personalisation
    </button>
  </div>
</div>"""


def _banner_multi_layer(site_domain: str) -> str:
    """Accept is 1 click, reject requires going to settings."""
    return f"""<div class="consent-layer" role="dialog">
  <h3>{site_domain} — Cookie Consent</h3>
  <p>We use cookies for essential functions and with your consent for analytics and ads.</p>
  <button id="accept" class="btn primary"
          style="width:250px; height:44px; font-size:16px; font-weight:500;
                 background-color:#2563eb; color:#fff;">
    Accept All
  </button>
  <a href="/cookie-settings" class="settings-link"
     style="font-size:13px; color:#6b7280;">
    Manage cookie settings
  </a>
</div>"""


def _banner_forced_action(site_domain: str) -> str:
    """Cookie wall — must accept to access."""
    return f"""<div class="cookie-wall-overlay"
     style="position:fixed; top:0; left:0; width:100%; height:100%;
            background:rgba(0,0,0,0.8); z-index:9999;">
  <div class="wall-content" style="background:#fff; padding:40px; margin:10% auto; max-width:600px;">
    <h2>You must accept cookies to continue</h2>
    <p>{site_domain} requires cookies to function. Accept to proceed.</p>
    <button id="accept" class="accept-wall"
            style="width:250px; height:48px; font-size:16px; font-weight:600;
                   background-color:#059669; color:#fff;">
      Accept All Cookies
    </button>
  </div>
</div>"""


# ── Site profile definitions ─────────────────────────────────────────────────

SITE_PROFILES = [
    # 1-4: HIGH compliance — clean banners, few trackers
    {
        "domain": "cleansite.de",
        "category": "Government",
        "region": "DE",
        "cmp": "Cookiebot",
        "banner_fn": _banner_clean,
        "pre_trackers": 0, "pre_fp": 3, "pre_tp": 1,
        "post_accept_trackers": 4, "post_accept_fp": 6, "post_accept_tp": 5,
        "post_reject_trackers": 0, "post_reject_fp": 3, "post_reject_tp": 1,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    {
        "domain": "privacy-first.nl",
        "category": "Government",
        "region": "NL",
        "cmp": "OneTrust",
        "banner_fn": _banner_clean,
        "pre_trackers": 0, "pre_fp": 2, "pre_tp": 0,
        "post_accept_trackers": 3, "post_accept_fp": 5, "post_accept_tp": 4,
        "post_reject_trackers": 0, "post_reject_fp": 2, "post_reject_tp": 0,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    {
        "domain": "edu-portal.fr",
        "category": "Education",
        "region": "FR",
        "cmp": "Didomi",
        "banner_fn": _banner_clean,
        "pre_trackers": 1, "pre_fp": 4, "pre_tp": 2,
        "post_accept_trackers": 5, "post_accept_fp": 7, "post_accept_tp": 6,
        "post_reject_trackers": 0, "post_reject_fp": 4, "post_reject_tp": 1,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    {
        "domain": "goodbank.eu",
        "category": "Finance",
        "region": "EU",
        "cmp": "Usercentrics",
        "banner_fn": _banner_clean,
        "pre_trackers": 0, "pre_fp": 5, "pre_tp": 0,
        "post_accept_trackers": 2, "post_accept_fp": 6, "post_accept_tp": 3,
        "post_reject_trackers": 0, "post_reject_fp": 5, "post_reject_tp": 0,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    # 5-8: MEDIUM compliance — some issues
    {
        "domain": "news-daily.co.uk",
        "category": "News",
        "region": "UK",
        "cmp": "OneTrust",
        "banner_fn": _banner_multi_layer,
        "pre_trackers": 3, "pre_fp": 5, "pre_tp": 4,
        "post_accept_trackers": 10, "post_accept_fp": 8, "post_accept_tp": 12,
        "post_reject_trackers": 2, "post_reject_fp": 5, "post_reject_tp": 3,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 3,
    },
    {
        "domain": "shopmore.de",
        "category": "E-Commerce",
        "region": "DE",
        "cmp": "Cookiebot",
        "banner_fn": _banner_preselected,
        "pre_trackers": 2, "pre_fp": 6, "pre_tp": 3,
        "post_accept_trackers": 8, "post_accept_fp": 10, "post_accept_tp": 9,
        "post_reject_trackers": 1, "post_reject_fp": 6, "post_reject_tp": 2,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    {
        "domain": "techblog.com",
        "category": "Technology",
        "region": "US",
        "cmp": "Quantcast",
        "banner_fn": _banner_confusing,
        "pre_trackers": 4, "pre_fp": 4, "pre_tp": 5,
        "post_accept_trackers": 12, "post_accept_fp": 8, "post_accept_tp": 14,
        "post_reject_trackers": 3, "post_reject_fp": 4, "post_reject_tp": 4,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    {
        "domain": "socialnet.fr",
        "category": "Social Media",
        "region": "FR",
        "cmp": "Didomi",
        "banner_fn": _banner_asymmetric,
        "pre_trackers": 5, "pre_fp": 3, "pre_tp": 6,
        "post_accept_trackers": 15, "post_accept_fp": 6, "post_accept_tp": 16,
        "post_reject_trackers": 4, "post_reject_fp": 3, "post_reject_tp": 5,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    # 9-12: LOW compliance — dark patterns, many trackers
    {
        "domain": "adtracker-news.com",
        "category": "News",
        "region": "US",
        "cmp": "TrustArc",
        "banner_fn": _banner_hidden_reject,
        "pre_trackers": 10, "pre_fp": 4, "pre_tp": 12,
        "post_accept_trackers": 18, "post_accept_fp": 8, "post_accept_tp": 20,
        "post_reject_trackers": 9, "post_reject_fp": 4, "post_reject_tp": 11,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    {
        "domain": "shady-shop.eu",
        "category": "E-Commerce",
        "region": "EU",
        "cmp": None,
        "banner_fn": _banner_no_reject,
        "pre_trackers": 8, "pre_fp": 5, "pre_tp": 10,
        "post_accept_trackers": 14, "post_accept_fp": 8, "post_accept_tp": 15,
        "post_reject_trackers": 8, "post_reject_fp": 5, "post_reject_tp": 10,
        "has_reject": False, "accept_clicks": 1, "reject_clicks": 999,
    },
    {
        "domain": "freestream.tv",
        "category": "Entertainment",
        "region": "EU",
        "cmp": None,
        "banner_fn": _banner_forced_action,
        "pre_trackers": 12, "pre_fp": 3, "pre_tp": 14,
        "post_accept_trackers": 18, "post_accept_fp": 6, "post_accept_tp": 18,
        "post_reject_trackers": 12, "post_reject_fp": 3, "post_reject_tp": 14,
        "has_reject": False, "accept_clicks": 1, "reject_clicks": 999,
    },
    {
        "domain": "clickbait.io",
        "category": "News",
        "region": "US",
        "cmp": None,
        "banner_fn": _banner_asymmetric,
        "pre_trackers": 15, "pre_fp": 2, "pre_tp": 16,
        "post_accept_trackers": 20, "post_accept_fp": 5, "post_accept_tp": 22,
        "post_reject_trackers": 14, "post_reject_fp": 2, "post_reject_tp": 15,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    # 13-16: SPECIAL CASES
    {
        "domain": "minimal.org",
        "category": "Education",
        "region": "EU",
        "cmp": None,
        "banner_fn": None,  # No banner at all
        "pre_trackers": 0, "pre_fp": 2, "pre_tp": 0,
        "post_accept_trackers": 0, "post_accept_fp": 2, "post_accept_tp": 0,
        "post_reject_trackers": 0, "post_reject_fp": 2, "post_reject_tp": 0,
        "has_reject": False, "accept_clicks": 999, "reject_clicks": 999,
        "no_banner": True,
    },
    {
        "domain": "broken-crawl.net",
        "category": "Technology",
        "region": "US",
        "cmp": None,
        "banner_fn": None,
        "failed": True,
        "error": "TimeoutError: Page load timed out after 30000ms",
    },
    {
        "domain": "tracker-heavy.de",
        "category": "News",
        "region": "DE",
        "cmp": "OneTrust",
        "banner_fn": _banner_confusing,
        "pre_trackers": 8, "pre_fp": 4, "pre_tp": 10,
        "post_accept_trackers": 16, "post_accept_fp": 8, "post_accept_tp": 18,
        "post_reject_trackers": 7, "post_reject_fp": 4, "post_reject_tp": 9,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 2,
    },
    {
        "domain": "wall-site.nl",
        "category": "Entertainment",
        "region": "NL",
        "cmp": None,
        "banner_fn": _banner_forced_action,
        "pre_trackers": 6, "pre_fp": 3, "pre_tp": 8,
        "post_accept_trackers": 12, "post_accept_fp": 6, "post_accept_tp": 13,
        "post_reject_trackers": 6, "post_reject_fp": 3, "post_reject_tp": 8,
        "has_reject": False, "accept_clicks": 1, "reject_clicks": 999,
    },
    # 17-20: MORE VARIETY
    {
        "domain": "vidshare.com",
        "category": "Entertainment",
        "region": "US",
        "cmp": "TrustArc",
        "banner_fn": _banner_multi_layer,
        "pre_trackers": 6, "pre_fp": 5, "pre_tp": 8,
        "post_accept_trackers": 14, "post_accept_fp": 8, "post_accept_tp": 16,
        "post_reject_trackers": 3, "post_reject_fp": 5, "post_reject_tp": 4,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 3,
    },
    {
        "domain": "fintech.eu",
        "category": "Finance",
        "region": "EU",
        "cmp": "Usercentrics",
        "banner_fn": _banner_preselected,
        "pre_trackers": 2, "pre_fp": 6, "pre_tp": 3,
        "post_accept_trackers": 6, "post_accept_fp": 9, "post_accept_tp": 7,
        "post_reject_trackers": 0, "post_reject_fp": 6, "post_reject_tp": 1,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    {
        "domain": "dark-patterns.shop",
        "category": "E-Commerce",
        "region": "EU",
        "cmp": None,
        "banner_fn": _banner_hidden_reject,
        "pre_trackers": 9, "pre_fp": 4, "pre_tp": 11,
        "post_accept_trackers": 16, "post_accept_fp": 8, "post_accept_tp": 18,
        "post_reject_trackers": 8, "post_reject_fp": 4, "post_reject_tp": 10,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
    {
        "domain": "open-data.gov.uk",
        "category": "Government",
        "region": "UK",
        "cmp": "OneTrust",
        "banner_fn": _banner_clean,
        "pre_trackers": 0, "pre_fp": 3, "pre_tp": 1,
        "post_accept_trackers": 2, "post_accept_fp": 5, "post_accept_tp": 3,
        "post_reject_trackers": 0, "post_reject_fp": 3, "post_reject_tp": 0,
        "has_reject": True, "accept_clicks": 1, "reject_clicks": 1,
    },
]


def _make_banner_info(profile: dict) -> dict | None:
    if profile.get("failed"):
        return None
    if profile.get("no_banner") or profile.get("banner_fn") is None:
        return {"found": False}

    fn = profile["banner_fn"]
    html = fn(profile["domain"])
    # Extract button info from the HTML
    buttons = []
    # Simple extraction for test data
    import re as _re

    for m in _re.finditer(
        r'<(?:button|a)\s[^>]*?id=["\']([^"\']+)["\'][^>]*?style="([^"]*)"[^>]*?>\s*(.*?)\s*</(?:button|a)>',
        html,
        _re.DOTALL,
    ):
        btn_id, style, text = m.groups()
        text = text.strip()
        # Parse style attributes
        w = _re.search(r"width:\s*(\d+)px", style)
        h = _re.search(r"height:\s*(\d+)px", style)
        fs = _re.search(r"font-size:\s*(\d+)px", style)
        fw = _re.search(r"font-weight:\s*(\d+)", style)
        bg = _re.search(r"background-color:\s*(#[0-9a-fA-F]+|rgb[^;]+)", style)
        clr = _re.search(r"(?<![a-z-])color:\s*(#[0-9a-fA-F]+|rgb[^;]+)", style)
        vis = "hidden" if "display:none" in style or "visibility:hidden" in style else "visible"
        disp_match = _re.search(r"display:\s*([^;]+)", style)
        disp = disp_match.group(1).strip() if disp_match else "block"

        # Determine button type
        text_lower = text.lower()
        if any(k in text_lower for k in ["accept", "agree", "ok"]):
            btn_type = "accept"
        elif any(k in text_lower for k in ["reject", "decline", "refuse", "deny"]):
            btn_type = "reject"
        else:
            btn_type = "unknown"

        buttons.append({
            "text": text,
            "tag": "button",
            "type": btn_type,
            "selector": f"button#{btn_id}",
            "computed_styles": {
                "width": f"{w.group(1)}px" if w else "auto",
                "height": f"{h.group(1)}px" if h else "auto",
                "background_color": bg.group(1) if bg else "rgba(0,0,0,0)",
                "color": clr.group(1) if clr else "rgb(0,0,0)",
                "font_size": f"{fs.group(1)}px" if fs else "16px",
                "font_weight": fw.group(1) if fw else "400",
                "display": disp,
                "visibility": vis,
            },
        })

    return {
        "found": True,
        "selector": f"[id*='cookie'], [id*='consent'], [class*='cookie'], [class*='consent'], [class*='gdpr']",
        "html": html,
        "text_content": _re.sub(r"<[^>]+>", " ", html).strip(),
        "buttons": buttons,
        "has_accept_button": any(b["type"] == "accept" for b in buttons),
        "has_reject_button": profile.get("has_reject", False),
        "accept_clicks_required": profile.get("accept_clicks", 1),
        "reject_clicks_required": profile.get("reject_clicks", 999),
    }


def generate_site(profile: dict, run_id: str) -> dict:
    """Generate a single mock site JSON from a profile."""
    domain = profile["domain"]
    ts = datetime.now(timezone.utc).isoformat()

    if profile.get("failed"):
        return {
            "domain": domain,
            "category": profile.get("category", ""),
            "region": profile.get("region", ""),
            "rank": random.randint(1, 10000),
            "crawl_timestamp": ts,
            "success": False,
            "error": profile.get("error", "Unknown error"),
            "cmp_detected": None,
            "consent_banner": None,
            "screenshot_path": None,
            **build_provenance(
                source_mode="mock",
                run_id=run_id,
                generated_at=ts,
                proxy_used=None,
                browser_name="mock-browser",
                browser_version="synthetic",
                site_list_source="tests/generate_mock_data.py",
            ),
            "pre_consent": {
                "cookies": [], "http_requests": [], "third_party_domains": [],
                "local_storage": {}, "session_storage": {},
                "total_cookies": 0, "total_third_party_domains": 0, "total_requests": 0,
            },
        }

    banner_info = _make_banner_info(profile)

    pre = _make_consent_section(
        domain,
        n_first_party=profile.get("pre_fp", 3),
        n_tracker=profile.get("pre_trackers", 0),
        n_third_party=profile.get("pre_tp", 1),
    )

    post_accept = _make_consent_section(
        domain,
        n_first_party=profile.get("post_accept_fp", 6),
        n_tracker=profile.get("post_accept_trackers", 5),
        n_third_party=profile.get("post_accept_tp", 8),
        is_post=True,
        pre_cookies=pre["cookies"],
        pre_domains=pre["third_party_domains"],
    )

    post_reject = _make_consent_section(
        domain,
        n_first_party=profile.get("post_reject_fp", 3),
        n_tracker=profile.get("post_reject_trackers", 0),
        n_third_party=profile.get("post_reject_tp", 1),
        is_post=True,
        pre_cookies=pre["cookies"],
        pre_domains=pre["third_party_domains"],
    )

    if profile.get("has_reject"):
        post_reject["reject_button_found"] = True
        post_reject["reject_successful"] = True
    else:
        post_reject["reject_button_found"] = False
        post_reject["reject_successful"] = False

    return {
        "domain": domain,
        "category": profile.get("category", ""),
        "region": profile.get("region", ""),
        "rank": random.randint(1, 10000),
        "crawl_timestamp": ts,
        "success": True,
        "error": None,
        "cmp_detected": profile.get("cmp"),
        "consent_banner": banner_info,
        "screenshot_path": str(LAYOUT.screenshots_dir / f"{domain}.png"),
        **build_provenance(
            source_mode="mock",
            run_id=run_id,
            generated_at=ts,
            proxy_used=None,
            browser_name="mock-browser",
            browser_version="synthetic",
            site_list_source="tests/generate_mock_data.py",
        ),
        "pre_consent": pre,
        "post_consent_accept": post_accept,
        "post_consent_reject": post_reject,
    }


def generate_all() -> None:
    """Generate all 20 mock sites and save to data/mock/raw/."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    BANNERS_DIR.mkdir(parents=True, exist_ok=True)
    LAYOUT.screenshots_dir.mkdir(parents=True, exist_ok=True)

    random.seed(42)  # Reproducible output
    run_id = generate_run_id("mock")

    for profile in SITE_PROFILES:
        domain = profile["domain"]
        site_data = generate_site(profile, run_id)

        # Write JSON
        out_path = RAW_DIR / f"{domain}.json"
        out_path.write_text(json.dumps(site_data, indent=2, default=str), encoding="utf-8")
        print(f"  Created {out_path.name}")

        # Write banner HTML if applicable
        if profile.get("banner_fn") and not profile.get("failed"):
            banner_html = profile["banner_fn"](domain)
            banner_path = BANNERS_DIR / f"{domain}.html"
            banner_path.write_text(banner_html, encoding="utf-8")
            print(f"  Created banner: {banner_path.name}")

    print(f"\nGenerated {len(SITE_PROFILES)} mock sites in {RAW_DIR}")
    print(f"Banner files in {BANNERS_DIR}")


if __name__ == "__main__":
    generate_all()
