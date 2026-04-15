from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "extension_scanner"
STUDY_SNAPSHOT = ROOT / "extension" / "lib" / "study-snapshot.js"
TRACKER_DATA = ROOT / "extension" / "lib" / "tracker-data.js"
TRACKER_INDEX = ROOT / "extension" / "lib" / "tracker-index.js"
DOMAIN_UTILS = ROOT / "extension" / "lib" / "domain-utils.js"
CLASSIFIER = ROOT / "extension" / "lib" / "classifier.js"
SCANNER = ROOT / "extension" / "content" / "consent-scanner.js"
SCORER = ROOT / "extension" / "lib" / "scorer.js"
POPUP = ROOT / "extension" / "popup" / "popup.js"
POPUP_CSS = ROOT / "extension" / "popup" / "popup.css"
POPUP_HTML = ROOT / "extension" / "popup" / "popup.html"
MANIFEST = ROOT / "extension" / "manifest.json"
README = ROOT / "README.md"
STORE_LISTING = ROOT / "docs" / "extension_store_listing.md"


def _install_scanner(target) -> None:
    target.add_script_tag(path=str(STUDY_SNAPSHOT))
    target.add_script_tag(path=str(TRACKER_DATA))
    target.add_script_tag(path=str(SCANNER))


def _scan_fixture(page, fixture_name: str) -> dict:
    page.goto((FIXTURES / fixture_name).as_uri())
    _install_scanner(page)
    return page.evaluate(
        """async () => {
            return await AECCSConsentScanner.scanPageWithRetries({
                attempts: 5,
                delayMs: 120
            });
        }"""
    )


def _scan_fixture_all_frames(page, fixture_name: str) -> dict:
    page.goto((FIXTURES / fixture_name).as_uri())

    frame_results = []
    best = None

    for index, frame in enumerate(page.frames):
        _install_scanner(frame)
        payload = frame.evaluate(
            """async () => {
                const scanResult = await AECCSConsentScanner.scanPageWithRetries({
                    attempts: 5,
                    delayMs: 120
                });
                return {
                    scanResult,
                    scanScore: AECCSConsentScanner.scoreResult(scanResult),
                };
            }"""
        )
        entry = {
            "frameIndex": index,
            "frameName": frame.name,
            "frameUrl": frame.url,
            **payload,
        }
        frame_results.append(entry)

        if best is None or _is_better_frame_scan(entry, best):
            best = entry

    return {
        "best": best["scanResult"] if best else None,
        "frames": frame_results,
    }


def _is_better_frame_scan(candidate: dict, current: dict | None) -> bool:
    if current is None:
        return True

    candidate_score = candidate.get("scanScore", -1)
    current_score = current.get("scanScore", -1)
    if candidate_score != current_score:
        return candidate_score > current_score

    candidate_direct_reject = bool(candidate["scanResult"].get("hasRejectButton"))
    current_direct_reject = bool(current["scanResult"].get("hasRejectButton"))
    if candidate_direct_reject != current_direct_reject:
        return candidate_direct_reject

    candidate_actionable = any(
        candidate["scanResult"].get(key) for key in ("hasAcceptButton", "hasRejectButton", "hasSettingsButton")
    )
    current_actionable = any(
        current["scanResult"].get(key) for key in ("hasAcceptButton", "hasRejectButton", "hasSettingsButton")
    )
    if candidate_actionable != current_actionable:
        return candidate_actionable

    return candidate["frameIndex"] < current["frameIndex"]


