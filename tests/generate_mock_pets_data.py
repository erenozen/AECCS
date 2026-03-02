"""
Generate mock PET evaluation data for testing Phase 3 Modules 2-4.

Produces ``data/mock/processed/pets_effectiveness.csv`` with realistic patterns:
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

import argparse
import csv
import json
import random
from pathlib import Path

from config import (
    PET_EFFECTIVENESS_FIELDS,
    build_provenance,
    generate_run_id,
    get_dataset_layout,
    infer_common_field,
)

LAYOUT = get_dataset_layout("mock")
PROCESSED_DIR = LAYOUT.processed_dir
RAW_DIR = LAYOUT.raw_dir


PETS = [
    "baseline",
    "ublock_origin",
    "privacy_badger",
    "firefox_etp_standard",
    "firefox_etp_strict",
    "brave_shields",
    "consent_o_matic",
]


def _get_sites() -> list[dict[str, str]]:
    """Get successful mock sites and their categories from raw data."""
    sites: list[dict[str, str]] = []
    raw = Path(RAW_DIR)
    for f in sorted(raw.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("success"):
                sites.append(
                    {
                        "domain": data.get("domain", f.stem),
                        "category": data.get("category", ""),
                    }
                )
        except Exception:
            continue
    return sites


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


def generate_mock_pets_effectiveness(run_id: str | None = None) -> str:
    """Generate pets_effectiveness.csv with realistic per-PET results."""
    random.seed(42)
    sites = _get_sites()
    raw_docs: list[dict] = []
    for path in sorted(Path(RAW_DIR).glob("*.json")):
        try:
            raw_docs.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    effective_run_id = run_id or infer_common_field(raw_docs, "run_id") or generate_run_id("mock-pets")
    site_list_source = infer_common_field(raw_docs, "site_list_source") or "tests/generate_mock_data.py"

    if not sites:
        print("No crawled domains found in raw data. Run generate_mock_data first.")
        return

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = PROCESSED_DIR / "pets_effectiveness.csv"

    rows: list[dict] = []

    for site in sites:
        domain = site["domain"]
        category = site["category"]
        base_td, base_tc, base_tot_c, base_req = _baseline_trackers(domain)
        base_total_tp = base_td + random.randint(0, 2)

        for pet in PETS:
            if pet == "baseline":
                td = base_td
                tc = base_tc
                tot_c = base_tot_c
                tot_r = base_req
                total_tp = base_total_tp
                blocked_requests = 0
                load_ms = random.randint(800, 3000)
                banner = True

            elif pet == "ublock_origin":
                # Near-complete blocking
                td = random.randint(0, max(1, base_td // 8))
                tc = random.randint(0, max(1, base_tc // 8))
                tot_c = max(tc, base_tot_c - random.randint(base_tc // 2, base_tc))
                tot_r = max(5, base_req - random.randint(base_req // 3, base_req // 2))
                total_tp = td + random.randint(0, 1)
                blocked_requests = max(0, base_req - tot_r)
                load_ms = random.randint(500, 1800)
                banner = random.random() < 0.3  # uBlock may hide banners

            elif pet == "privacy_badger":
                # Moderate blocking (60-80%)
                reduction = random.uniform(0.60, 0.80)
                td = max(0, int(base_td * (1 - reduction)))
                tc = max(0, int(base_tc * (1 - reduction)))
                tot_c = max(tc, base_tot_c - int(base_tc * reduction * 0.7))
                tot_r = max(5, base_req - int(base_req * reduction * 0.3))
                total_tp = td + random.randint(0, 2)
                blocked_requests = max(0, base_req - tot_r)
                load_ms = random.randint(600, 2200)
                banner = True

            elif pet == "firefox_etp_standard":
                # Significant blocking (50-70%)
                reduction = random.uniform(0.50, 0.70)
                td = max(0, int(base_td * (1 - reduction)))
                tc = max(0, int(base_tc * (1 - reduction)))
                tot_c = max(tc, base_tot_c - int(base_tc * reduction * 0.6))
                tot_r = max(5, base_req - int(base_req * reduction * 0.25))
                total_tp = td + random.randint(0, 2)
                blocked_requests = max(0, base_req - tot_r)
                load_ms = random.randint(700, 2500)
                banner = True

            elif pet == "firefox_etp_strict":
                # Stronger blocking (70-85%)
                reduction = random.uniform(0.70, 0.85)
                td = max(0, int(base_td * (1 - reduction)))
                tc = max(0, int(base_tc * (1 - reduction)))
                tot_c = max(tc, base_tot_c - int(base_tc * reduction * 0.8))
                tot_r = max(5, base_req - int(base_req * reduction * 0.35))
                total_tp = td + random.randint(0, 1)
                blocked_requests = max(0, base_req - tot_r)
                load_ms = random.randint(600, 2200)
                banner = True

            elif pet == "brave_shields":
                # Strong blocking (80-95%)
                reduction = random.uniform(0.80, 0.95)
                td = max(0, int(base_td * (1 - reduction)))
                tc = max(0, int(base_tc * (1 - reduction)))
                tot_c = max(tc, base_tot_c - int(base_tc * reduction * 0.9))
                tot_r = max(5, base_req - int(base_req * reduction * 0.4))
                total_tp = td + random.randint(0, 1)
                blocked_requests = max(0, base_req - tot_r)
                load_ms = random.randint(500, 1800)
                banner = random.random() < 0.6  # Brave may block some banners

            elif pet == "consent_o_matic":
                # Does NOT block network trackers — auto-rejects consent
                td = base_td  # Same tracker domains
                tc = base_tc  # Same tracker cookies initially
                # But after auto-reject, cookies drop
                tot_c = max(0, base_tot_c - random.randint(2, max(3, base_tc)))
                tot_r = base_req  # Same requests
                total_tp = base_total_tp
                blocked_requests = 0
                load_ms = random.randint(900, 3500)  # Slightly slower (interaction)
                banner = True  # Always detects banner to interact with it

            else:
                continue

            rows.append({
                "domain": domain,
                "source_mode": "mock",
                "run_id": effective_run_id,
                "category": category,
                "pet_name": pet,
                "measurement_mode": "simulated" if pet == "brave_shields" else "real",
                "browser_name": "chromium" if "firefox" not in pet else "firefox",
                "browser_version": "synthetic",
                "extension_name": pet if pet in ("ublock_origin", "privacy_badger", "consent_o_matic") else "",
                "extension_version": "synthetic" if pet in ("ublock_origin", "privacy_badger", "consent_o_matic") else "",
                "extension_path": f"data/pet_extensions/{pet}" if pet in ("ublock_origin", "privacy_badger", "consent_o_matic") else "",
                "extension_enabled": pet in ("ublock_origin", "privacy_badger", "consent_o_matic"),
                "consent_banner_detected": banner,
                "page_load_time_ms": load_ms,
                "total_cookies": tot_c,
                "tracker_domains": td,
                "tracker_cookies": tc,
                "total_third_party_domains": total_tp,
                "total_requests": tot_r,
                "blocked_requests": blocked_requests,
                "blocked_tracker_requests": int(
                    blocked_requests * random.uniform(0.6, 0.95)
                ) if blocked_requests > 0 else 0,
                "success": True,
                "error": "",
            })

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PET_EFFECTIVENESS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    out_json = PROCESSED_DIR / "pets_raw_results.json"
    out_json.write_text(
        json.dumps(
            {
                **build_provenance(
                    source_mode="mock",
                    run_id=effective_run_id,
                    site_list_source=site_list_source,
                ),
                "results": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Generated {len(rows)} rows ({len(sites)} sites × {len(PETS)} PETs)")
    print(f"Saved to {out_csv}")

    # Print summary statistics
    _print_summary(rows, [site["domain"] for site in sites])
    return effective_run_id


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
    parser = argparse.ArgumentParser(description="Generate AECCS mock PET outputs")
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional shared run identifier for the generated mock PET artifacts",
    )
    args = parser.parse_args()
    generate_mock_pets_effectiveness(run_id=args.run_id)
