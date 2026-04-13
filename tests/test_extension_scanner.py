from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "extension_scanner"
TRACKER_DATA = ROOT / "extension" / "lib" / "tracker-data.js"
SCANNER = ROOT / "extension" / "content" / "consent-scanner.js"
SCORER = ROOT / "extension" / "lib" / "scorer.js"


def _scan_fixture(page, fixture_name: str) -> dict:
    page.goto((FIXTURES / fixture_name).as_uri())
    page.add_script_tag(path=str(TRACKER_DATA))
    page.add_script_tag(path=str(SCANNER))
    return page.evaluate(
        """async () => {
            return await AECCSConsentScanner.scanPageWithRetries({
                attempts: 5,
                delayMs: 120
            });
        }"""
    )


def test_consent_scanner_detects_nested_reddit_like_buttons() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "reddit_like.html")
        browser.close()

    assert result["bannerFound"] is True
    assert result["bannerSelector"] == "#cookie-consent-shell"
    assert result["hasAcceptButton"] is True
    assert result["acceptButtonText"] == "Accept All"
    assert result["hasRejectButton"] is True
    assert result["rejectButtonText"] == "Reject Optional Cookies"
    assert result["acceptClicksRequired"] == 1
    assert result["rejectClicksRequired"] == 1


def test_consent_scanner_detects_direct_accept_and_reject_buttons() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "direct_buttons.html")
        browser.close()

    assert result["bannerFound"] is True
    assert result["hasAcceptButton"] is True
    assert result["hasRejectButton"] is True
    assert result["acceptButtonText"] == "Accept All"
    assert result["rejectButtonText"] == "Reject All"
    assert result["acceptClicksRequired"] == 1
    assert result["rejectClicksRequired"] == 1


def test_consent_scanner_detects_settings_path_without_direct_reject() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "settings_path.html")
        browser.close()

    assert result["bannerFound"] is True
    assert result["hasAcceptButton"] is True
    assert result["hasRejectButton"] is False
    assert result["hasSettingsButton"] is True
    assert result["settingsButtonText"] == "Manage Preferences"
    assert result["rejectClicksRequired"] == 2


def test_consent_scanner_reads_value_and_title_labels() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "aria_value_title.html")
        browser.close()

    assert result["hasAcceptButton"] is True
    assert result["acceptButtonText"] == "Accept All"
    assert result["hasRejectButton"] is True
    assert result["rejectButtonText"] == "Reject All"


def test_consent_scanner_retries_until_buttons_render() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "delayed_buttons.html")
        browser.close()

    assert result["bannerFound"] is True
    assert result["hasAcceptButton"] is True
    assert result["hasRejectButton"] is True


def test_scorer_distinguishes_direct_and_settings_reject_paths() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("data:text/html,<html><body></body></html>")
        page.add_script_tag(path=str(TRACKER_DATA))
        page.add_script_tag(path=str(SCORER))

        scores = page.evaluate(
            """() => {
                const direct = Scorer.computeComplianceScore([], {
                    bannerFound: true,
                    hasAcceptButton: true,
                    hasRejectButton: true,
                    hasSettingsButton: false,
                    acceptClicksRequired: 1,
                    rejectClicksRequired: 1,
                    darkPatterns: { count: 0, detected: [] },
                    transparency: {}
                });

                const settingsPath = Scorer.computeComplianceScore([], {
                    bannerFound: true,
                    hasAcceptButton: true,
                    hasRejectButton: false,
                    hasSettingsButton: true,
                    acceptClicksRequired: 1,
                    rejectClicksRequired: 2,
                    darkPatterns: { count: 0, detected: [] },
                    transparency: {}
                });

                return { direct, settingsPath };
            }"""
        )
        browser.close()

    assert scores["direct"]["criteria"]["reject_option_available"]["score"] == 100
    assert scores["direct"]["criteria"]["equal_accept_reject_effort"]["score"] == 100
    assert scores["settingsPath"]["criteria"]["reject_option_available"]["score"] == 50
    assert scores["settingsPath"]["criteria"]["equal_accept_reject_effort"]["score"] == 50