def _render_popup(page, result: dict) -> None:
    page.set_content(
        """
        <!DOCTYPE html>
        <html>
        <body>
          <div id="app">
            <header class="header">
              <div class="header-title">
                <svg class="logo" width="20" height="20" viewBox="0 1 24 24.5" fill="none">
                  <path d="M12 2L3 7v6c0 5.25 3.83 10.15 9 11.25C17.17 23.15 21 18.25 21 13V7l-9-5z"
                        class="logo-fill"></path>
                  <path d="M12 2L3 7v6c0 5.25 3.83 10.15 9 11.25C17.17 23.15 21 18.25 21 13V7l-9-5z"
                        class="logo-stroke" stroke-width="2" fill="none"></path>
                  <path d="M9 12l2 2 4-4" class="logo-stroke" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round"></path>
                </svg>
                <span>AECCS Compliance Checker</span>
              </div>
              <div id="siteDomain" class="site-domain">—</div>
            </header>

            <div id="loading" class="loading">
              <div class="spinner"></div>
              <span>Analyzing compliance...</span>
            </div>

            <div id="errorState" class="error-state hidden">
              <span class="error-icon">!</span>
              <span id="errorMsg"></span>
            </div>

            <div id="disabledState" class="disabled-state hidden">
              <span class="disabled-icon">i</span>
              <div class="disabled-copy">
                <div id="disabledTitle" class="disabled-title"></div>
                <div id="disabledMsg" class="disabled-msg"></div>
              </div>
            </div>

            <div id="results" class="hidden">
              <div id="govAlert" class="gov-alert hidden">
                <div>
                  <strong>Government / Public Sector Site</strong>
                  <div id="govNote" class="gov-note"></div>
                </div>
              </div>
              <section class="score-card">
                <div id="gradeBadge" class="grade-badge">
                  <span id="gradeLetter" class="grade-letter"></span>
                </div>
                <div class="score-info">
                  <div class="score-value"><span id="scoreValue"></span><span class="score-max">/100</span></div>
                  <div class="score-label">GDPR Compliance Score</div>
                </div>
              </section>
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
            <details id="studyInsightsSection" class="hidden">
              <summary>AECCS Study Insights</summary>
              <div id="studyInsightsContent"></div>
            </details>
            </div>
            <footer id="footerNote" class="footer"></footer>
          </div>
        </body>
        </html>
        """
    )
    page.add_style_tag(path=str(POPUP_CSS))
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
    page.add_script_tag(path=str(STUDY_SNAPSHOT))
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


def test_consent_scanner_detects_sourcepoint_like_buttons() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "sourcepoint_like.html")
        browser.close()

    assert result["cmpDetected"] == "Sourcepoint"
    assert result["bannerFound"] is True
    assert result["hasAcceptButton"] is True
    assert result["hasRejectButton"] is True
    assert result["hasSettingsButton"] is True
    assert result["acceptButtonText"] == "Accept all"
    assert result["rejectButtonText"] == "Essential cookies only"
    assert result["settingsButtonText"] == "View options"
    assert result["acceptClicksRequired"] == 1
    assert result["rejectClicksRequired"] == 1


def test_consent_scanner_prefers_iframe_hosted_banner_via_frame_aggregation() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        top_frame_result = _scan_fixture(page, "sourcepoint_iframe_host.html")
        merged = _scan_fixture_all_frames(page, "sourcepoint_iframe_host.html")
        browser.close()

    assert top_frame_result["bannerFound"] is False

    best = merged["best"]
    assert best is not None
    assert best["cmpDetected"] == "Sourcepoint"
    assert best["bannerFound"] is True
    assert best["hasAcceptButton"] is True
    assert best["hasRejectButton"] is True
    assert best["hasSettingsButton"] is True
    assert best["acceptButtonText"] == "Accept all"
    assert best["rejectButtonText"] == "Essential cookies only"
    assert best["settingsButtonText"] == "View options"
    assert best["acceptClicksRequired"] == 1
    assert best["rejectClicksRequired"] == 1

    iframe_scans = [
        entry for entry in merged["frames"]
        if entry["frameUrl"].endswith("sourcepoint_iframe_inner.html")
    ]
    assert len(iframe_scans) == 1
    assert iframe_scans[0]["scanResult"]["bannerFound"] is True


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
        page.add_script_tag(path=str(STUDY_SNAPSHOT))
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


