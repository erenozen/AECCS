"""
Merge multiple batch directories into a single combined dataset.

Usage:
    python -m scripts.merge_batches --batches real_0 real_1 real_2 ... --output real_combined
    python -m scripts.merge_batches --batch-range 0 9 --output real_combined
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd

from config import DATA_DIR, get_dataset_layout, infer_common_value, utc_now_iso


def _rewrite_source_mode(payload: object, output_mode: str) -> object:
    """Rewrite the top-level source mode for merged artifacts."""
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["source_mode"] = output_mode
    return payload


def _reset_combined_outputs(output_mode: str) -> None:
    """Rebuild combined data/report directories from scratch."""
    out_layout = get_dataset_layout(output_mode)
    if out_layout.data_root.exists():
        shutil.rmtree(out_layout.data_root)
    if out_layout.report_dir.exists():
        shutil.rmtree(out_layout.report_dir)
    combined_csv = DATA_DIR / "websites_combined.csv"
    if combined_csv.exists():
        combined_csv.unlink()


def merge_batches(
    batch_modes: list[str],
    output_mode: str,
    website_csvs: list[Path] | None = None,
) -> None:
    """Merge per-batch data directories into a single combined dataset."""
    _reset_combined_outputs(output_mode)
    out_layout = get_dataset_layout(output_mode)
    out_layout.raw_dir.mkdir(parents=True, exist_ok=True)
    out_layout.processed_dir.mkdir(parents=True, exist_ok=True)
    out_layout.screenshots_dir.mkdir(parents=True, exist_ok=True)
    out_layout.banners_dir.mkdir(parents=True, exist_ok=True)

    all_scores: list[pd.DataFrame] = []
    all_pets: list[pd.DataFrame] = []
    all_pets_raw: list[dict] = []
    pets_run_ids: list[object] = []
    pets_site_sources: list[object] = []
    raw_count = 0
    processed_count = 0

    for batch_mode in batch_modes:
        batch_layout = get_dataset_layout(batch_mode)

        # Copy raw JSONs
        if batch_layout.raw_dir.exists():
            for json_file in batch_layout.raw_dir.glob("*.json"):
                dest = out_layout.raw_dir / json_file.name
                data = json.loads(json_file.read_text(encoding="utf-8"))
                data = _rewrite_source_mode(data, output_mode)
                dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
                raw_count += 1

        # Copy screenshots
        if batch_layout.screenshots_dir.exists():
            for img in batch_layout.screenshots_dir.glob("*"):
                dest = out_layout.screenshots_dir / img.name
                shutil.copy2(img, dest)

        # Copy banners
        if batch_layout.banners_dir.exists():
            for html in batch_layout.banners_dir.glob("*"):
                dest = out_layout.banners_dir / html.name
                shutil.copy2(html, dest)

        # Copy processed per-site files, rewriting source_mode to output_mode
        if batch_layout.processed_dir.exists():
            for suffix in ("_classified.json", "_dark_patterns.json", "_score.json"):
                for f in batch_layout.processed_dir.glob(f"*{suffix}"):
                    dest = out_layout.processed_dir / f.name
                    data = json.loads(f.read_text(encoding="utf-8"))
                    data = _rewrite_source_mode(data, output_mode)
                    dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    processed_count += 1

            # Collect compliance scores
            scores_csv = batch_layout.processed_dir / "compliance_scores.csv"
            if scores_csv.exists():
                all_scores.append(pd.read_csv(scores_csv))

            # Collect PET effectiveness data
            pets_csv = batch_layout.processed_dir / "pets_effectiveness.csv"
            if pets_csv.exists():
                all_pets.append(pd.read_csv(pets_csv))

            # Collect PET raw results
            pets_json = batch_layout.processed_dir / "pets_raw_results.json"
            if pets_json.exists():
                data = json.loads(pets_json.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for entry in data:
                        rewritten = _rewrite_source_mode(entry, output_mode)
                        if isinstance(rewritten, dict):
                            all_pets_raw.append(rewritten)
                elif isinstance(data, dict) and "results" in data:
                    pets_run_ids.append(data.get("run_id"))
                    pets_site_sources.append(data.get("site_list_source"))
                    for entry in data["results"]:
                        rewritten = _rewrite_source_mode(entry, output_mode)
                        if isinstance(rewritten, dict):
                            all_pets_raw.append(rewritten)

    # Merge compliance scores (deduplicate by domain, keep last)
    if all_scores:
        combined_scores = pd.concat(all_scores, ignore_index=True)
        combined_scores = combined_scores.drop_duplicates(subset="domain", keep="last")
        combined_scores["source_mode"] = output_mode
        out_csv = out_layout.processed_dir / "compliance_scores.csv"
        combined_scores.to_csv(out_csv, index=False)
        print(f"Merged compliance_scores.csv: {len(combined_scores)} sites")

    # Merge PET effectiveness (deduplicate by domain + pet_name, keep last)
    if all_pets:
        combined_pets = pd.concat(all_pets, ignore_index=True)
        dedup_cols = ["domain", "pet_name"] if "pet_name" in combined_pets.columns else ["domain"]
        combined_pets = combined_pets.drop_duplicates(subset=dedup_cols, keep="last")
        combined_pets["source_mode"] = output_mode
        out_pets_csv = out_layout.processed_dir / "pets_effectiveness.csv"
        combined_pets.to_csv(out_pets_csv, index=False)
        print(f"Merged pets_effectiveness.csv: {len(combined_pets)} rows")

    # Merge PET raw results
    if all_pets_raw:
        out_pets_json = out_layout.processed_dir / "pets_raw_results.json"
        out_pets_json.write_text(
            json.dumps(
                {
                    "source_mode": output_mode,
                    "run_id": infer_common_value(pets_run_ids),
                    "site_list_source": infer_common_value(pets_site_sources),
                    "generated_at": utc_now_iso(),
                    "results": all_pets_raw,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Merged pets_raw_results.json: {len(all_pets_raw)} entries")

    # Merge website CSVs into a combined list
    if website_csvs:
        all_websites: list[pd.DataFrame] = []
        for csv_path in website_csvs:
            if csv_path.exists():
                all_websites.append(pd.read_csv(csv_path))
        if all_websites:
            combined_websites = pd.concat(all_websites, ignore_index=True)
            combined_websites = combined_websites.drop_duplicates(
                subset="domain", keep="first"
            )
            combined_websites["rank"] = range(1, len(combined_websites) + 1)
            out_websites = DATA_DIR / "websites_combined.csv"
            combined_websites.to_csv(out_websites, index=False)
            print(f"Combined website list: {len(combined_websites)} sites → {out_websites}")

    print(f"\nMerge complete:")
    print(f"  Raw JSONs copied: {raw_count}")
    print(f"  Processed files copied: {processed_count}")
    print(f"  Output: {out_layout.data_root}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge AECCS batch data directories")
    parser.add_argument(
        "--batches",
        nargs="+",
        default=None,
        help="Batch source modes to merge (e.g., real_0 real_1 real_2)",
    )
    parser.add_argument(
        "--batch-range",
        nargs=2,
        type=int,
        default=None,
        metavar=("START", "END"),
        help="Range of batch numbers (e.g., 0 9 for real_0 through real_9)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="real_combined",
        help="Output source mode name (default: real_combined)",
    )
    parser.add_argument(
        "--website-csvs",
        nargs="+",
        default=None,
        help="Website CSV files to merge into a combined list",
    )
    args = parser.parse_args()

    if args.batch_range:
        start, end = args.batch_range
        batch_modes = [f"real_{i}" for i in range(start, end + 1)]
    elif args.batches:
        batch_modes = args.batches
    else:
        parser.error("Provide either --batches or --batch-range")

    csv_paths = None
    if args.website_csvs:
        csv_paths = [Path(p) for p in args.website_csvs]
    else:
        # Auto-detect: websites_1.csv through websites_10.csv
        csv_paths = [DATA_DIR / f"websites_{i}.csv" for i in range(1, 11)]
        csv_paths = [p for p in csv_paths if p.exists()]

    merge_batches(batch_modes, args.output, csv_paths)


if __name__ == "__main__":
    main()
