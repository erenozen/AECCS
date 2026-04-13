from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVACY_POLICY = ROOT / "docs" / "privacy-policy.html"
STORE_LISTING = ROOT / "docs" / "extension_store_listing.md"
STORE_LISTING_CHROME = ROOT / "docs" / "extension_store_listing_chrome.md"
STORE_LISTING_FIREFOX = ROOT / "docs" / "extension_store_listing_firefox.md"
REVIEWER_NOTES = ROOT / "docs" / "extension_reviewer_notes.md"
RELEASE_CHECKLIST = ROOT / "docs" / "extension_release_checklist.md"
PACKAGE_SCRIPT = ROOT / "scripts" / "package_extension_release.py"
MANIFEST = ROOT / "extension" / "manifest.json"
POPUP = ROOT / "extension" / "popup" / "popup.js"
PUBLIC_PRIVACY_POLICY_URL = "https://erenozen.github.io/AECCS/privacy-policy.html"
FIREFOX_BACKGROUND_SCRIPTS = [
    "lib/browser-polyfill.js",
    "lib/study-snapshot.js",
    "lib/tracker-data.js",
    "lib/tracker-index.js",
    "lib/domain-utils.js",
    "lib/classifier.js",
    "lib/scorer.js",
    "background/service-worker.js",
]


def test_privacy_policy_matches_release_behavior() -> None:
    text = PRIVACY_POLICY.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "does not collect, sell, store" in lowered
    assert "transmit personal data" in lowered
    assert "browser.cookies" in text
    assert "<code>activeTab</code>" in text
    assert "<code>scripting</code>" in text
    assert "&lt;all_urls&gt;" in text
    assert "zero network requests" in text.lower()
    assert "No Remote Code" in text
    assert "build_extension_study_snapshot.py" in text
    assert "build_extension_tracker_index.py" in text
    assert "https://github.com/erenozen/AECCS" in text
    assert "https://github.com/erenozen/AECCS/issues" in text
    assert PUBLIC_PRIVACY_POLICY_URL in text


def test_release_docs_cover_store_and_reviewer_workflows() -> None:
    source_text = STORE_LISTING.read_text(encoding="utf-8")
    chrome_text = STORE_LISTING_CHROME.read_text(encoding="utf-8")
    firefox_text = STORE_LISTING_FIREFOX.read_text(encoding="utf-8")
    reviewer_text = REVIEWER_NOTES.read_text(encoding="utf-8")
    checklist_text = RELEASE_CHECKLIST.read_text(encoding="utf-8")

    assert "Passive, research-grounded GDPR cookie-consent auditor" in source_text

    assert "Chrome Web Store" in chrome_text
    assert "Single Purpose" in chrome_text
    assert "no remote code" in chrome_text.lower()
    assert PUBLIC_PRIVACY_POLICY_URL in chrome_text

    assert "Firefox Add-ons" in firefox_text
    assert PUBLIC_PRIVACY_POLICY_URL in firefox_text
    assert "listed add-on" in checklist_text
    assert "Submit Firefox First" in checklist_text
    assert "Submit Chrome Immediately After" in checklist_text
    assert "440x280" in checklist_text
    assert "generated static assets" in firefox_text.lower()

    assert "`cookies`" in reviewer_text
    assert "`activeTab`" in reviewer_text
    assert "`scripting`" in reviewer_text
    assert "`<all_urls>`" in reviewer_text
    assert "study-snapshot.js" in reviewer_text
    assert "tracker-index.js" in reviewer_text
    assert "background.scripts" in reviewer_text
    assert 'data_collection_permissions.required = ["none"]' in reviewer_text
    assert PUBLIC_PRIVACY_POLICY_URL in reviewer_text

    assert "deferred publishing" in checklist_text.lower()
    assert "package_extension_release.py" in checklist_text
    assert PUBLIC_PRIVACY_POLICY_URL in checklist_text


def test_release_packaging_script_builds_expected_archives(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = manifest["version"]

    subprocess.run(
        [
            sys.executable,
            str(PACKAGE_SCRIPT),
            "--skip-generate",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=True,
    )

    chrome_zip = tmp_path / f"aeccs-extension-chrome-{version}.zip"
    firefox_zip = tmp_path / f"aeccs-extension-firefox-{version}.zip"
    reviewer_zip = tmp_path / f"aeccs-extension-reviewer-source-{version}.zip"
    release_manifest = tmp_path / f"aeccs-extension-release-{version}.json"

    assert chrome_zip.exists()
    assert firefox_zip.exists()
    assert reviewer_zip.exists()
    assert release_manifest.exists()

    manifest_payload = json.loads(release_manifest.read_text(encoding="utf-8"))
    assert manifest_payload["version"] == version
    assert manifest_payload["chromePackage"] == chrome_zip.name
    assert manifest_payload["firefoxPackage"] == firefox_zip.name
    assert manifest_payload["reviewerSourcePackage"] == reviewer_zip.name
    assert manifest_payload["privacyPolicyUrl"] == PUBLIC_PRIVACY_POLICY_URL

    with zipfile.ZipFile(chrome_zip) as zf:
        names = set(zf.namelist())
        chrome_manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert "manifest.json" in names
    assert "popup/popup.js" in names
    assert "background/service-worker.js" in names
    assert "icons/icon-128.png" in names
    assert chrome_manifest["background"]["service_worker"] == "background/service-worker.js"
    assert "scripts" not in chrome_manifest["background"]

    with zipfile.ZipFile(reviewer_zip) as zf:
        names = set(zf.namelist())
    assert "extension/manifest.json" in names
    assert "docs/privacy-policy.html" in names
    assert "docs/extension_reviewer_notes.md" in names
    assert "scripts/build_extension_study_snapshot.py" in names
    assert "scripts/build_extension_tracker_index.py" in names

    with zipfile.ZipFile(firefox_zip) as zf:
        firefox_manifest = json.loads(zf.read("manifest.json").decode("utf-8"))

    assert firefox_manifest["background"]["service_worker"] == "background/service-worker.js"
    assert firefox_manifest["background"]["scripts"] == FIREFOX_BACKGROUND_SCRIPTS
    assert firefox_manifest["browser_specific_settings"]["gecko"]["data_collection_permissions"] == {
        "required": ["none"]
    }


def test_source_manifest_declares_no_firefox_data_collection() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["browser_specific_settings"]["gecko"]["data_collection_permissions"] == {
        "required": ["none"]
    }


def test_popup_renderer_no_longer_uses_runtime_innerhtml() -> None:
    popup_text = POPUP.read_text(encoding="utf-8")
    assert ".innerHTML" not in popup_text