def test_classifier_uses_precompiled_tracker_index_for_non_fallback_domains() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("data:text/html,<html><body></body></html>")
        page.add_script_tag(path=str(STUDY_SNAPSHOT))
        page.add_script_tag(path=str(TRACKER_DATA))
        page.add_script_tag(path=str(TRACKER_INDEX))
        page.add_script_tag(path=str(DOMAIN_UTILS))
        page.add_script_tag(path=str(CLASSIFIER))

        result = page.evaluate(
            """() => {
                return {
                    easyprivacy: Classifier.classifyCookie(
                        { name: "opt_test", domain: ".googleoptimize.com" },
                        "example.com"
                    ),
                    easylist: Classifier.classifyCookie(
                        { name: "ad_test", domain: ".zedo.com" },
                        "example.com"
                    ),
                };
            }"""
        )
        browser.close()

    assert result["easyprivacy"]["is_tracker"] is True
    assert result["easyprivacy"]["category"] == "Analytics"
    assert result["easyprivacy"]["classification_source"] == "easyprivacy"
    assert result["easylist"]["is_tracker"] is True
    assert result["easylist"]["category"] == "Advertising"
    assert result["easylist"]["classification_source"] == "easylist"


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


def test_popup_shows_disabled_state_when_no_active_banner_is_detected() -> None:
    popup_result = {
        "isGovDomain": False,
        "studyMetadata": {
            "label": "AECCS 1000-site combined study snapshot",
            "runId": "combined-1000",
            "sampleSize": 1000,
            "successfulCrawls": 861,
            "snapshotDateLabel": "March 6, 2026",
        },
        "evaluationDisabled": {
            "active": True,
            "reason": "no_active_cookie_banner",
            "title": "Evaluation unavailable on this page",
            "message": "AECCS works with active visible cookie banners. No cookie banner was detected, so this website was not evaluated.",
        },
        "score": None,
        "categoryCounts": {},
        "totalCookies": None,
        "thirdPartyCount": None,
        "trackerCount": None,
        "trackersByVendor": {},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": None,
            "bannerFound": False,
            "hasAcceptButton": False,
            "hasRejectButton": False,
            "hasSettingsButton": False,
            "acceptButtonText": None,
            "rejectButtonText": None,
            "settingsButtonText": None,
            "acceptClicksRequired": 999,
            "rejectClicksRequired": 999,
            "transparency": {},
            "darkPatterns": {"count": 0, "detected": []},
            "buttonComparison": None,
        },
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _render_popup(page, popup_result)
        state = page.evaluate(
            """() => ({
                disabledHidden: document.getElementById("disabledState").classList.contains("hidden"),
                resultsHidden: document.getElementById("results").classList.contains("hidden"),
                errorHidden: document.getElementById("errorState").classList.contains("hidden"),
                title: document.getElementById("disabledTitle").textContent,
                message: document.getElementById("disabledMsg").textContent,
                bodyBackground: getComputedStyle(document.body).backgroundColor,
                disabledBackground: getComputedStyle(document.getElementById("disabledState")).backgroundColor,
                disabledBorderColor: getComputedStyle(document.getElementById("disabledState")).borderBottomColor,
                disabledMessageColor: getComputedStyle(document.getElementById("disabledMsg")).color,
                disabledIconBackground: getComputedStyle(document.querySelector(".disabled-icon")).backgroundColor,
            })"""
        )
        browser.close()

    assert state["disabledHidden"] is False
    assert state["resultsHidden"] is True
    assert state["errorHidden"] is True
    assert state["title"] == "Evaluation unavailable on this page"
    assert "active visible cookie banners" in state["message"]
    assert "not evaluated" in state["message"]
    assert state["bodyBackground"] == "rgb(244, 248, 252)"
    assert state["disabledBackground"] == "rgb(239, 246, 255)"
    assert state["disabledBorderColor"] == "rgb(191, 219, 254)"
    assert state["disabledMessageColor"] == "rgb(95, 112, 136)"
    assert state["disabledIconBackground"] == "rgb(37, 99, 235)"


