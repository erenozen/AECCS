from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "extension_scanner"
TRACKER_DATA = ROOT / "extension" / "lib" / "tracker-data.js"
SCANNER = ROOT / "extension" / "content" / "consent-scanner.js"
SCORER = ROOT / "extension" / "lib" / "scorer.js"
POPUP = ROOT / "extension" / "popup" / "popup.js"
POPUP_HTML = ROOT / "extension" / "popup" / "popup.html"


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
            <div id="govAlert" class="hidden"><div id="govNote"></div></div>
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
            <section id="petSection" class="hidden"><div id="petSubtitle"></div><div id="petList"></div></section>
          </div>
          <footer id="footerNote"></footer>
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


def test_consent_scanner_tracks_passive_parity_dark_patterns_for_direct_banner() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "direct_buttons.html")
        browser.close()

    assert result["darkPatterns"]["missingReject"]["detected"] is False
    assert result["darkPatterns"]["multiLayerRejection"]["detected"] is False
    assert "Missing reject option" not in result["darkPatterns"]["detected"]
    assert "Multi-layer rejection" not in result["darkPatterns"]["detected"]


def test_consent_scanner_tracks_passive_parity_dark_patterns_for_settings_path() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "settings_path.html")
        browser.close()

    assert result["darkPatterns"]["missingReject"]["detected"] is True
    assert result["darkPatterns"]["missingReject"]["description"] == "No reject button in consent banner"
    assert result["darkPatterns"]["multiLayerRejection"]["detected"] is True
    assert result["darkPatterns"]["multiLayerRejection"]["acceptClicks"] == 1
    assert result["darkPatterns"]["multiLayerRejection"]["rejectClicks"] == 2
    assert result["darkPatterns"]["multiLayerRejection"]["clickRatio"] == 2.0
    assert "Missing reject option" in result["darkPatterns"]["detected"]
    assert "Multi-layer rejection" in result["darkPatterns"]["detected"]


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


def test_consent_scanner_tracks_missing_reject_when_no_reject_path_exists() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "no_reject_banner.html")
        browser.close()

    assert result["bannerFound"] is True
    assert result["hasAcceptButton"] is True
    assert result["hasRejectButton"] is False
    assert result["hasSettingsButton"] is False
    assert result["rejectClicksRequired"] == 999
    assert result["darkPatterns"]["missingReject"]["detected"] is True
    assert result["darkPatterns"]["multiLayerRejection"]["detected"] is True
    assert "Missing reject option" in result["darkPatterns"]["detected"]


def test_consent_scanner_keeps_no_banner_pages_at_zero_dark_patterns() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("<!DOCTYPE html><html><body><main>No consent banner here.</main></body></html>")
        page.add_script_tag(path=str(TRACKER_DATA))
        page.add_script_tag(path=str(SCANNER))
        result = page.evaluate(
            """async () => {
                return await AECCSConsentScanner.scanPageWithRetries({
                    attempts: 2,
                    delayMs: 20
                });
            }"""
        )
        browser.close()

    assert result["bannerFound"] is False
    assert result["darkPatterns"]["count"] == 0
    assert result["darkPatterns"]["detected"] == []
    assert result["darkPatterns"]["missingReject"]["detected"] is False
    assert result["darkPatterns"]["multiLayerRejection"]["detected"] is False


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


