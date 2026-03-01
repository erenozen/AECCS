"""
Generate mock PET evaluation data for testing Phase 3 Modules 2-4.

Produces ``data/processed/pets_effectiveness.csv`` with realistic patterns:
- baseline: most trackers (no protection)
- ublock_origin: near-zero trackers
- privacy_badger: moderate reduction (~60-80%)
- firefox_etp_standard: significant reduction (~50-70%)
- firefox_etp_strict: stronger reduction (~70-85%)
- brave_shields: strong reduction (~80-95%)
- consent_o_matic: reduces cookies but not network tracker domains

This data allows dp_reporting, cmp_analysis, and comparison modules to be
tested without running actual browser PET evaluations.

Usage:
    python -m tests.generate_mock_pets_data
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from config import PROCESSED_DIR, RAW_DIR


PETS = [
    "baseline",
    "ublock_origin",
    "privacy_badger",
    "firefox_etp_standard",
    "firefox_etp_strict",
    "brave_shields",
    "consent_o_matic",
]


def _get_domains() -> list[str]:
    """Get all crawled domains from raw data."""
    domains: list[str] = []
    raw = Path(RAW_DIR)
    for f in sorted(raw.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("success"):
                domains.append(data.get("domain", f.stem))
        except Exception:
            continue
    return domains


def _baseline_trackers(domain: str) -> tuple[int, int, int, int]:
    """Return (tracker_domains, tracker_cookies, total_cookies, total_requests)
    from actual raw data if available, otherwise generate."""
    raw_file = RAW_DIR / f"{domain}.json"
    if raw_file.exists():
        try:
            data = json.loads(raw_file.read_text(encoding="utf-8"))
            pre = data.get("pre_consent", {})
            tp = len(pre.get("third_party_domains", []))
            cookies = pre.get("cookies", [])
            total_cookies = len(cookies)
            # Estimate tracker cookies as proportion of third-party cookies
            tracker_cookies = sum(
                1 for c in cookies
                if c.get("domain", "").lstrip(".") not in domain
            )
            requests = len(pre.get("http_requests", []))
            return tp, tracker_cookies, total_cookies, max(requests, 10)
        except Exception:
            pass
    # Fallback random
    td = random.randint(3, 15)
    tc = random.randint(2, td + 3)
    tot_c = tc + random.randint(3, 8)
    req = random.randint(20, 80)
    return td, tc, tot_c, req


def generate_mock_pets_effectiveness() -> None:
    """Generate pets_effectiveness.csv with realistic per-PET results."""
    random.seed(42)
    domains = _get_domains()

    if not domains:
        print("No crawled domains found in raw data. Run generate_mock_data first.")
        return

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = PROCESSED_DIR / "pets_effectiveness.csv"

    fields = [
        "domain", "pet_name", "tracker_domains", "tracker_cookies",
        "total_cookies", "total_requests", "page_load_time_ms",
        "consent_banner_detected", "cookies_after_reject",
    ]

    rows: list[dict] = []

    for domain in domains:
        base_td, base_tc, base_tot_c, base_req = _baseline_trackers(domain)

        for pet in PETS:
            if pet == "baseline":
                td = base_td
                tc = base_tc
                tot_c = base_tot_c
                tot_r = base_req
                load_ms = random.randint(800, 3000)
                banner = True
                cookies_after_rej = max(0, tot_c - random.randint(0, 2))

            elif pet == "ublock_origin":
                # Near-complete blocking
                td = random.randint(0, max(1, base_td // 8))
                tc = random.randint(0, max(1, base_tc // 8))
                tot_c = max(tc, base_tot_c - random.randint(base_tc // 2, base_tc))
                tot_r = max(5, base_req - random.randint(base_req // 3, base_req // 2))
                load_ms = random.randint(500, 1800)
                banner = random.random() < 0.3  # uBlock may hide banners
                cookies_after_rej = max(0, tc - random.randint(0, tc))

            elif pet == "privacy_badger":
                # Moderate blocking (60-80%)
                reduction = random.uniform(0.60, 0.80)
                td = max(0, int(base_td * (1 - reduction)))
                tc = max(0, int(base_tc * (1 - reduction)))
                tot_c = max(tc, base_tot_c - int(base_tc * reduction * 0.7))
                tot_r = max(5, base_req - int(base_req * reduction * 0.3))
                load_ms = random.randint(600, 2200)
                banner = True
                cookies_after_rej = max(0, tot_c - random.randint(0, 3))

            elif pet == "firefox_etp_standard":
                # Significant blocking (50-70%)
                reduction = random.uniform(0.50, 0.70)
                td = max(0, int(base_td * (1 - reduction)))
                tc = max(0, int(base_tc * (1 - reduction)))
                tot_c = max(tc, base_tot_c - int(base_tc * reduction * 0.6))
                tot_r = max(5, base_req - int(base_req * reduction * 0.25))
                load_ms = random.randint(700, 2500)
                banner = True
                cookies_after_rej = max(0, tot_c - random.randint(0, 2))

            elif pet == "firefox_etp_strict":
                # Stronger blocking (70-85%)
                reduction = random.uniform(0.70, 0.85)
                td = max(0, int(base_td * (1 - reduction)))
                tc = max(0, int(base_tc * (1 - reduction)))
                tot_c = max(tc, base_tot_c - int(base_tc * reduction * 0.8))
                tot_r = max(5, base_req - int(base_req * reduction * 0.35))
                load_ms = random.randint(600, 2200)
                banner = True
                cookies_after_rej = max(0, tot_c - random.randint(0, 2))

            elif pet == "brave_shields":
                # Strong blocking (80-95%)
                reduction = random.uniform(0.80, 0.95)
                td = max(0, int(base_td * (1 - reduction)))
                tc = max(0, int(base_tc * (1 - reduction)))
                tot_c = max(tc, base_tot_c - int(base_tc * reduction * 0.9))
                tot_r = max(5, base_req - int(base_req * reduction * 0.4))
                load_ms = random.randint(500, 1800)
                banner = random.random() < 0.6  # Brave may block some banners
                cookies_after_rej = max(0, tc)

            elif pet == "consent_o_matic":
                # Does NOT block network trackers — auto-rejects consent
                td = base_td  # Same tracker domains
                tc = base_tc  # Same tracker cookies initially
                # But after auto-reject, cookies drop
                tot_c = max(0, base_tot_c - random.randint(2, max(3, base_tc)))
                tot_r = base_req  # Same requests
                load_ms = random.randint(900, 3500)  # Slightly slower (interaction)
                banner = True  # Always detects banner to interact with it
                cookies_after_rej = max(0, tot_c - random.randint(2, max(3, base_tc // 2)))

            else:
                continue

            rows.append({
                "domain": domain,
                "pet_name": pet,
                "tracker_domains": td,
                "tracker_cookies": tc,
                "total_cookies": tot_c,
                "total_requests": tot_r,
                "page_load_time_ms": load_ms,
                "consent_banner_detected": banner,
                "cookies_after_reject": cookies_after_rej,
            })

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} rows ({len(domains)} sites × {len(PETS)} PETs)")
    print(f"Saved to {out_csv}")

    # Print summary statistics
    _print_summary(rows, domains)


def _print_summary(rows: list[dict], domains: list[str]) -> None:
    """Print mock data summary."""
    print(f"\n{'=' * 70}")
    print("MOCK PET EFFECTIVENESS DATA SUMMARY")
    print(f"{'=' * 70}")

    print(f"\n{'PET':<25s} {'Avg Trackers':>13s} {'Avg Cookies':>12s} {'Avg Requests':>13s}")
    print("-" * 65)

    for pet in PETS:
        pet_rows = [r for r in rows if r["pet_name"] == pet]
        avg_td = sum(r["tracker_domains"] for r in pet_rows) / len(pet_rows)
        avg_tc = sum(r["total_cookies"] for r in pet_rows) / len(pet_rows)
        avg_req = sum(r["total_requests"] for r in pet_rows) / len(pet_rows)
        print(f"  {pet:<23s} {avg_td:>13.1f} {avg_tc:>12.1f} {avg_req:>13.1f}")

    print(f"\nDomains: {len(domains)}")
    print(f"Total rows: {len(rows)}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    generate_mock_pets_effectiveness()
