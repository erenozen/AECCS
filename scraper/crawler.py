"""
Website crawler with cookie consent banner interaction.

This module uses Playwright to crawl websites in headless mode, capturing:
- All cookies set before and after consent banner interaction
- HTTP requests (including third-party tracker requests)
- Consent banner HTML for dark pattern analysis
- Screenshots for manual verification

The crawler supports three interaction modes:
- "none": No interaction with the consent banner (baseline)
- "accept": Click the "Accept All" button
- "reject": Click the "Reject All" button

It also detects Consent Management Platforms (CMPs) like OneTrust, Cookiebot,
Quantcast, etc. by matching page content against known CMP signatures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth
from tqdm import tqdm

_stealth = Stealth()

from config import (
    BANNERS_DIR,
    CMP_SIGNATURES,
    CONSENT_BUTTON_KEYWORDS,
    DEFAULT_SOURCE_MODE,
    PAGE_LOAD_TIMEOUT,
    PROXY_DISPLAY_URL,
    PROXY_URL,
    RAW_DIR,
    REQUEST_DELAY_RANGE,
    SCREENSHOTS_DIR,
    USER_AGENTS,
    WEBSITES_CSV,
    TLD_EXTRACT,
    build_provenance,
    generate_run_id,
    get_dataset_layout,
)

# ── CSS selectors tried in order when looking for consent banners ─────────────

_BANNER_SELECTORS = [
    "#cookie-banner",
    "#cookie-consent",
    "#consent-banner",
    "#cookieConsent",
    "#onetrust-banner-sdk",
    "#CybotCookiebotDialog",
    "#qc-cmp2-container",
    ".cookie-banner",
    ".cookie-consent",
    ".consent-banner",
    ".cookie-notice",
    "[class*='cookie-banner']",
    "[class*='cookie-consent']",
    "[class*='consent-banner']",
    "[id*='cookie']",
    "[id*='consent']",
    "[id*='gdpr']",
    "[id*='privacy']",
    "[class*='cookie']",
    "[class*='consent']",
    "[class*='gdpr']",
    "[role='dialog'][aria-label*='cookie' i]",
    "[role='dialog'][aria-label*='consent' i]",
    "div[data-testid*='cookie']",
    "div[data-testid*='consent']",
]

# Keywords that indicate a "settings / manage preferences" button
_SETTINGS_KEYWORDS = [
    "settings",
    "preferences",
    "manage",
    "customize",
    "customise",
    "more options",
    "cookie settings",
    "cookie preferences",
    # German
    "einstellungen",
    # French
    "paramètres",
    "parametres",
    "gérer",
    "gerer",
    # Dutch
    "instellingen",
    # Spanish
    "opciones",
    "configurar",
    # Italian
    "impostazioni",
    # Turkish
    "ayarlar",
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_registered_domain(url: str) -> str:
    """Return the registered domain (e.g. 'google.com') from a URL."""
    ext = TLD_EXTRACT(url)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def _classify_button_text(text: str) -> str:
    """Classify button text as 'accept', 'reject', 'settings', or 'unknown'.

    Uses substring matching so that variations like "Accepter et continuer"
    or "Reject and close" are still recognised.
    """
    normalised = text.strip().lower()
    # Try exact match first (higher confidence)
    for kw in CONSENT_BUTTON_KEYWORDS["accept"]:
        if kw.lower() == normalised:
            return "accept"
    for kw in CONSENT_BUTTON_KEYWORDS["reject"]:
        if kw.lower() == normalised:
            return "reject"
    # Then substring containment
    for kw in CONSENT_BUTTON_KEYWORDS["reject"]:
        if kw.lower() in normalised:
            return "reject"
    for kw in CONSENT_BUTTON_KEYWORDS["accept"]:
        if kw.lower() in normalised:
            return "accept"
    for kw in _SETTINGS_KEYWORDS:
        if kw in normalised:
            return "settings"
    return "unknown"


def _safe_json(obj: object) -> object:
    """Fallback serialiser for json.dumps – converts non-serialisable types."""
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    return str(obj)


# ── CMP Detection ────────────────────────────────────────────────────────────


def detect_cmp(page_content: str, scripts: list[str]) -> str | None:
    """Identify the Consent Management Platform (CMP) used by the website.

    Checks both the page HTML and loaded script URLs against known
    ``CMP_SIGNATURES`` (case-insensitive).

    Args:
        page_content: The full HTML content of the page.
        scripts: List of script URLs loaded by the page.

    Returns:
        The CMP provider name, or None if no match.
    """
    content_lower = page_content.lower()
    scripts_lower = " ".join(scripts).lower()

    for cmp_name, signatures in CMP_SIGNATURES.items():
        for sig in signatures:
            sig_lower = sig.lower()
            if sig_lower in content_lower or sig_lower in scripts_lower:
                return cmp_name
    return None


# ── Consent Banner Detection ─────────────────────────────────────────────────


async def _get_button_styles(page, btn_handle) -> dict:
    """Extract computed styles for a button element."""
    try:
        return await page.evaluate(
            """(el) => {
                const cs = window.getComputedStyle(el);
                return {
                    width: cs.width,
                    height: cs.height,
                    background_color: cs.backgroundColor,
                    color: cs.color,
                    font_size: cs.fontSize,
                    font_weight: cs.fontWeight,
                    display: cs.display,
                    visibility: cs.visibility
                };
            }""",
            btn_handle,
        )
    except Exception:
        return {}


async def _extract_buttons(page, banner_handle) -> list[dict]:
    """Find all clickable elements inside a banner and classify them."""
    buttons: list[dict] = []
    try:
        btn_handles = await banner_handle.query_selector_all(
            "button, a[role='button'], input[type='button'], input[type='submit'], "
            "[role='button'], a.btn, a[class*='btn'], a[class*='button']"
        )
        for bh in btn_handles:
            text = (await bh.inner_text()).strip() if await bh.inner_text() else ""
            if not text:
                # Try value attribute for <input> elements
                text = await bh.get_attribute("value") or ""
                text = text.strip()
            if not text:
                text = await bh.get_attribute("aria-label") or ""
                text = text.strip()
            if not text:
                continue

            tag = await bh.evaluate("el => el.tagName.toLowerCase()")
            btn_type = _classify_button_text(text)
            styles = await _get_button_styles(page, bh)

            # Build a usable CSS selector for this button
            btn_id = await bh.get_attribute("id")
            if btn_id:
                selector = f"#{btn_id}"
            else:
                # Use text-based selector
                selector = f"{tag}:has-text('{text}')"

            buttons.append(
                {
                    "text": text,
                    "tag": tag,
                    "type": btn_type,
                    "selector": selector,
                    "computed_styles": styles,
                }
            )
    except Exception:
        pass
    return buttons


async def detect_consent_banner(page) -> dict | None:
    """Detect the cookie consent banner on the current page.

    Tries common CSS selectors, IAB TCF API detection, and fixed/sticky
    overlay heuristics. Returns structured info about the banner or None.

    Args:
        page: A Playwright Page object with the loaded website.

    Returns:
        A dict with banner info, or None if no banner is detected.
    """
    # Strategy 1: common CSS selectors
    # Collect all candidates, then pick the smallest (most specific) one.
    candidates: list[tuple[str, object]] = []  # (selector, element_handle)
    for selector in _BANNER_SELECTORS:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for i in range(min(count, 5)):  # check up to 5 matches per selector
                el = locator.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                except Exception:
                    continue
                handle = await el.element_handle()
                if not handle:
                    continue
                text_content = await handle.evaluate(
                    "el => el.innerText || el.textContent || ''"
                )
                text_lower = text_content.lower()
                all_keywords = (
                    CONSENT_BUTTON_KEYWORDS["accept"]
                    + CONSENT_BUTTON_KEYWORDS["reject"]
                )
                if not any(kw.lower() in text_lower for kw in all_keywords):
                    continue
                # Get element size to prefer the smallest (most specific) match
                bbox = await handle.bounding_box()
                area = (bbox["width"] * bbox["height"]) if bbox else float("inf")
                candidates.append((selector, handle, text_content, area))
        except Exception:
            continue

    if candidates:
        # Pick the candidate with the smallest area (most specific banner element)
        candidates.sort(key=lambda c: c[3])
        selector, handle, text_content, _ = candidates[0]
        html = await handle.evaluate("el => el.outerHTML")
        buttons = await _extract_buttons(page, handle)
        return _build_banner_result(selector, html, text_content, buttons)

    # Strategy 2: IAB TCF CMP detection
    try:
        has_tcf = await page.evaluate("typeof window.__tcfapi !== 'undefined'")
        if has_tcf:
            # TCF API exists – try to find the visible CMP container via
            # the __tcfapiLocator iframe or any visible dialog
            for sel in [
                "[id*='cmp']",
                "[class*='cmp']",
                "[id*='tcf']",
                "[class*='tcf']",
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        handle = await el.element_handle()
                        html = await handle.evaluate("el => el.outerHTML")
                        text_content = await handle.evaluate(
                            "el => el.innerText || el.textContent || ''"
                        )
                        buttons = await _extract_buttons(page, handle)
                        return _build_banner_result(sel, html, text_content, buttons)
                except Exception:
                    continue
    except Exception:
        pass

    # Strategy 3: fixed/sticky overlays with consent keywords
    try:
        accept_keywords_js = json.dumps(
            [kw.lower() for kw in CONSENT_BUTTON_KEYWORDS["accept"]]
        )
        result = await page.evaluate(
            """(keywords) => {
                const elems = document.querySelectorAll('div, section, aside');
                for (const el of elems) {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
                    const rect = el.getBoundingClientRect();
                    const inBottomOrTop = rect.top < 200 || rect.top > (window.innerHeight - 200);
                    if (!inBottomOrTop) continue;
                    const text = (el.innerText || '').toLowerCase();
                    for (const kw of keywords) {
                        if (text.includes(kw)) {
                            return {
                                html: el.outerHTML,
                                text: el.innerText || el.textContent || '',
                                tag: el.tagName.toLowerCase(),
                                id: el.id || null,
                                className: el.className || null
                            };
                        }
                    }
                }
                return null;
            }""",
            accept_keywords_js,
        )
        if result:
            # Build a selector from id or class
            if result["id"]:
                sel = f"#{result['id']}"
            elif result["className"]:
                first_cls = str(result["className"]).split()[0]
                sel = f"{result['tag']}.{first_cls}"
            else:
                sel = result["tag"]
            handle = await page.query_selector(sel)
            buttons = []
            if handle:
                buttons = await _extract_buttons(page, handle)
            return _build_banner_result(sel, result["html"], result["text"], buttons)
    except Exception:
        pass

    return None


def _build_banner_result(
    selector: str, html: str, text_content: str, buttons: list[dict]
) -> dict:
    """Assemble the banner detection result dict."""
    has_accept = any(b["type"] == "accept" for b in buttons)
    has_reject = any(b["type"] == "reject" for b in buttons)
    has_settings = any(b["type"] == "settings" for b in buttons)

    if has_accept:
        accept_clicks = 1
    else:
        accept_clicks = 999

    if has_reject:
        reject_clicks = 1
    elif has_settings:
        reject_clicks = 2  # settings → then reject/save inside
    else:
        reject_clicks = 999

    return {
        "found": True,
        "selector": selector,
        "html": html,
        "text_content": text_content,
        "buttons": buttons,
        "has_accept_button": has_accept,
        "has_reject_button": has_reject,
        "accept_clicks_required": accept_clicks,
        "reject_clicks_required": reject_clicks,
    }


# ── Consent Button Clicking ──────────────────────────────────────────────────


async def click_consent_button(page, interaction: str) -> bool:
    """Click the appropriate consent button (accept or reject).

    For reject: if no direct reject button exists, tries clicking the
    settings button first, waits for the panel, then looks for a reject
    or "save" button inside.

    Args:
        page: A Playwright Page object.
        interaction: ``"accept"`` or ``"reject"``.

    Returns:
        True if the button was clicked successfully, False otherwise.
    """
    banner = await detect_consent_banner(page)
    if not banner or not banner["found"]:
        return False

    if interaction == "accept":
        for btn in banner["buttons"]:
            if btn["type"] == "accept":
                try:
                    await page.click(btn["selector"], timeout=5000)
                    return True
                except Exception:
                    continue
        return False

    if interaction == "reject":
        # Try direct reject button first
        for btn in banner["buttons"]:
            if btn["type"] == "reject":
                try:
                    await page.click(btn["selector"], timeout=5000)
                    return True
                except Exception:
                    continue

        # No direct reject – try settings path
        for btn in banner["buttons"]:
            if btn["type"] == "settings":
                try:
                    await page.click(btn["selector"], timeout=5000)
                    await page.wait_for_timeout(2000)

                    # Re-scan for new buttons on the page
                    all_btns = await page.query_selector_all(
                        "button, a[role='button'], input[type='button'], "
                        "input[type='submit'], [role='button']"
                    )
                    for bh in all_btns:
                        try:
                            text = (await bh.inner_text()).strip()
                        except Exception:
                            continue
                        if not text:
                            continue
                        btn_type = _classify_button_text(text)
                        if btn_type == "reject":
                            await bh.click(timeout=5000)
                            return True

                    # Look for "save" / "confirm" buttons (with defaults = reject)
                    save_keywords = [
                        "save", "confirm", "save preferences",
                        "confirm choices", "speichern", "sauvegarder",
                        "opslaan", "guardar", "salva", "kaydet",
                    ]
                    for bh in all_btns:
                        try:
                            text = (await bh.inner_text()).strip().lower()
                        except Exception:
                            continue
                        for kw in save_keywords:
                            if kw in text:
                                await bh.click(timeout=5000)
                                return True

                except Exception:
                    continue

        return False

    return False


# ── State Capture ─────────────────────────────────────────────────────────────


async def _capture_state(
    context, page, collected_requests: list[dict], site_domain: str
) -> dict:
    """Capture the current browser state (cookies, storage, requests)."""
    cookies = await context.cookies()

    # Local storage
    try:
        ls_raw = await page.evaluate("() => JSON.stringify(localStorage)")
        local_storage = json.loads(ls_raw) if ls_raw else {}
    except Exception:
        local_storage = {}

    # Session storage
    try:
        ss_raw = await page.evaluate("() => JSON.stringify(sessionStorage)")
        session_storage = json.loads(ss_raw) if ss_raw else {}
    except Exception:
        session_storage = {}

    # Third-party domains
    all_request_domains = set()
    for req in collected_requests:
        try:
            all_request_domains.add(_extract_registered_domain(req["url"]))
        except Exception:
            continue
    third_party = sorted(
        d for d in all_request_domains if d and d != site_domain
    )

    return {
        "cookies": cookies,
        "http_requests": collected_requests,
        "third_party_domains": third_party,
        "local_storage": local_storage,
        "session_storage": session_storage,
        "total_cookies": len(cookies),
        "total_third_party_domains": len(third_party),
        "total_requests": len(collected_requests),
    }


# ── Core Crawling Engine ─────────────────────────────────────────────────────


async def crawl_site(
    domain: str,
    interaction: str = "none",
    headless: bool = True,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
    site_list_source: str | None = None,
) -> dict:
    """Crawl a single website and capture cookies, requests, and banner HTML.

    Args:
        domain: The website domain to crawl (e.g., "example.com").
        interaction: One of "none", "accept", or "reject".
        headless: Whether to run the browser in headless mode.

    Returns:
        A structured dict with pre/post interaction state, banner info,
        CMP detection, etc.
    """
    layout = get_dataset_layout(source_mode)
    timestamp = datetime.now(timezone.utc).isoformat()
    site_domain = _extract_registered_domain(domain)
    collected_requests: list[dict] = []

    async def _do_crawl() -> dict:
        async with async_playwright() as pw:
            # Browser launch options
            launch_opts: dict = {"headless": headless}
            if PROXY_URL:
                launch_opts["proxy"] = {"server": PROXY_URL}

            browser = await pw.chromium.launch(**launch_opts)
            try:
                ua = random.choice(USER_AGENTS)
                context = await browser.new_context(
                    user_agent=ua,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-GB",
                    timezone_id="Europe/Berlin",
                )
                context.set_default_navigation_timeout(PAGE_LOAD_TIMEOUT)

                page = await context.new_page()
                await _stealth.apply_stealth_async(page)

                # Request interception
                def on_request(request):
                    entry = {
                        "url": request.url,
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "domain": _extract_registered_domain(request.url),
                    }
                    headers = request.headers
                    if "cookie" in headers:
                        entry["cookie_header"] = headers["cookie"]
                    if "referer" in headers:
                        entry["referer"] = headers["referer"]
                    collected_requests.append(entry)

                page.on("request", on_request)

                # Navigate
                url = f"https://{domain}"
                try:
                    await page.goto(url, wait_until="networkidle", timeout=15000)
                except PlaywrightTimeout:
                    # Fall back to domcontentloaded
                    try:
                        await page.goto(url, wait_until="domcontentloaded")
                    except PlaywrightTimeout:
                        pass

                # Wait for late-firing scripts
                await page.wait_for_timeout(3000)

                # Screenshot
                layout.screenshots_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = layout.screenshots_dir / f"{domain}.png"
                try:
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                except Exception:
                    screenshot_path = None

                # Capture pre-interaction state
                pre_requests = list(collected_requests)
                pre_state = await _capture_state(
                    context, page, pre_requests, site_domain
                )

                # Detect consent banner
                banner = await detect_consent_banner(page)

                # Detect CMP
                page_content = await page.content()
                script_urls = [
                    r["url"]
                    for r in collected_requests
                    if r["resource_type"] == "script"
                ]
                cmp = detect_cmp(page_content, script_urls)

                # Save banner HTML
                banner_html = None
                if banner and banner["found"]:
                    banner_html = banner["html"]
                    layout.banners_dir.mkdir(parents=True, exist_ok=True)
                    banner_path = layout.banners_dir / f"{domain}.html"
                    banner_path.write_text(
                        f"<!-- domain: {domain} | timestamp: {timestamp} -->\n"
                        + banner_html,
                        encoding="utf-8",
                    )

                provenance = build_provenance(
                    source_mode=source_mode,
                    run_id=run_id,
                    generated_at=timestamp,
                    proxy_used=PROXY_DISPLAY_URL,
                    browser_name="chromium",
                    browser_version=getattr(browser, "version", None),
                    site_list_source=site_list_source,
                )

                result = {
                    "domain": domain,
                    "crawl_timestamp": timestamp,
                    "success": True,
                    "error": None,
                    "interaction": interaction,
                    "cmp_detected": cmp,
                    "consent_banner": banner,
                    "screenshot_path": str(screenshot_path) if screenshot_path else None,
                }
                result.update(provenance)

                # Post-interaction capture
                if interaction in ("accept", "reject"):
                    # Reset collected requests for post-interaction
                    pre_req_count = len(collected_requests)
                    click_ok = await click_consent_button(page, interaction)
                    await page.wait_for_timeout(3000)

                    post_requests = list(collected_requests[pre_req_count:])
                    post_state = await _capture_state(
                        context, page, list(collected_requests), site_domain
                    )

                    # Compute new cookies/domains after interaction
                    pre_cookie_names = {
                        (c["name"], c.get("domain", "")) for c in pre_state["cookies"]
                    }
                    new_cookies = [
                        c
                        for c in post_state["cookies"]
                        if (c["name"], c.get("domain", "")) not in pre_cookie_names
                    ]
                    pre_tp = set(pre_state["third_party_domains"])
                    new_tp = [
                        d
                        for d in post_state["third_party_domains"]
                        if d not in pre_tp
                    ]

                    post_state["new_cookies_after_interaction"] = new_cookies
                    post_state["new_third_party_domains_after_interaction"] = new_tp

                    if interaction == "reject":
                        post_state["reject_button_found"] = click_ok
                        post_state["reject_successful"] = click_ok

                    result["pre_consent"] = pre_state
                    result[f"post_consent_{interaction}"] = post_state
                else:
                    result["pre_consent"] = pre_state

                await context.close()
            finally:
                await browser.close()

            return result

    try:
        return await asyncio.wait_for(_do_crawl(), timeout=60)
    except Exception as exc:
        print(f"[ERROR] {domain}: {exc}")
        return {
            "domain": domain,
            "crawl_timestamp": timestamp,
            "success": False,
            "error": str(exc),
            "interaction": interaction,
            "cmp_detected": None,
            "consent_banner": None,
            "pre_consent": None,
            "screenshot_path": None,
            **build_provenance(
                source_mode=source_mode,
                run_id=run_id,
                generated_at=timestamp,
                proxy_used=PROXY_DISPLAY_URL,
                browser_name="chromium",
                browser_version=None,
                site_list_source=site_list_source,
            ),
        }


# ── Full Crawl Runner ────────────────────────────────────────────────────────


async def run_full_crawl(
    websites_csv: str | Path | None = None,
    output_dir: str | Path | None = None,
    headless: bool = True,
    force: bool = False,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> None:
    """Read the websites CSV and crawl every site in all three interaction modes.

    Args:
        websites_csv: Path to the CSV file listing target websites.
        output_dir: Directory to write per-site JSON result files.
        headless: Whether to run the browser in headless mode.
        force: If True, re-crawl even if the output JSON already exists.
    """
    layout = get_dataset_layout(source_mode)
    csv_path = Path(websites_csv) if websites_csv else layout.websites_csv
    out_dir = Path(output_dir) if output_dir else layout.raw_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path)
    domains = df.to_dict("records")

    success_count = 0
    fail_count = 0
    total_cookies = 0

    effective_run_id = run_id or generate_run_id("crawl")

    for row in tqdm(domains, desc="Crawling sites"):
        domain = row["domain"]
        output_path = out_dir / f"{domain}.json"

        if output_path.exists() and not force:
            print(f"[SKIP] {domain} — output already exists. Use --force to re-crawl.")
            continue

        # Run all three interaction modes
        results: dict = {
            "domain": domain,
            "category": row.get("category", ""),
            "region": row.get("region", ""),
            "rank": row.get("rank", 0),
            "crawl_timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "error": None,
            "cmp_detected": None,
            "consent_banner": None,
        }

        site_run_id = effective_run_id
        for mode in ("none", "accept", "reject"):
            data = await crawl_site(
                domain,
                interaction=mode,
                headless=headless,
                source_mode=source_mode,
                run_id=site_run_id,
                site_list_source=str(csv_path),
            )
            if site_run_id is None:
                site_run_id = data.get("run_id")

            if mode == "none":
                results["cmp_detected"] = data.get("cmp_detected")
                results["consent_banner"] = data.get("consent_banner")
                results["screenshot_path"] = data.get("screenshot_path")
                results["pre_consent"] = data.get("pre_consent")
                for field in (
                    "source_mode",
                    "run_id",
                    "generated_at",
                    "proxy_used",
                    "browser_name",
                    "browser_version",
                    "site_list_source",
                ):
                    results[field] = data.get(field)
                if not data.get("success", False):
                    results["success"] = False
                    results["error"] = data.get("error")
            elif mode == "accept":
                results["post_consent_accept"] = data.get(
                    "post_consent_accept", data.get("pre_consent")
                )
            elif mode == "reject":
                results["post_consent_reject"] = data.get(
                    "post_consent_reject", data.get("pre_consent")
                )

        # Tally stats
        if results["success"]:
            success_count += 1
            pre = results.get("pre_consent") or {}
            total_cookies += pre.get("total_cookies", 0)
        else:
            fail_count += 1

        # Save merged JSON
        output_path.write_text(
            json.dumps(results, indent=2, default=_safe_json), encoding="utf-8"
        )

        # Random delay between sites
        delay = random.uniform(*REQUEST_DELAY_RANGE)
        await asyncio.sleep(delay)

    # Summary
    total = success_count + fail_count
    avg_cookies = total_cookies / success_count if success_count else 0
    print(f"\n{'='*60}")
    print(f"Crawl complete: {total} sites")
    print(f"  Success: {success_count}")
    print(f"  Failed:  {fail_count}")
    print(f"  Avg cookies (pre-consent): {avg_cookies:.1f}")
    print(f"{'='*60}")


# ── Single-domain helper for CLI ─────────────────────────────────────────────


async def _crawl_single(
    domain: str,
    interactions: list[str],
    output_dir: Path,
    headless: bool,
    force: bool,
    source_mode: str,
    run_id: str | None,
) -> None:
    """Crawl a single domain in the given interaction modes and save JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{domain}.json"

    if output_path.exists() and not force:
        print(f"[SKIP] {domain} — output already exists. Use --force to re-crawl.")
        return

    if len(interactions) == 1 and interactions[0] != "all":
        result = await crawl_site(
            domain,
            interactions[0],
            headless=headless,
            source_mode=source_mode,
            run_id=run_id,
            site_list_source="single-domain",
        )
        result.setdefault("category", "")
        result.setdefault("region", "")
        result.setdefault("rank", 0)
        output_path.write_text(
            json.dumps(result, indent=2, default=_safe_json), encoding="utf-8"
        )
        print(f"[OK] {domain} ({interactions[0]}) → {output_path}")
    else:
        # Run all 3 modes and merge
        merged: dict = {
            "domain": domain,
            "category": "",
            "region": "",
            "rank": 0,
            "crawl_timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "error": None,
        }
        site_run_id = run_id or generate_run_id("crawl")
        for mode in ("none", "accept", "reject"):
            data = await crawl_site(
                domain,
                mode,
                headless=headless,
                source_mode=source_mode,
                run_id=site_run_id,
                site_list_source="single-domain",
            )
            if site_run_id is None:
                site_run_id = data.get("run_id")
            if mode == "none":
                merged["cmp_detected"] = data.get("cmp_detected")
                merged["consent_banner"] = data.get("consent_banner")
                merged["screenshot_path"] = data.get("screenshot_path")
                merged["pre_consent"] = data.get("pre_consent")
                for field in (
                    "source_mode",
                    "run_id",
                    "generated_at",
                    "proxy_used",
                    "browser_name",
                    "browser_version",
                    "site_list_source",
                ):
                    merged[field] = data.get(field)
                if not data.get("success"):
                    merged["success"] = False
                    merged["error"] = data.get("error")
            elif mode == "accept":
                merged["post_consent_accept"] = data.get(
                    "post_consent_accept", data.get("pre_consent")
                )
            elif mode == "reject":
                merged["post_consent_reject"] = data.get(
                    "post_consent_reject", data.get("pre_consent")
                )
        output_path.write_text(
            json.dumps(merged, indent=2, default=_safe_json), encoding="utf-8"
        )
        print(f"[OK] {domain} (all modes) → {output_path}")


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AECCS website crawler — capture cookies and consent banners"
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help=f"Path to websites CSV (default: {WEBSITES_CSV})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=f"Output directory for JSON results (default: {RAW_DIR})",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Single domain to crawl (skips CSV)",
    )
    parser.add_argument(
        "--interaction",
        type=str,
        choices=["none", "accept", "reject", "all"],
        default="all",
        help="Interaction mode for single-domain crawl (default: all)",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run browser in headless mode (default: True, use --no-headless to disable)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-crawl even if output JSON already exists",
    )
    parser.add_argument(
        "--source-mode",
        choices=["real", "mock"],
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

    layout = get_dataset_layout(args.source_mode)
    output_dir = Path(args.output) if args.output else layout.raw_dir

    if args.domain:
        interactions = (
            [args.interaction] if args.interaction != "all" else ["all"]
        )
        asyncio.run(
            _crawl_single(
                args.domain,
                interactions,
                output_dir,
                args.headless,
                args.force,
                args.source_mode,
                args.run_id,
            )
        )
    else:
        asyncio.run(
            run_full_crawl(
                websites_csv=args.csv,
                output_dir=args.output,
                headless=args.headless,
                force=args.force,
                source_mode=args.source_mode,
                run_id=args.run_id,
            )
        )


if __name__ == "__main__":
    main()
