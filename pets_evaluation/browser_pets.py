"""
Browser-based PET evaluation.

Re-runs the crawling pipeline under different browser PET configurations
to measure their effectiveness at blocking trackers and enforcing consent
preferences.  Configurations are defined in ``config.PET_CONFIGURATIONS``.

Tested PETs include:
- uBlock Origin (extension-based tracker blocker)
- Privacy Badger (EFF heuristic tracker blocker)
- Firefox Enhanced Tracking Protection (Standard and Strict modes)
- Brave Shields (simulated via filter lists)
- Consent-O-Matic (auto-reject consent extension)

For each PET the module records:
- Number of trackers blocked vs. baseline
- Cookies blocked vs. baseline
- Third-party requests blocked vs. baseline
- Whether consent banners were auto-handled
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import shutil
import tempfile
import time
from pathlib import Path

import pandas as pd

from config import (
    DATA_DIR,
    DEFAULT_SOURCE_MODE,
    PAGE_LOAD_TIMEOUT,
    PET_EFFECTIVENESS_FIELDS,
    PET_CONFIGURATIONS,
    PROCESSED_DIR,
    PROXY_DISPLAY_URL,
    PROXY_URL,
    RAW_DIR,
    REQUEST_DELAY_RANGE,
    USER_AGENTS,
    WEBSITES_CSV,
    TLD_EXTRACT,
    build_provenance,
    generate_run_id,
    get_dataset_layout,
)

# ── Extension management ──────────────────────────────────────────────────────

PET_EXTENSIONS_DIR = DATA_DIR / "pet_extensions"

_EXTENSION_INFO: dict[str, dict] = {
    "ublock-origin": {
        "dir_name": "ublock-origin",
        "display_name": "uBlock Origin",
        "github_url": "https://github.com/nicedayzhu/nicedayzhu.github.io",
    },
    "privacy-badger": {
        "dir_name": "privacy-badger",
        "display_name": "Privacy Badger",
        "github_url": "https://github.com/nicedayzhu/nicedayzhu.github.io",
    },
    "consent-o-matic": {
        "dir_name": "consent-o-matic",
        "display_name": "Consent-O-Matic",
        "github_url": "https://github.com/nicedayzhu/nicedayzhu.github.io",
    },
}


def setup_pet_extensions() -> dict[str, Path | None]:
    """Check for available browser extensions and return their paths.

    For each known extension:
      1. If the unpacked directory exists and contains *manifest.json* → use it.
      2. Otherwise print instructions and mark it as unavailable.

    Returns:
        Mapping of extension slug → Path (or *None* if missing).
    """
    PET_EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path | None] = {}

    for slug, info in _EXTENSION_INFO.items():
        ext_dir = PET_EXTENSIONS_DIR / info["dir_name"]
        manifest = ext_dir / "manifest.json"

        if ext_dir.is_dir() and manifest.is_file():
            print(f"[OK] Extension '{info['display_name']}' found at {ext_dir}")
            result[slug] = ext_dir
        else:
            print(
                f"[WARN] Extension '{info['display_name']}' not found at {ext_dir}\n"
                f"  To set up this extension:\n"
                f"    1. Download the extension source/release from its official GitHub repository\n"
                f"    2. Unpack it into: {ext_dir}\n"
                f"    3. Ensure the directory contains a manifest.json file\n"
                f"  Skipping this PET configuration.\n"
            )
            result[slug] = None

    return result


def _get_extension_version(ext_path: Path | None) -> str | None:
    """Extract an extension version from manifest.json if available."""
    if ext_path is None:
        return None
    manifest = ext_path / "manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return None
    version = data.get("version")
    return str(version) if version is not None else None


def _build_skipped_result(
    domain: str,
    pet_config: dict,
    *,
    source_mode: str,
    run_id: str,
    site_list_source: str,
    error: str,
) -> dict:
    """Build a synthetic result row for a skipped PET configuration."""
    ext_slug = pet_config.get("extension")
    result = {
        "domain": domain,
        "pet_name": pet_config["name"],
        "pet_description": pet_config["description"],
        "success": False,
        "error": error,
        "cookies": [],
        "http_requests": [],
        "third_party_domains": [],
        "total_cookies": 0,
        "total_third_party_domains": 0,
        "total_requests": 0,
        "tracker_cookies": 0,
        "tracker_domains": 0,
        "blocked_requests": 0,
        "consent_banner_detected": False,
        "page_load_time_ms": None,
        "browser_name": pet_config.get("browser", ""),
        "browser_version": None,
        "extension_name": ext_slug,
        "extension_version": None,
        "extension_path": None,
        "extension_enabled": False,
        "measurement_mode": "simulated" if pet_config["name"] == "brave_shields" else "real",
    }
    result.update(
        build_provenance(
            source_mode=source_mode,
            run_id=run_id,
            proxy_used=PROXY_DISPLAY_URL,
            browser_name=result["browser_name"],
            browser_version=result["browser_version"],
            site_list_source=site_list_source,
            pet_config=pet_config["name"],
            measurement_mode=result["measurement_mode"],
            extension_name=result["extension_name"],
            extension_version=result["extension_version"],
            extension_path=result["extension_path"],
            extension_enabled=False,
        )
    )
    return result


# ── Tracker classification integration ────────────────────────────────────────


def _classify_pet_cookies(
    cookies: list[dict],
    site_domain: str,
    filter_data: dict,
) -> tuple[int, int]:
    """Classify cookies captured during a PET crawl.

    Returns (tracker_cookie_count, tracker_domain_count).
    """
    from analysis.classifier import classify_cookie

    tracker_cookies = 0
    tracker_domains: set[str] = set()
    for cookie in cookies:
        classified = classify_cookie(cookie, filter_data, site_domain)
        if classified.get("is_tracker"):
            tracker_cookies += 1
            rd = classified.get("registered_domain", "")
            if rd:
                tracker_domains.add(rd)
    return tracker_cookies, len(tracker_domains)


def _count_tracker_domains(
    third_party_domains: list[str],
    filter_data: dict,
) -> int:
    """Count how many third-party domains are known trackers."""
    ep = filter_data.get("easyprivacy_domains", set())
    el = filter_data.get("easylist_domains", set())
    dc = filter_data.get("tracker_domain_map", {})

    from analysis.classifier import FALLBACK_TRACKERS

    count = 0
    for d in third_party_domains:
        if d in ep or d in el or d in dc or d in FALLBACK_TRACKERS:
            count += 1
    return count


# ── Brave Shields simulation: tracker domain list ────────────────────────────


def _load_block_domains(filter_data: dict) -> set[str]:
    """Return a set of tracker domains for route-blocking (Brave simulation)."""
    from analysis.classifier import FALLBACK_TRACKERS

    domains: set[str] = set()
    domains.update(filter_data.get("easyprivacy_domains", set()))
    domains.update(FALLBACK_TRACKERS.keys())
    # Keep it manageable — only the top-level domains
    return domains


# ── PET Crawler ───────────────────────────────────────────────────────────────


async def crawl_with_pet(
    domain: str,
    pet_config: dict,
    extension_paths: dict[str, Path | None],
    filter_data: dict,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
    site_list_source: str | None = None,
) -> dict:
    """Crawl a single website with a specific PET configuration active.

    Args:
        domain: The website domain to crawl.
        pet_config: A PET configuration dict from ``PET_CONFIGURATIONS``.
        extension_paths: Mapping of extension slug → local path.
        filter_data: Loaded filter lists for tracker classification.

    Returns:
        A dict with crawl results including tracker/cookie counts.
    """
    from playwright.async_api import async_playwright

    pet_name = pet_config["name"]
    pet_desc = pet_config["description"]
    ext_slug = pet_config.get("extension")

    result: dict = {
        "domain": domain,
        "pet_name": pet_name,
        "pet_description": pet_desc,
        "success": False,
        "error": None,
        "cookies": [],
        "http_requests": [],
        "third_party_domains": [],
        "total_cookies": 0,
        "total_third_party_domains": 0,
        "total_requests": 0,
        "tracker_cookies": 0,
        "tracker_domains": 0,
        "blocked_requests": 0,
        "consent_banner_detected": False,
        "page_load_time_ms": None,
        "browser_name": pet_config.get("browser", ""),
        "browser_version": None,
        "extension_name": ext_slug,
        "extension_version": None,
        "extension_path": None,
        "extension_enabled": False,
        "measurement_mode": "simulated" if pet_name == "brave_shields" else "real",
        **build_provenance(
            source_mode=source_mode,
            run_id=run_id,
            proxy_used=PROXY_DISPLAY_URL,
            browser_name=pet_config.get("browser", ""),
            browser_version=None,
            site_list_source=site_list_source,
            pet_config=pet_name,
            measurement_mode="simulated" if pet_name == "brave_shields" else "real",
            extension_name=ext_slug,
            extension_version=None,
            extension_path=None,
            extension_enabled=False,
        ),
    }

    url = f"https://{domain}"
    user_agent = random.choice(USER_AGENTS)
    tmp_dir: str | None = None

    try:
        async with async_playwright() as pw:
            browser = None
            context = None
            page = None
            request_log: list[dict] = []
            blocked_count = 0

            # ── Browser setup per PET type ────────────────────────────
            if pet_name == "baseline":
                browser = await pw.chromium.launch(
                    headless=True,
                    proxy={"server": PROXY_URL} if PROXY_URL else None,
                )
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-GB",
                    timezone_id="Europe/Berlin",
                )

            elif pet_name in ("ublock_origin", "privacy_badger", "consent_o_matic"):
                ext_path = extension_paths.get(ext_slug)
                if ext_path is None:
                    result["error"] = f"Extension '{ext_slug}' not available"
                    return result
                result["extension_version"] = _get_extension_version(ext_path)
                result["extension_path"] = str(ext_path)
                result["extension_enabled"] = True

                tmp_dir = tempfile.mkdtemp(prefix=f"aeccs_pet_{pet_name}_")
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=tmp_dir,
                    headless=False,
                    args=[
                        f"--disable-extensions-except={ext_path}",
                        f"--load-extension={ext_path}",
                        "--headless=new",
                    ],
                    proxy={"server": PROXY_URL} if PROXY_URL else None,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-GB",
                    timezone_id="Europe/Berlin",
                    user_agent=user_agent,
                )
                # Wait for extension to initialise
                await asyncio.sleep(3)

            elif pet_name == "firefox_etp_standard":
                browser = await pw.firefox.launch(
                    headless=True,
                    proxy={"server": PROXY_URL} if PROXY_URL else None,
                    firefox_user_prefs={
                        "privacy.trackingprotection.enabled": True,
                        "privacy.trackingprotection.socialtracking.enabled": True,
                        "network.cookie.cookieBehavior": 4,
                        "privacy.annotate_channels.strict_list.enabled": False,
                    },
                )
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-GB",
                    timezone_id="Europe/Berlin",
                )

            elif pet_name == "firefox_etp_strict":
                browser = await pw.firefox.launch(
                    headless=True,
                    proxy={"server": PROXY_URL} if PROXY_URL else None,
                    firefox_user_prefs={
                        "privacy.trackingprotection.enabled": True,
                        "privacy.trackingprotection.socialtracking.enabled": True,
                        "privacy.trackingprotection.cryptomining.enabled": True,
                        "privacy.trackingprotection.fingerprinting.enabled": True,
                        "network.cookie.cookieBehavior": 5,
                        "privacy.annotate_channels.strict_list.enabled": True,
                        "privacy.partition.network_state.ocsp_cache": True,
                    },
                )
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-GB",
                    timezone_id="Europe/Berlin",
                )

            elif pet_name == "brave_shields":
                # Simulate Brave Shields via Chromium + route blocking
                browser = await pw.chromium.launch(
                    headless=True,
                    proxy={"server": PROXY_URL} if PROXY_URL else None,
                )
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-GB",
                    timezone_id="Europe/Berlin",
                )

            else:
                result["error"] = f"Unknown PET configuration: {pet_name}"
                return result

            # ── Page setup ────────────────────────────────────────────
            if context is None:
                result["error"] = "Failed to create browser context"
                return result

            if browser is not None:
                result["browser_version"] = getattr(browser, "version", None)
            elif hasattr(context, "browser") and context.browser is not None:
                result["browser_version"] = getattr(context.browser, "version", None)

            page = await context.new_page()

            # Request logging
            async def _on_request(req):
                nonlocal request_log
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(req.url)
                    req_domain = parsed.netloc.lower().lstrip("www.")
                    request_log.append({
                        "url": req.url,
                        "method": req.method,
                        "resource_type": req.resource_type,
                        "domain": req_domain,
                    })
                except Exception:
                    pass

            page.on("request", _on_request)

            # Brave Shields: block known tracker domains
            if pet_name == "brave_shields":
                block_domains = _load_block_domains(filter_data)

                async def _block_tracker(route):
                    nonlocal blocked_count
                    from urllib.parse import urlparse

                    request = route.request
                    parsed = urlparse(request.url)
                    req_ext = TLD_EXTRACT(parsed.netloc.lower().lstrip("www."))
                    req_rd = f"{req_ext.domain}.{req_ext.suffix}".lower()

                    if req_rd in block_domains and req_rd != ".":
                        blocked_count += 1
                        await route.abort()
                        return

                    await route.continue_()

                # A single catch-all route scales far better than registering one
                # pattern per tracker domain.
                await page.route("**/*", _block_tracker)

            # ── Navigate ──────────────────────────────────────────────
            start_ts = time.perf_counter()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            except Exception:
                try:
                    await page.goto(url, wait_until="commit", timeout=PAGE_LOAD_TIMEOUT)
                except Exception as nav_err:
                    result["error"] = f"Navigation failed: {nav_err}"
                    return result
            finally:
                result["page_load_time_ms"] = int((time.perf_counter() - start_ts) * 1000)

            # Extra wait for dynamic content
            await asyncio.sleep(3)

            from scraper.crawler import detect_consent_banner

            banner = await detect_consent_banner(page)
            result["consent_banner_detected"] = bool(banner and banner.get("found"))

            # ── Capture state ─────────────────────────────────────────
            cookies = await context.cookies()
            site_ext = TLD_EXTRACT(domain)
            site_rd = f"{site_ext.domain}.{site_ext.suffix}".lower()

            third_party: set[str] = set()
            for req in request_log:
                req_ext = TLD_EXTRACT(req.get("domain", ""))
                req_rd = f"{req_ext.domain}.{req_ext.suffix}".lower()
                if req_rd and req_rd != site_rd and req_rd != ".":
                    third_party.add(req_rd)

            tp_sorted = sorted(third_party)

            # Classify cookies
            cookie_dicts = []
            for c in cookies:
                cookie_dicts.append({
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                    "expires": c.get("expires", -1),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                    "sameSite": c.get("sameSite", "None"),
                })

            tracker_cookies, tracker_cookie_domains = _classify_pet_cookies(
                cookie_dicts, domain, filter_data
            )
            tracker_domains = _count_tracker_domains(tp_sorted, filter_data)

            result.update({
                "success": True,
                "cookies": cookie_dicts,
                "http_requests": request_log,
                "third_party_domains": tp_sorted,
                "total_cookies": len(cookie_dicts),
                "total_third_party_domains": len(tp_sorted),
                "total_requests": len(request_log),
                "tracker_cookies": tracker_cookies,
                "tracker_domains": tracker_domains,
                "blocked_requests": blocked_count,
            })
            result.update(
                build_provenance(
                    source_mode=source_mode,
                    run_id=result.get("run_id"),
                    proxy_used=PROXY_DISPLAY_URL,
                    browser_name=result.get("browser_name"),
                    browser_version=result.get("browser_version"),
                    site_list_source=site_list_source,
                    pet_config=pet_name,
                    measurement_mode=result.get("measurement_mode"),
                    extension_name=result.get("extension_name"),
                    extension_version=result.get("extension_version"),
                    extension_path=result.get("extension_path"),
                    extension_enabled=result.get("extension_enabled"),
                )
            )

            # ── Cleanup ───────────────────────────────────────────────
            await page.close()
            if browser:
                await browser.close()
            elif context:
                await context.close()

    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


# ── Full PET evaluation runner ────────────────────────────────────────────────


async def run_pet_evaluation(
    websites_csv: str | None = None,
    output_path: str | None = None,
    pets: list[str] | None = None,
    max_sites: int | None = None,
    domain: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> None:
    """Run the full PET evaluation across sites and configurations.

    Args:
        websites_csv: Path to the website list CSV.
        output_path: Path for the output CSV.
        pets: PET names to test (default: all).
        max_sites: Limit number of sites tested.
        domain: Test a single domain instead of CSV list.
    """
    from analysis.classifier import load_filter_lists

    layout = get_dataset_layout(source_mode)
    csv_path = Path(websites_csv) if websites_csv else layout.websites_csv
    out_csv = Path(output_path) if output_path else layout.processed_dir / "pets_effectiveness.csv"
    out_json = out_csv.with_name("pets_raw_results.json")
    layout.processed_dir.mkdir(parents=True, exist_ok=True)

    # Determine sites to test
    if domain:
        domains = [domain]
        site_rows = [{"domain": domain, "category": "", "region": "", "rank": 0}]
    else:
        df = pd.read_csv(csv_path)
        col = "domain" if "domain" in df.columns else df.columns[0]
        domains = df[col].dropna().tolist()
        site_rows = df.to_dict(orient="records")
        if max_sites:
            domains = domains[:max_sites]
            site_rows = site_rows[:max_sites]
    category_by_domain = {
        row.get("domain"): row.get("category", "")
        for row in site_rows
        if row.get("domain")
    }

    # Determine PET configs
    if pets:
        configs = [c for c in PET_CONFIGURATIONS if c["name"] in pets]
    else:
        configs = list(PET_CONFIGURATIONS)

    # Setup extensions
    print("Checking PET extensions …")
    ext_paths = setup_pet_extensions()

    # Filter out unavailable extension PETs
    available_configs: list[dict] = []
    unavailable_configs: list[dict] = []
    for cfg in configs:
        ext_slug = cfg.get("extension")
        if ext_slug and ext_paths.get(ext_slug) is None:
            print(f"[SKIP] PET '{cfg['name']}' — extension not available")
            unavailable_configs.append(cfg)
            continue
        available_configs.append(cfg)

    if not available_configs and not unavailable_configs:
        print("[ERROR] No PET configurations available. Aborting.")
        return

    # Load filter lists once
    print("Loading filter lists …")
    filter_data = load_filter_lists()

    effective_run_id = run_id or generate_run_id("pets")

    total = len(domains) * (len(available_configs) + len(unavailable_configs))
    print(
        f"\nRunning PET evaluation: {len(domains)} sites × "
        f"{len(available_configs) + len(unavailable_configs)} PETs = {total} crawls\n"
    )

    all_results: list[dict] = []
    completed = 0

    for dom in domains:
        for cfg in unavailable_configs:
            completed += 1
            print(f"  [{completed}/{total}] {dom} — {cfg['name']} … SKIPPED")
            res = _build_skipped_result(
                dom,
                cfg,
                source_mode=source_mode,
                run_id=effective_run_id,
                site_list_source=str(csv_path) if not domain else "single-domain",
                error=f"SKIPPED: extension '{cfg.get('extension')}' not available",
            )
            res["category"] = category_by_domain.get(dom, "")
            all_results.append(res)

        for cfg in available_configs:
            completed += 1
            print(f"  [{completed}/{total}] {dom} — {cfg['name']} … ", end="", flush=True)
            res = await crawl_with_pet(
                dom,
                cfg,
                ext_paths,
                filter_data,
                source_mode=source_mode,
                run_id=effective_run_id,
                site_list_source=str(csv_path) if not domain else "single-domain",
            )
            res["category"] = category_by_domain.get(dom, "")
            all_results.append(res)

            if res["success"]:
                print(
                    f"OK (cookies={res['total_cookies']}, "
                    f"trackers={res['tracker_cookies']}, "
                    f"tp_domains={res['total_third_party_domains']})"
                )
            else:
                print(f"FAIL — {res.get('error', 'unknown')}")

            # Delay between crawls
            delay = random.uniform(*REQUEST_DELAY_RANGE)
            await asyncio.sleep(delay)

    # ── Save results ──────────────────────────────────────────────────────
    # CSV
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=PET_EFFECTIVENESS_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        for r in all_results:
            r.setdefault("category", "")
            writer.writerow(r)
    print(f"\nResults saved to {out_csv}")

    # Full JSON
    # Strip heavy fields for JSON output
    slim_results = []
    for r in all_results:
        slim = {k: v for k, v in r.items() if k not in ("cookies", "http_requests")}
        slim_results.append(slim)
    out_json.write_text(
        json.dumps(
            {
                **build_provenance(
                    source_mode=source_mode,
                    run_id=effective_run_id,
                    site_list_source=str(csv_path) if not domain else "single-domain",
                ),
                "results": slim_results,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"Raw results saved to {out_json}")

    # ── Print summary ─────────────────────────────────────────────────────
    _print_summary(all_results, available_configs)


def _print_summary(results: list[dict], configs: list[dict]) -> None:
    """Print a formatted effectiveness summary."""
    import statistics

    print(f"\n{'=' * 70}")
    print("PET EFFECTIVENESS SUMMARY")
    print(f"{'=' * 70}")

    # Group by PET
    by_pet: dict[str, list[dict]] = {}
    for r in results:
        by_pet.setdefault(r["pet_name"], []).append(r)

    baseline_trackers: list[int] = []
    baseline_domains: list[int] = []
    if "baseline" in by_pet:
        for r in by_pet["baseline"]:
            if r["success"]:
                baseline_trackers.append(r["tracker_cookies"])
                baseline_domains.append(r["tracker_domains"])

    avg_bl_t = statistics.mean(baseline_trackers) if baseline_trackers else 0
    avg_bl_d = statistics.mean(baseline_domains) if baseline_domains else 0

    print(f"\n{'PET':<25s} {'Avg Cookies':>12s} {'Avg Trackers':>13s} {'Avg TP Domains':>15s} {'Tracker Δ vs BL':>16s}")
    print("-" * 83)

    pet_scores: list[tuple[str, float]] = []
    for cfg in configs:
        name = cfg["name"]
        if name not in by_pet:
            continue
        success = [r for r in by_pet[name] if r["success"]]
        if not success:
            continue
        avg_c = statistics.mean([r["total_cookies"] for r in success])
        avg_t = statistics.mean([r["tracker_cookies"] for r in success])
        avg_d = statistics.mean([r["tracker_domains"] for r in success])
        if avg_bl_t > 0:
            reduction = (1 - avg_t / avg_bl_t) * 100
        else:
            reduction = 0.0
        pet_scores.append((name, reduction))
        print(f"{name:<25s} {avg_c:>12.1f} {avg_t:>13.1f} {avg_d:>15.1f} {reduction:>15.1f}%")

    if pet_scores:
        best = max(pet_scores, key=lambda x: x[1])
        print(f"\nBest performing PET: {best[0]} ({best[1]:.1f}% tracker reduction)")

    print(f"{'=' * 70}")


# ── CLI Entry Point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AECCS Browser PET Evaluation")
    parser.add_argument("--pets", nargs="+", default=None, help="PET names to test")
    parser.add_argument("--max-sites", type=int, default=None, help="Limit number of sites")
    parser.add_argument("--domain", type=str, default=None, help="Test single domain")
    parser.add_argument("--output", type=str, default=None, help="Output CSV path")
    parser.add_argument("--websites-csv", type=str, default=None, help="Websites CSV path")
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

    asyncio.run(
        run_pet_evaluation(
            websites_csv=args.websites_csv,
            output_path=args.output,
            pets=args.pets,
            max_sites=args.max_sites,
            domain=args.domain,
            source_mode=args.source_mode,
            run_id=args.run_id,
        )
    )


if __name__ == "__main__":
    main()
