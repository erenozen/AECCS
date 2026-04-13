from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "extension_scanner"
TRACKER_DATA = ROOT / "extension" / "lib" / "tracker-data.js"
SCANNER = ROOT / "extension" / "content" / "consent-scanner.js"
SCORER = ROOT / "extension" / "lib" / "scorer.js"
POPUP = ROOT / "extension" / "popup" / "popup.js"


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


def _render_popup(page, result: dict) -> None:
    page.set_content(
        """
        <!DOCTYPE html>
        <html>
        <body>
          <div id="loading"></div>
          <div id="errorState" class="hidden"><span id="errorMsg"></span></div>
          <div id="results" class="hidden">
            <div id="siteDomain"></div>
            <div id="govAlert" class="hidden"></div>
            <div id="gradeBadge"></div>
            <div id="gradeLetter"></div>
            <div id="scoreValue"></div>
            <div id="cookieBar"></div>
            <div id="cookieCounts"></div>
            <div id="cookieMeta"></div>
            <div id="trackerSection"></div>
            <div id="trackerList"></div>
            <div id="consentInfo"></div>
            <div id="cmpInfo" class="hidden"></div>
            <section id="buttonCompSection" class="hidden"><div id="buttonComparison"></div></section>
            <section id="darkPatternSection"><div id="darkPatternDetails"></div></section>
            <table><tbody id="criteriaBody"></tbody></table>
            <section id="petSection" class="hidden"><div id="petList"></div></section>
          </div>
        </body>
        </html>
        """
    )
    page.evaluate(
        """data => {
            window.browser = {
                tabs: {
                    query: async () => [{ id: 1, url: "https://eksisozluk.com" }]
                },
                runtime: {
                    sendMessage: async () => data
                }
            };
        }""",
        result,
    )
    page.add_script_tag(path=str(TRACKER_DATA))
    page.add_script_tag(path=str(POPUP))


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
    assert result["buttonComparison"]["available"] is True
    assert result["buttonComparison"]["rejectSource"] == "settings"
    assert result["buttonComparison"]["reject"]["text"] == "Manage Preferences"


def test_consent_scanner_detects_turkish_accept_and_settings_path() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "eksisozluk_like.html")
        browser.close()

    assert result["bannerFound"] is True
    assert result["hasAcceptButton"] is True
    assert result["acceptButtonText"] == "İzin ver"
    assert result["hasRejectButton"] is False
    assert result["hasSettingsButton"] is True
    assert result["settingsButtonText"] == "Seçenekleri yönetin"
    assert result["acceptClicksRequired"] == 1
    assert result["rejectClicksRequired"] == 2
    assert result["buttonComparison"]["available"] is True
    assert result["buttonComparison"]["rejectSource"] == "settings"
    assert result["buttonComparison"]["reject"]["text"] == "Seçenekleri yönetin"
    assert "settings/preferences" in result["buttonComparison"]["issues"][0]


def test_consent_scanner_uses_painted_nested_button_styles() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "nested_visual_styles.html")
        browser.close()

    assert result["hasAcceptButton"] is True
    assert result["hasSettingsButton"] is True
    assert result["buttonComparison"]["available"] is True
    assert result["buttonComparison"]["rejectSource"] == "settings"

    accept = result["buttonComparison"]["accept"]
    reject = result["buttonComparison"]["reject"]

    assert accept["styleSource"] == "span.action-pill"
    assert reject["styleSource"] == "span.action-pill"
    assert accept["bgColor"] == "rgb(37, 99, 235)"
    assert reject["bgColor"] == "rgb(37, 99, 235)"
    assert accept["color"] == "rgb(255, 255, 255)"
    assert reject["color"] == "rgb(255, 255, 255)"
    assert "Reject is styled as a plain link, not a button" not in result["buttonComparison"]["issues"]


def test_consent_scanner_uses_split_painted_button_styles() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "split_visual_styles.html")
        browser.close()

    assert result["hasAcceptButton"] is True
    assert result["hasSettingsButton"] is True
    assert result["buttonComparison"]["available"] is True
    assert result["buttonComparison"]["rejectSource"] == "settings"

    accept = result["buttonComparison"]["accept"]
    reject = result["buttonComparison"]["reject"]

    assert accept["styleSource"] == "span.action-bg"
    assert reject["styleSource"] == "span.action-bg"
    assert accept["bgColor"] == "rgb(37, 99, 235)"
    assert reject["bgColor"] == "rgb(37, 99, 235)"
    assert accept["plainLinkLike"] is False
    assert reject["plainLinkLike"] is False
    assert "Reject is styled as a plain link, not a button" not in result["buttonComparison"]["issues"]


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


def test_popup_prefers_non_transparent_bg_color_over_background_shorthand() -> None:
    popup_result = {
        "isGovDomain": False,
        "score": {"grade": "C", "overall_score": 60, "criteria": {}},
        "categoryCounts": {},
        "totalCookies": 0,
        "thirdPartyCount": 0,
        "trackerCount": 0,
        "trackersByVendor": {},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": None,
            "bannerFound": True,
            "hasAcceptButton": True,
            "hasRejectButton": False,
            "hasSettingsButton": True,
            "acceptButtonText": "İzin ver",
            "rejectButtonText": None,
            "settingsButtonText": "Seçenekleri yönetin",
            "acceptClicksRequired": 1,
            "rejectClicksRequired": 2,
            "transparency": {},
            "darkPatterns": {"count": 0, "detected": []},
            "buttonComparison": {
                "available": True,
                "rejectSource": "settings",
                "issues": [],
                "accept": {
                    "text": "İzin ver",
                    "width": 196,
                    "height": 38,
                    "fontSize": 14,
                    "fontWeight": 400,
                    "background": "rgba(0, 0, 0, 0) none repeat scroll 0% 0% / auto padding-box border-box",
                    "bgColor": "rgb(37, 99, 235)",
                    "color": "rgb(255, 255, 255)",
                    "border": "0px none rgb(255, 255, 255)",
                    "borderRadius": "999px",
                    "boxShadow": "none",
                    "clicksRequired": 1,
                    "styleSource": "button",
                    "plainLinkLike": False,
                },
                "reject": {
                    "text": "Seçenekleri yönetin",
                    "width": 196,
                    "height": 38,
                    "fontSize": 14,
                    "fontWeight": 400,
                    "background": "rgba(0, 0, 0, 0) none repeat scroll 0% 0% / auto padding-box border-box",
                    "bgColor": "rgb(37, 99, 235)",
                    "color": "rgb(255, 255, 255)",
                    "border": "0px none rgb(255, 255, 255)",
                    "borderRadius": "999px",
                    "boxShadow": "none",
                    "clicksRequired": 2,
                    "styleSource": "button",
                    "plainLinkLike": False,
                },
                "settings": None,
            },
        },
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _render_popup(page, popup_result)
        page.wait_for_selector("#buttonComparison .btn-mock")
        styles = page.evaluate(
            """() => {
                return Array.from(document.querySelectorAll("#buttonComparison .btn-mock")).map(el => {
                    const style = getComputedStyle(el);
                    return {
                        backgroundColor: style.backgroundColor,
                        color: style.color,
                    };
                });
            }"""
        )
        browser.close()

    assert styles[0]["backgroundColor"] == "rgb(37, 99, 235)"
    assert styles[1]["backgroundColor"] == "rgb(37, 99, 235)"
    assert styles[0]["color"] == "rgb(255, 255, 255)"
    assert styles[1]["color"] == "rgb(255, 255, 255)"


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
