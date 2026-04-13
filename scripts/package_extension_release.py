"""Package the AECCS browser extension for Chrome and Firefox release."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = ROOT / "extension"
MANIFEST_PATH = EXTENSION_DIR / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "extension-release"

REVIEWER_SOURCE_FILES = [
    "extension",
    "docs/privacy-policy.html",
    "docs/extension_store_listing.md",
    "docs/extension_store_listing_chrome.md",
    "docs/extension_store_listing_firefox.md",
    "docs/extension_reviewer_notes.md",
    "docs/extension_release_checklist.md",
    "scripts/build_extension_study_snapshot.py",
    "scripts/build_extension_tracker_index.py",
    "scripts/package_extension_release.py",
]


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def write_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def bump_version(version: str | None) -> str:
    manifest = load_manifest()
    if version:
        manifest["version"] = version
        write_manifest(manifest)
    return manifest["version"]


def run_generator(script_name: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / script_name)], cwd=ROOT, check=True)


def add_tree_to_zip(zf: zipfile.ZipFile, base_dir: Path, root_in_zip: Path | None = None) -> None:
    root_in_zip = root_in_zip or Path()
    for path in sorted(base_dir.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(base_dir)
        zf.write(path, (root_in_zip / relative).as_posix())


def build_extension_zip(output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        add_tree_to_zip(zf, EXTENSION_DIR)


def build_reviewer_source_zip(output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in REVIEWER_SOURCE_FILES:
            path = ROOT / item
            if path.is_dir():
                add_tree_to_zip(zf, path, Path(item))
            else:
                zf.write(path, item)


def build_release_manifest(output_path: Path, version: str, files: dict[str, str]) -> None:
    payload = {
        "name": "AECCS Cookie Compliance Checker",
        "version": version,
        "chromePackage": files["chrome"],
        "firefoxPackage": files["firefox"],
        "reviewerSourcePackage": files["reviewer"],
        "homepageUrl": "https://github.com/erenozen/AECCS",
        "supportUrl": "https://github.com/erenozen/AECCS/issues",
        "privacyPolicyPath": "docs/privacy-policy.html",
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Optional version to write into extension/manifest.json before packaging.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory to place release archives.")
    parser.add_argument("--skip-generate", action="store_true", help="Skip regenerating study-snapshot.js and tracker-index.js.")
    args = parser.parse_args()

    version = bump_version(args.version)

    if not args.skip_generate:
        run_generator("build_extension_study_snapshot.py")
        run_generator("build_extension_tracker_index.py")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    chrome_zip = args.output_dir / f"aeccs-extension-chrome-{version}.zip"
    firefox_zip = args.output_dir / f"aeccs-extension-firefox-{version}.zip"
    reviewer_zip = args.output_dir / f"aeccs-extension-reviewer-source-{version}.zip"
    manifest_json = args.output_dir / f"aeccs-extension-release-{version}.json"

    build_extension_zip(chrome_zip)
    shutil.copyfile(chrome_zip, firefox_zip)
    build_reviewer_source_zip(reviewer_zip)
    build_release_manifest(
        manifest_json,
        version,
        {
            "chrome": chrome_zip.name,
            "firefox": firefox_zip.name,
            "reviewer": reviewer_zip.name,
        },
    )

    print(f"[OK] Chrome package: {chrome_zip}")
    print(f"[OK] Firefox package: {firefox_zip}")
    print(f"[OK] Reviewer/source package: {reviewer_zip}")
    print(f"[OK] Release manifest: {manifest_json}")


if __name__ == "__main__":
    main()