def test_popup_renders_updated_study_snapshot_copy_and_pet_cards() -> None:
    popup_result = {
        "isGovDomain": True,
        "studyMetadata": {
            "sampleSize": 100,
            "successfulCrawls": 97,
            "snapshotDateLabel": "March 1, 2026",
        },
        "score": {"grade": "D", "overall_score": 45.1, "criteria": {}},
        "categoryCounts": {},
        "totalCookies": 0,
        "thirdPartyCount": 0,
        "trackerCount": 0,
        "trackersByVendor": {},
        "cmpStats": {
            "avgScore": 45.1,
            "sampleSize": 26,
            "rejectRate": 0.615,
            "petScore": 33.4,
        },
        "petRecommendations": [
            {
                "name": "Brave Shields",
                "type": "browser",
                "description": "Built-in browser protection with the best average tracker reduction in the study.",
                "studyTrackerReductionPct": 14.7,
                "studyLabel": "+14.7% avg tracker reduction in study",
            }
        ],
        "consentScan": {
            "cmpDetected": "OneTrust",
            "bannerFound": True,
            "hasAcceptButton": True,
            "hasRejectButton": True,
            "hasSettingsButton": False,
            "acceptButtonText": "Accept All",
            "rejectButtonText": "Reject All",
            "settingsButtonText": None,
            "acceptClicksRequired": 1,
            "rejectClicksRequired": 1,
            "transparency": {},
            "darkPatterns": {"count": 0, "detected": []},
            "buttonComparison": None,
        },
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _render_popup(page, popup_result)
        page.wait_for_selector("#petList .pet-effectiveness")
        content = page.evaluate(
            """() => ({
                govNote: document.getElementById("govNote").textContent,
                petSubtitle: document.getElementById("petSubtitle").textContent,
                footer: document.getElementById("footerNote").textContent,
                cmpInfo: document.getElementById("cmpInfo").textContent,
                petList: document.getElementById("petList").textContent,
                petBadge: document.querySelector(".pet-effectiveness")?.textContent || ""
            })"""
        )
        browser.close()

    assert "stricter GDPR obligations" in content["govNote"]
    assert "~90%" not in content["govNote"]
    assert "100-site snapshot" in content["petSubtitle"]
    assert "97 successful crawls" in content["petSubtitle"]
    assert "March 1, 2026" in content["footer"]
    assert "OneTrust in the 100-site AECCS snapshot" in content["cmpInfo"]
    assert "45.1/100" in content["cmpInfo"]
    assert "62%" in content["cmpInfo"]
    assert "26 sites" in content["cmpInfo"]
    assert "33.4" in content["cmpInfo"]
    assert "+14.7% avg tracker reduction in study" in content["petList"]
    assert "95%" not in content["petList"]
    assert content["petBadge"] == "+15%"


def test_extension_copy_no_longer_contains_legacy_study_strings() -> None:
    tracker_data_text = TRACKER_DATA.read_text(encoding="utf-8")
    popup_html_text = POPUP_HTML.read_text(encoding="utf-8")
    popup_js_text = POPUP.read_text(encoding="utf-8")

    for text in (tracker_data_text, popup_html_text, popup_js_text):
        assert "1000-site" not in text
        assert "2025" not in text
        assert "~90% non-compliance among government domains" not in text


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

                const noReject = Scorer.computeComplianceScore([], {
                    bannerFound: true,
                    hasAcceptButton: true,
                    hasRejectButton: false,
                    hasSettingsButton: false,
                    acceptClicksRequired: 1,
                    rejectClicksRequired: 999,
                    darkPatterns: { count: 1, detected: ["Missing reject option"] },
                    transparency: {}
                });

                const noBanner = Scorer.computeComplianceScore([], {
                    bannerFound: false,
                    hasAcceptButton: false,
                    hasRejectButton: false,
                    hasSettingsButton: false,
                    acceptClicksRequired: 999,
                    rejectClicksRequired: 999,
                    darkPatterns: { count: 0, detected: [] },
                    transparency: {}
                });

                return { direct, settingsPath, noReject, noBanner };
            }"""
        )
        browser.close()

    assert scores["direct"]["criteria"]["reject_option_available"]["score"] == 100
    assert scores["direct"]["criteria"]["equal_accept_reject_effort"]["score"] == 100
    assert scores["direct"]["criteria"]["post_reject_compliance"]["score"] == 0
    assert scores["direct"]["criteria"]["post_reject_compliance"]["details"] == "No post-reject data available"
    assert scores["settingsPath"]["criteria"]["reject_option_available"]["score"] == 50
    assert scores["settingsPath"]["criteria"]["equal_accept_reject_effort"]["score"] == 50
    assert scores["settingsPath"]["criteria"]["post_reject_compliance"]["score"] == 0
    assert scores["settingsPath"]["criteria"]["post_reject_compliance"]["details"] == "No post-reject data available"
    assert scores["noReject"]["criteria"]["reject_option_available"]["score"] == 0
    assert scores["noReject"]["criteria"]["equal_accept_reject_effort"]["score"] == 0
    assert scores["noReject"]["criteria"]["post_reject_compliance"]["score"] == 0
    assert scores["noReject"]["criteria"]["post_reject_compliance"]["details"] == "No post-reject data available"
    assert scores["noBanner"]["criteria"]["reject_option_available"]["score"] == 0
    assert scores["noBanner"]["criteria"]["post_reject_compliance"]["score"] == 0
    assert scores["noBanner"]["criteria"]["post_reject_compliance"]["details"] == "No post-reject data available"