def test_popup_renders_updated_study_snapshot_copy_and_pet_cards() -> None:
    popup_result = {
        "isGovDomain": True,
        "studyMetadata": {
            "label": "AECCS 1000-site combined study snapshot",
            "runId": "combined-1000",
            "sampleSize": 1000,
            "successfulCrawls": 861,
            "bannerSites": 595,
            "snapshotDateLabel": "March 6, 2026",
            "avgCompliance": 27.4,
            "missingRejectRate": 0.84,
            "multiLayerRate": 0.105,
            "rejectReducesTrackersRate": 0.076,
            "rejectEliminatesTrackersRate": 0.122,
            "publicSector": {
                "successfulSites": 77,
                "avgCompliance": 30.9,
                "preConsentTrackerRate": 0.753,
            },
        },
        "score": {"grade": "D", "overall_score": 45.1, "criteria": {}},
        "categoryCounts": {},
        "totalCookies": 0,
        "thirdPartyCount": 0,
        "trackerCount": 0,
        "trackersByVendor": {},
        "cmpStats": {
            "avgScore": 35.5,
            "sampleSize": 138,
            "rejectRate": 0.406,
            "petScore": 24.1,
        },
        "petRecommendations": [
            {
                "name": "Brave Shields",
                "type": "browser",
                "description": "Built-in browser protection with the strongest average tracker reduction in the combined study.",
                "studyTrackerReductionPct": 22.8,
                "studySitesTested": 878,
                "studyRank": 1,
                "studyMetricLabel": "+22.8%",
                "studyLabel": "+22.8% avg tracker reduction in study",
                "studyTooltipText": "AECCS 1000-site combined study snapshot: Brave Shields averaged +22.8% tracker reduction across 878 tested sites. This is not a live measurement for the current page.",
                "whyRecommended": "Helps with pre-consent trackers and analytics trackers.",
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
                govAlertBackground: getComputedStyle(document.getElementById("govAlert")).backgroundColor,
                govNoteColor: getComputedStyle(document.getElementById("govNote")).color,
                petSubtitle: document.getElementById("petSubtitle").textContent,
                footer: document.getElementById("footerNote").textContent,
                cmpInfo: document.getElementById("cmpInfo").textContent,
                cmpPanelBackground: getComputedStyle(document.querySelector(".cmp-stats")).backgroundColor,
                cmpTitleColor: getComputedStyle(document.querySelector(".cmp-stats-title")).color,
                petList: document.getElementById("petList").textContent,
                petBadge: document.querySelector(".pet-effectiveness")?.textContent || "",
                petBadges: Array.from(document.querySelectorAll(".pet-effectiveness")).map(el => el.textContent),
                petInfoLabel: document.querySelector(".pet-study-info")?.getAttribute("aria-label") || "",
                petTooltipText: document.querySelector(".pet-study-tooltip")?.textContent || "",
                petTooltipHidden: document.querySelector(".pet-study-tooltip")?.hidden ?? true,
                studyInsightsOpen: document.getElementById("studyInsightsSection").open,
                studyInsightsContent: document.getElementById("studyInsightsContent").textContent,
            })"""
        )
        browser.close()

    assert "77 sites" in content["govNote"]
    assert "30.9/100" in content["govNote"]
    assert "75.3%" in content["govNote"]
    assert "~90%" not in content["govNote"]
    assert "1000-site combined study" in content["petSubtitle"]
    assert "861 successful crawls" in content["petSubtitle"]
    assert "March 6, 2026" in content["footer"]
    assert "OneTrust in the 1000-site AECCS combined snapshot" in content["cmpInfo"]
    assert "35.5/100" in content["cmpInfo"]
    assert "41%" in content["cmpInfo"]
    assert "138 sites" in content["cmpInfo"]
    assert "24.1" in content["cmpInfo"]
    assert "Why recommended:" in content["petList"]
    assert "Study snapshot:" not in content["petList"]
    assert "95%" not in content["petList"]
    assert content["petBadge"] == "+22.8%"
    assert "study" not in {badge.lower() for badge in content["petBadges"]}
    assert content["petInfoLabel"] == "Explain study metric for Brave Shields"
    assert "AECCS 1000-site combined study snapshot" in content["petTooltipText"]
    assert "878 tested sites" in content["petTooltipText"]
    assert "not a live measurement for the current page" in content["petTooltipText"]
    assert content["petTooltipHidden"] is True
    assert content["studyInsightsOpen"] is False
    assert content["studyInsightsContent"] == ""
    assert content["govAlertBackground"] == "rgb(239, 246, 255)"
    assert content["govNoteColor"] == "rgb(95, 112, 136)"
    assert content["cmpPanelBackground"] == "rgb(238, 244, 251)"
    assert content["cmpTitleColor"] == "rgb(37, 99, 235)"


def test_popup_pet_tooltip_supports_hover_focus_click_and_escape() -> None:
    popup_result = {
        "isGovDomain": False,
        "studyMetadata": {
            "label": "AECCS 1000-site combined study snapshot",
            "runId": "combined-1000",
            "sampleSize": 1000,
            "successfulCrawls": 861,
            "bannerSites": 595,
            "snapshotDateLabel": "March 6, 2026",
        },
        "score": {"grade": "C", "overall_score": 61, "criteria": {}},
        "categoryCounts": {},
        "totalCookies": 0,
        "thirdPartyCount": 0,
        "trackerCount": 0,
        "trackersByVendor": {},
        "cmpStats": None,
        "petRecommendations": [
            {
                "name": "Brave Shields",
                "type": "browser",
                "description": "Built-in browser protection with the strongest average tracker reduction in the combined study.",
                "studyTrackerReductionPct": 22.8,
                "studySitesTested": 878,
                "studyRank": 1,
                "studyMetricLabel": "+22.8%",
                "studyTooltipText": "AECCS 1000-site combined study snapshot: Brave Shields averaged +22.8% tracker reduction across 878 tested sites. This is not a live measurement for the current page.",
                "whyRecommended": "Helps with pre-consent trackers.",
            },
            {
                "name": "Consent-O-Matic",
                "type": "extension",
                "description": "Automates reject flows when a site exposes a usable path, rather than blocking requests directly.",
                "studyTrackerReductionPct": -11.2,
                "studySitesTested": 896,
                "studyRank": 5,
                "studyMetricLabel": "-11.2%",
                "studyTooltipText": "AECCS 1000-site combined study snapshot: Consent-O-Matic averaged -11.2% tracker reduction across 896 tested sites. This is not a live measurement for the current page.",
                "whyRecommended": "Helps with dark patterns and reject friction.",
            },
        ],
        "consentScan": {
            "cmpDetected": None,
            "bannerFound": False,
            "hasAcceptButton": False,
            "hasRejectButton": False,
            "hasSettingsButton": False,
            "acceptButtonText": None,
            "rejectButtonText": None,
            "settingsButtonText": None,
            "acceptClicksRequired": 0,
            "rejectClicksRequired": 0,
            "transparency": {},
            "darkPatterns": {"count": 0, "detected": []},
            "buttonComparison": None,
        },
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _render_popup(page, popup_result)
        page.wait_for_selector("#petList .pet-study-info")

        initial = page.evaluate(
            """() => ({
                expanded: document.querySelector(".pet-study-info")?.getAttribute("aria-expanded"),
                hidden: document.querySelector(".pet-study-tooltip")?.hidden
            })"""
        )

        page.hover(".pet-study")
        after_hover = page.evaluate(
            """() => ({
                expanded: document.querySelector(".pet-study-info")?.getAttribute("aria-expanded"),
                hidden: document.querySelector(".pet-study-tooltip")?.hidden
            })"""
        )

        page.hover("#footerNote")
        after_mouse_leave = page.evaluate(
            """() => document.querySelector(".pet-study-tooltip")?.hidden"""
        )

        page.focus(".pet-study-info")
        after_focus = page.evaluate(
            """() => document.querySelector(".pet-study-tooltip")?.hidden"""
        )

        page.keyboard.press("Escape")
        after_escape = page.evaluate(
            """() => document.querySelector(".pet-study-tooltip")?.hidden"""
        )

        page.click(".pet-study-info")
        after_click = page.evaluate(
            """() => document.querySelector(".pet-study-tooltip")?.hidden"""
        )

        page.click(".pet-card:nth-child(2) .pet-study-info")
        after_second_click = page.evaluate(
            """() => ({
                expanded: Array.from(document.querySelectorAll(".pet-study-info")).map(el => el.getAttribute("aria-expanded")),
                visible: Array.from(document.querySelectorAll(".pet-study-tooltip")).map(el => !el.hidden)
            })"""
        )

        page.click("#footerNote")
        after_outside_click = page.evaluate(
            """() => Array.from(document.querySelectorAll(".pet-study-tooltip")).every(el => el.hidden)"""
        )
        browser.close()

    assert initial["expanded"] == "false"
    assert initial["hidden"] is True
    assert after_hover["expanded"] == "true"
    assert after_hover["hidden"] is False
    assert after_mouse_leave is True
    assert after_focus is False
    assert after_escape is True
    assert after_click is False
    assert after_second_click["expanded"] == ["false", "true"]
    assert after_second_click["visible"] == [False, True]
    assert after_outside_click is True


def test_popup_study_insights_lazy_render_combined_snapshot_content() -> None:
    popup_result = {
        "isGovDomain": True,
        "studyMetadata": {
            "label": "AECCS 1000-site combined study snapshot",
            "runId": "combined-1000",
            "sampleSize": 1000,
            "successfulCrawls": 861,
            "bannerSites": 595,
            "snapshotDateLabel": "March 6, 2026",
            "avgCompliance": 27.4,
            "missingRejectRate": 0.84,
            "multiLayerRate": 0.105,
            "rejectReducesTrackersRate": 0.076,
            "rejectEliminatesTrackersRate": 0.122,
            "publicSector": {
                "successfulSites": 77,
                "avgCompliance": 30.9,
                "preConsentTrackerRate": 0.753,
            },
        },
        "score": {"grade": "F", "overall_score": 26, "criteria": {}},
        "categoryCounts": {},
        "totalCookies": 0,
        "thirdPartyCount": 0,
        "trackerCount": 0,
        "trackersByVendor": {},
        "cmpStats": {
            "avgScore": 36.2,
            "sampleSize": 49,
            "rejectRate": 0.388,
            "petScore": 24.9,
        },
        "petRecommendations": [
            {
                "name": "Consent-O-Matic",
                "type": "extension",
                "description": "Automates reject flows when a site exposes a usable path, rather than blocking requests directly.",
                "studyTrackerReductionPct": -11.2,
                "studyLabel": "-11.2% avg tracker reduction in study",
                "whyRecommended": "Helps with dark patterns and reject friction.",
            }
        ],
        "consentScan": {
            "cmpDetected": "Didomi",
            "bannerFound": True,
            "hasAcceptButton": True,
            "hasRejectButton": False,
            "hasSettingsButton": True,
            "acceptButtonText": "Accept",
            "rejectButtonText": None,
            "settingsButtonText": "Manage Preferences",
            "acceptClicksRequired": 1,
            "rejectClicksRequired": 2,
            "transparency": {},
            "darkPatterns": {"count": 2, "detected": ["Missing reject option", "Multi-layer rejection"]},
            "buttonComparison": None,
        },
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _render_popup(page, popup_result)
        page.wait_for_function(
            """() => !document.getElementById("studyInsightsSection").classList.contains("hidden")"""
        )

        before = page.evaluate(
            """() => ({
                open: document.getElementById("studyInsightsSection").open,
                content: document.getElementById("studyInsightsContent").textContent
            })"""
        )

        page.click("#studyInsightsSection summary")
        page.wait_for_function(
            """() => document.getElementById("studyInsightsSection").open &&
                document.getElementById("studyInsightsContent").textContent.length > 0"""
        )

        after = page.evaluate(
            """() => document.getElementById("studyInsightsContent").textContent"""
        )
        browser.close()

    assert before["open"] is False
    assert before["content"] == ""
    assert "AECCS 1000-site combined study snapshot" in after
    assert "March 6, 2026" in after
    assert "Brave Shields" in after
    assert "Didomi" in after
    assert "combined-1000" in after
    assert "77 successful government/public-sector sites" in after
    assert "crawl → classify → dark-pattern detect → score → CMP analysis → PET comparison → reporting" in after
    assert "GDPR Validator" not in after
    assert "fixGDPR" not in after


def test_extension_copy_no_longer_contains_legacy_study_strings() -> None:
    study_snapshot_text = STUDY_SNAPSHOT.read_text(encoding="utf-8")
    tracker_data_text = TRACKER_DATA.read_text(encoding="utf-8")
    popup_html_text = POPUP_HTML.read_text(encoding="utf-8")
    popup_js_text = POPUP.read_text(encoding="utf-8")

    for text in (study_snapshot_text, tracker_data_text, popup_html_text, popup_js_text):
        assert "100-site snapshot" not in text
        assert "March 1, 2026" not in text
        assert "2025" not in text
        assert "~90% non-compliance among government domains" not in text


def test_extension_combined_study_snapshot_matches_authoritative_values() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("data:text/html,<html><body></body></html>")
        page.add_script_tag(path=str(STUDY_SNAPSHOT))
        page.add_script_tag(path=str(TRACKER_DATA))
        result = page.evaluate(
            """() => ({
                study: AECCS.STUDY_METADATA,
                bestPet: AECCS.PET_STUDY_RESULTS[0],
                bestPetProfile: AECCS.PET_PROFILES.find(p => p.name === "Brave Shields"),
                bestCmp: AECCS.CMP_STUDY_RESULTS[0],
                cmpStats: AECCS.CMP_STATS.Didomi
            })"""
        )
        browser.close()

    assert result["study"]["label"] == "AECCS 1000-site combined study snapshot"
    assert result["study"]["runId"] == "combined-1000"
    assert result["study"]["sampleSize"] == 1000
    assert result["study"]["successfulCrawls"] == 861
    assert result["study"]["failedCrawls"] == 139
    assert result["study"]["bannerSites"] == 595
    assert result["study"]["avgCompliance"] == 27.4
    assert result["study"]["missingRejectRate"] == 0.84
    assert result["study"]["multiLayerRate"] == 0.105
    assert result["study"]["rejectReducesTrackersRate"] == 0.076
    assert result["study"]["rejectEliminatesTrackersRate"] == 0.122
    assert result["study"]["publicSector"]["successfulSites"] == 77
    assert result["bestPet"]["name"] == "Brave Shields"
    assert result["bestPet"]["trackerReductionPct"] == 22.8
    assert result["bestPetProfile"]["studySitesTested"] == 878
    assert result["bestPetProfile"]["studyRank"] == 1
    assert result["bestPetProfile"]["studyMetricLabel"] == "+22.8%"
    assert "not a live measurement for the current page" in result["bestPetProfile"]["studyTooltipText"]
    assert result["bestCmp"]["name"] == "Didomi"
    assert result["bestCmp"]["petScore"] == 24.9
    assert result["cmpStats"]["sampleSize"] == 49
    assert result["cmpStats"]["avgScore"] == 36.2


def test_readme_and_store_listing_use_passive_combined_study_framing() -> None:
    readme_text = README.read_text(encoding="utf-8")
    manifest_text = MANIFEST.read_text(encoding="utf-8")
    listing_text = STORE_LISTING.read_text(encoding="utf-8")

    assert "passive, local cookie-consent auditor" in readme_text.lower()
    assert "1000-site combined study" in readme_text
    assert "no blocking" in readme_text.lower()
    assert "no auto-clicking" in readme_text.lower()
    assert "study-backed pet guidance" in readme_text.lower()

    assert "Passive, research-grounded GDPR cookie-consent auditor" in manifest_text

    assert "Passive, research-grounded GDPR cookie-consent auditor" in listing_text
    assert "1000-site combined study snapshot" in listing_text
    assert "Not an auto-consent clicker" in listing_text
    assert "First to detect dark patterns" in listing_text


def test_scorer_distinguishes_direct_and_settings_reject_paths() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("data:text/html,<html><body></body></html>")
        page.add_script_tag(path=str(STUDY_SNAPSHOT))
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
