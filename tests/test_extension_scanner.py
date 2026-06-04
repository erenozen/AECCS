from __future__ import annotations

from contextlib import contextmanager
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright

from tests._consent_cases import CONSENT_ACTION_CASES

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "extension_scanner"
STUDY_SNAPSHOT = ROOT / "extension" / "lib" / "study-snapshot.js"
SHARED_CONFIG = ROOT / "extension" / "lib" / "shared-config.js"
TRACKER_DATA = ROOT / "extension" / "lib" / "tracker-data.js"
TRACKER_INDEX = ROOT / "extension" / "lib" / "tracker-index.js"
DOMAIN_UTILS = ROOT / "extension" / "lib" / "domain-utils.js"
CLASSIFIER = ROOT / "extension" / "lib" / "classifier.js"
SCANNER = ROOT / "extension" / "content" / "consent-scanner.js"
SCORER = ROOT / "extension" / "lib" / "scorer.js"
POPUP = ROOT / "extension" / "popup" / "popup.js"
POPUP_CSS = ROOT / "extension" / "popup" / "popup.css"
POPUP_HTML = ROOT / "extension" / "popup" / "popup.html"
SERVICE_WORKER = ROOT / "extension" / "background" / "service-worker.js"
MANIFEST = ROOT / "extension" / "manifest.json"
README = ROOT / "README.md"
PRIVACY_POLICY = ROOT / "docs" / "privacy-policy.html"


def _install_runtime(target) -> None:
    target.add_script_tag(path=str(STUDY_SNAPSHOT))
    target.add_script_tag(path=str(SHARED_CONFIG))
    target.add_script_tag(path=str(TRACKER_DATA))


def _install_scanner_script(target) -> None:
    target.add_script_tag(path=str(SCANNER))


def _install_scanner(target) -> None:
    _install_runtime(target)
    _install_scanner_script(target)


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


def _scan_inline_banner(
    page,
    *,
    accept: str | None = "Accept All",
    reject: str | None = None,
    settings: str | None = None,
    dismiss: str | None = None,
) -> dict:
    buttons: list[str] = []
    if accept:
        buttons.append(f'<button type="button">{escape(accept)}</button>')
    if reject:
        buttons.append(f'<button type="button">{escape(reject)}</button>')
    if settings:
        buttons.append(f'<button type="button">{escape(settings)}</button>')
    if dismiss:
        buttons.append(f'<button type="button">{escape(dismiss)}</button>')

    page.set_content(
        f"""
        <!DOCTYPE html>
        <html>
        <body>
          <main style="min-height: 120vh;">Fixture page</main>
          <div id="inline-banner" role="dialog" aria-modal="true"
               style="position: fixed; left: 0; right: 0; bottom: 0; z-index: 9999;
                      padding: 18px; background: rgb(255, 255, 255); border-top: 1px solid #cbd5e1;
                      box-shadow: 0 -8px 24px rgba(15, 23, 42, 0.12);">
            <p>We use cookies to improve the site and remember your preferences.</p>
            <div style="display: flex; gap: 12px;">{''.join(buttons)}</div>
          </div>
        </body>
        </html>
        """
    )
    _install_scanner(page)
    return page.evaluate(
        """async () => {
            return await AECCSConsentScanner.scanPageWithRetries({
                attempts: 2,
                delayMs: 20
            });
        }"""
    )


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


def _mount_popup_shell(page) -> None:
    # The score gauge sweep + count-up animate on requestAnimationFrame, so
    # emulate the OS "reduce motion" preference to render the final score state
    # synchronously and keep these assertions deterministic (this also exercises
    # the reduced-motion code path in popup.js).
    page.emulate_media(reduced_motion="reduce")
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

            <section id="onboardingCard" class="onboarding hidden" aria-labelledby="onboardingTitle">
              <h2 class="onboarding-title" id="onboardingTitle">Welcome to AECCS</h2>
              <div class="onboarding-lead">AECCS rates a website's cookie-consent banner for GDPR compliance using six weighted criteria.</div>
              <ul class="onboarding-points">
                <li>Runs entirely on your device.</li>
                <li>Audits the active tab only, on demand.</li>
                <li>Open <strong>About &amp; Methodology</strong> below anytime.</li>
              </ul>
              <button id="onboardingDismiss" class="onboarding-button" type="button">Got it</button>
            </section>

            <div id="loading" class="loading">
              <span class="sr-only" role="status" aria-live="polite">Analyzing compliance...</span>
              <div class="skeleton" aria-hidden="true">
                <div class="skeleton-score">
                  <div class="skeleton-block skeleton-circle"></div>
                  <div class="skeleton-lines">
                    <div class="skeleton-block skeleton-line skeleton-line-lg"></div>
                    <div class="skeleton-block skeleton-line skeleton-line-sm"></div>
                  </div>
                </div>
                <div class="skeleton-section">
                  <div class="skeleton-block skeleton-title"></div>
                  <div class="skeleton-block skeleton-bar"></div>
                </div>
                <div class="skeleton-section">
                  <div class="skeleton-block skeleton-title"></div>
                  <div class="skeleton-block skeleton-line"></div>
                  <div class="skeleton-block skeleton-line skeleton-line-sm"></div>
                </div>
              </div>
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
                <div id="gradeBadge" class="grade-badge gauge">
                  <svg class="gauge-ring" viewBox="0 0 36 36" aria-hidden="true" focusable="false">
                    <circle class="gauge-track" cx="18" cy="18" r="15.9155"></circle>
                    <circle class="gauge-arc" cx="18" cy="18" r="15.9155"
                            stroke-dasharray="100 100" stroke-dashoffset="100"
                            transform="rotate(-90 18 18)"></circle>
                  </svg>
                  <span id="gradeLetter" class="grade-letter"></span>
                </div>
                <div class="score-info">
                  <div class="score-value"><span id="scoreValue"></span><span class="score-max">/100</span></div>
                  <div id="scoreLabel" class="score-label">GDPR Compliance Score</div>
                  <div id="scoreContext" class="score-context hidden"></div>
                </div>
              </section>
            <section class="section score-context-panel">
              <div id="analysisCompleteness" class="analysis-completeness hidden"></div>
              <div id="protectionCaveat" class="protection-caveat hidden">
                <div class="protection-caveat-title">Measured in your current browsing setup</div>
                <div id="protectionCaveatText" class="protection-caveat-text"></div>
              </div>
            </section>
            <section id="baselineScoreSection" class="section secondary-score hidden">
              <h2 class="section-title">Baseline Banner Score</h2>
              <div class="secondary-score-card">
                <div id="baselineGradeBadge" class="secondary-grade-badge gauge">
                  <svg class="gauge-ring" viewBox="0 0 36 36" aria-hidden="true" focusable="false">
                    <circle class="gauge-track" cx="18" cy="18" r="15.9155"></circle>
                    <circle class="gauge-arc" cx="18" cy="18" r="15.9155"
                            stroke-dasharray="100 100" stroke-dashoffset="100"
                            transform="rotate(-90 18 18)"></circle>
                  </svg>
                  <span id="baselineGradeLetter" class="secondary-grade-letter"></span>
                </div>
                <div class="secondary-score-info">
                  <div class="secondary-score-value"><span id="baselineScoreValue"></span><span class="score-max">/100</span></div>
                  <div id="baselineScoreLabel" class="score-label">GDPR Compliance Score</div>
                </div>
              </div>
            </section>
            <div id="cookieBar"></div>
            <div id="cookieCounts"></div>
            <div id="cookieMeta"></div>
            <div id="trackerSection"></div>
            <div id="trackerList"></div>
            <div id="consentInfo"></div>
            <div id="cmpInfo" class="hidden"></div>
            <section id="interactionSection" class="hidden">
              <div id="compareFlow"></div>
              <div class="compare-actions">
                <button id="recheckButton" type="button">Re-check now</button>
                <button id="startOverButton" type="button">Start over</button>
              </div>
              <div id="interactionInfo"></div>
            </section>
            <section id="buttonCompSection" class="hidden"><div id="buttonComparison"></div></section>
            <section id="darkPatternSection"><div id="darkPatternDetails"></div></section>
            <table><tbody id="criteriaBody"></tbody></table>
            <details id="petSection" class="study-insights pet-recommendations hidden">
              <summary class="study-insights-toggle">
                <span>Recommended Privacy Tools</span>
                <span class="study-insights-meta">Study-backed guidance</span>
              </summary>
              <div id="petContent" class="study-insights-content">
                <div id="petSubtitle" class="pet-subtitle"></div>
                <div id="petList"></div>
              </div>
            </details>
            <details id="browsingSetupSection" class="section browsing-setup">
              <summary class="study-insights-toggle">
                <span>Browsing Setup</span>
                <span id="browsingSetupSummary" class="study-insights-meta">No protections declared</span>
              </summary>
              <div class="study-insights-content">
                <div class="setup-subtitle"></div>
                <label class="setup-field">
                  <span class="setup-label">Browser protection</span>
                  <select id="browserProtectionSelect" class="setup-select">
                    <option value="none">None declared</option>
                    <option value="firefox_etp_standard">Firefox ETP Standard</option>
                    <option value="firefox_etp_strict">Firefox ETP Strict</option>
                    <option value="brave_shields">Brave Shields</option>
                  </select>
                </label>
                <div class="setup-field">
                  <div class="setup-label">Extra tools</div>
                  <div class="setup-checkbox-grid">
                    <label class="setup-checkbox"><input type="checkbox" name="extraTool" value="ublock_origin"><span>uBlock Origin</span></label>
                    <label class="setup-checkbox"><input type="checkbox" name="extraTool" value="privacy_badger"><span>Privacy Badger</span></label>
                    <label class="setup-checkbox"><input type="checkbox" name="extraTool" value="consent_o_matic"><span>Consent-O-Matic</span></label>
                  </div>
                </div>
                <div id="browsingSetupStatus" class="setup-status"></div>
                <details id="protectionExplainer" class="protection-explainer">
                  <summary class="protection-explainer-toggle">How this can affect results</summary>
                  <div id="protectionExplainerContent" class="protection-explainer-content"></div>
                </details>
              </div>
            </details>
            <details id="studyInsightsSection" class="hidden">
              <summary>AECCS Study Insights</summary>
              <div id="studyInsightsContent"></div>
            </details>
            </div>
            <details id="aboutSection" class="section study-insights about-methodology">
              <summary class="study-insights-toggle">
                <span>About &amp; Methodology</span>
                <span class="study-insights-meta">How AECCS scores this page</span>
              </summary>
              <div class="study-insights-content">
                <div class="insight-intro">AECCS audits the active tab's cookie-consent banner against GDPR.</div>
                <div class="insight-card">
                  <div class="insight-card-title">Six weighted criteria</div>
                  <div id="aboutCriteriaList" class="about-criteria"></div>
                </div>
                <div class="insight-card">
                  <div class="insight-card-title">Study basis</div>
                  <div id="aboutStudyBasis" class="insight-card-copy"></div>
                </div>
                <div class="insight-card-copy about-privacy">
                  Privacy statement.
                  <a class="about-privacy-link" href="https://erenozen.github.io/AECCS/privacy-policy.html" target="_blank" rel="noopener noreferrer">Read the privacy policy</a>
                </div>
              </div>
            </details>
            <footer id="footerNote" class="footer"></footer>
          </div>
        </body>
        </html>
        """
    )
    page.add_style_tag(path=str(POPUP_CSS))


def _render_popup(page, result: dict) -> None:
    _mount_popup_shell(page)
    page.evaluate(
        """data => {
            window.__aeccsPopupStorage = {};
            window.__aeccsMessageResponses = [data];
            window.__aeccsMessageCalls = [];
            window.browser = {
                tabs: {
                    query: async () => [{ id: 1, url: "https://eksisozluk.com" }]
                },
                runtime: {
                    sendMessage: async msg => {
                        window.__aeccsMessageCalls.push(msg);
                        if (typeof window.__aeccsPopupMessageHandler === "function") {
                            return await window.__aeccsPopupMessageHandler(msg);
                        }
                        return window.__aeccsMessageResponses[0];
                    }
                },
                storage: {
                    local: {
                        get: async key => {
                            if (typeof key === "string") {
                                return { [key]: window.__aeccsPopupStorage[key] };
                            }
                            return { ...window.__aeccsPopupStorage };
                        },
                        set: async payload => {
                            Object.assign(window.__aeccsPopupStorage, payload || {});
                        }
                    }
                }
            };
        }""",
        result,
    )
    page.add_script_tag(path=str(STUDY_SNAPSHOT))
    page.add_script_tag(path=str(SHARED_CONFIG))
    page.add_script_tag(path=str(TRACKER_DATA))
    page.add_script_tag(path=str(POPUP))


def _boot_popup_with_state(
    page,
    *,
    responses: list[dict] | None = None,
    storage_state: dict | None = None,
    tab_url: str = "https://eksisozluk.com",
    tab_id: int = 1,
) -> None:
    _mount_popup_shell(page)
    page.evaluate(
        """payload => {
            window.__aeccsPopupStorage = payload.storageState || {};
            window.__aeccsMessageResponses = payload.responses || [];
            window.__aeccsMessageCalls = [];
            window.browser = {
                tabs: {
                    query: async () => [{ id: payload.tabId, url: payload.tabUrl }]
                },
                runtime: {
                    sendMessage: async msg => {
                        window.__aeccsMessageCalls.push(msg);
                        if (typeof window.__aeccsPopupMessageHandler === "function") {
                            return await window.__aeccsPopupMessageHandler(msg);
                        }
                        const responses = window.__aeccsMessageResponses || [];
                        const index = Math.min(Math.max(window.__aeccsMessageCalls.length - 1, 0), Math.max(responses.length - 1, 0));
                        return responses[index] ?? null;
                    }
                },
                storage: {
                    local: {
                        get: async key => {
                            if (typeof key === "string") {
                                return { [key]: window.__aeccsPopupStorage[key] };
                            }
                            return { ...window.__aeccsPopupStorage };
                        },
                        set: async payload => {
                            Object.assign(window.__aeccsPopupStorage, payload || {});
                        }
                    }
                }
            };
        }""",
        {
            "responses": responses or [],
            "storageState": storage_state or {},
            "tabUrl": tab_url,
            "tabId": tab_id,
        },
    )
    page.add_script_tag(path=str(STUDY_SNAPSHOT))
    page.add_script_tag(path=str(SHARED_CONFIG))
    page.add_script_tag(path=str(TRACKER_DATA))
    page.add_script_tag(path=str(POPUP))


def _install_service_worker_harness(page, timeout_overrides: dict | None = None) -> None:
    page.set_content("<!DOCTYPE html><html><body></body></html>")
    page.evaluate(
        """overrides => {
            window.__AECCS_TIMEOUTS = overrides || {};
            window.browser = {
                runtime: {
                    onMessage: {
                        addListener() {}
                    }
                }
            };
        }""",
        timeout_overrides or {},
    )
    page.add_script_tag(path=str(STUDY_SNAPSHOT))
    page.add_script_tag(path=str(SHARED_CONFIG))
    page.add_script_tag(path=str(TRACKER_DATA))
    page.add_script_tag(path=str(TRACKER_INDEX))
    page.add_script_tag(path=str(DOMAIN_UTILS))
    page.add_script_tag(path=str(CLASSIFIER))
    page.add_script_tag(path=str(SCORER))
    page.add_script_tag(path=str(SERVICE_WORKER))


@contextmanager
def _serve_fixture_dir(directory: Path):
    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, format, *args):  # noqa: A003 - stdlib signature
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _launch_extension_context_or_skip(playwright):
    extension_dir = (ROOT / "extension").resolve()
    try:
        return playwright.chromium.launch_persistent_context(
            user_data_dir="/tmp/aeccs-extension-integration-profile",
            headless=True,
            args=[
                f"--disable-extensions-except={extension_dir}",
                f"--load-extension={extension_dir}",
            ],
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Extension-backed browser context unavailable in this environment: {exc}")


def _get_extension_service_worker(context):
    if context.service_workers:
        return context.service_workers[0]
    try:
        return context.wait_for_event("serviceworker", timeout=10000)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Extension service worker unavailable in this environment: {exc}")


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


def test_consent_scanner_treats_dismissed_banner_as_no_active_banner() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "dismissible_reddit_like.html").as_uri())
        _install_scanner(page)

        before = page.evaluate(
            """async () => {
                return await AECCSConsentScanner.scanPageWithRetries({
                    attempts: 2,
                    delayMs: 20
                });
            }"""
        )

        page.click(".close-btn")
        page.wait_for_function(
            """() => getComputedStyle(document.querySelector(".site-footer")).display === "block" """
        )

        after = page.evaluate(
            """async () => {
                return await AECCSConsentScanner.scanPageWithRetries({
                    attempts: 2,
                    delayMs: 20
                });
            }"""
        )
        browser.close()

    assert before["bannerFound"] is True
    assert before["hasAcceptButton"] is True
    assert before["hasRejectButton"] is True

    assert after["bannerFound"] is False
    assert after["hasAcceptButton"] is False
    assert after["hasRejectButton"] is False
    assert after["hasSettingsButton"] is False
    assert after["darkPatterns"]["count"] == 0
    assert after["darkPatterns"]["detected"] == []


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


def test_consent_scanner_detects_onetrust_i_accept_button() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1080})
        result = _scan_fixture(page, "onetrust_i_accept_like.html")
        browser.close()

    assert result["cmpDetected"] == "OneTrust"
    assert result["bannerFound"] is True
    assert result["hasAcceptButton"] is True
    assert result["hasRejectButton"] is True
    assert result["hasSettingsButton"] is True
    assert result["acceptButtonText"] == "I Accept"
    assert result["rejectButtonText"] == "Reject All"
    assert result["settingsButtonText"] == "Show Purposes, Opens the preference center dialog"
    assert result["acceptClicksRequired"] == 1
    assert result["rejectClicksRequired"] == 1


def test_consent_scanner_does_not_infer_accept_from_explanatory_text_only() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1080})
        page.set_content(
            """
            <!DOCTYPE html>
            <html>
            <body>
              <div id="onetrust-banner-sdk" role="dialog" aria-label="Cookie banner"
                   style="position: fixed; left: 0; right: 0; bottom: 0; z-index: 9999;
                          padding: 24px; background: white; border-top: 1px solid #d1d5db;">
                <h2>We Care About Your Privacy</h2>
                <p>
                  Selecting I Accept enables tracking technologies to support the purposes shown below.
                </p>
                <div style="display: flex; gap: 12px;">
                  <button type="button">Reject All</button>
                  <button type="button">Show Purposes</button>
                </div>
              </div>
            </body>
            </html>
            """
        )
        _install_scanner(page)
        result = page.evaluate(
            """async () => {
                return await AECCSConsentScanner.scanPageWithRetries({
                    attempts: 2,
                    delayMs: 20
                });
            }"""
        )
        browser.close()

    assert result["bannerFound"] is True
    assert result["hasAcceptButton"] is False
    assert result["acceptButtonText"] is None
    assert result["hasRejectButton"] is True
    assert result["rejectButtonText"] == "Reject All"
    assert result["hasSettingsButton"] is True
    assert result["settingsButtonText"] == "Show Purposes"


@pytest.mark.parametrize(("language", "label", "expected_field"), CONSENT_ACTION_CASES)
def test_consent_scanner_matches_multilingual_action_labels(
    language: str, label: str, expected_field: str
) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_inline_banner(
            page,
            accept=label if expected_field == "accept" else (None if expected_field == "dismiss" else "Accept All"),
            reject=label if expected_field == "reject" else None,
            settings=label if expected_field == "settings" else None,
            dismiss=label if expected_field == "dismiss" else None,
        )
        browser.close()

    assert result["bannerFound"] is True

    if expected_field == "accept":
        assert result["hasAcceptButton"] is True
        assert result["acceptButtonText"] == label
    elif expected_field == "reject":
        assert result["hasAcceptButton"] is True
        assert result["acceptButtonText"] == "Accept All"
        assert result["hasRejectButton"] is True
        assert result["rejectButtonText"] == label
        assert result["rejectClicksRequired"] == 1
    elif expected_field == "settings":
        assert result["hasAcceptButton"] is True
        assert result["acceptButtonText"] == "Accept All"
        assert result["hasSettingsButton"] is True
        assert result["settingsButtonText"] == label
        assert result["rejectClicksRequired"] == 2
    else:
        assert result["hasAcceptButton"] is False
        assert result["hasRejectButton"] is False
        assert result["hasSettingsButton"] is False


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


def test_consent_scanner_bootstrap_exports_runtime_contract_in_order() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "sourcepoint_like.html").as_uri())

        _install_runtime(page)
        runtime_status = page.evaluate(
            """() => ({
                hasSharedConfig: !!globalThis.AECCSSharedConfig,
                hasAECCS: !!globalThis.AECCS,
                hasScanner: !!globalThis.AECCSConsentScanner
            })"""
        )

        _install_scanner_script(page)
        scanner_status = page.evaluate(
            """() => ({
                hasAECCS: !!globalThis.AECCS,
                hasScanner: !!globalThis.AECCSConsentScanner,
                loaded: !!globalThis._AECCSConsentScannerLoaded,
                initStage: globalThis._AECCSConsentScannerInitStage,
                initError: globalThis._AECCSConsentScannerInitError
            })"""
        )
        browser.close()

    assert runtime_status == {
        "hasSharedConfig": True,
        "hasAECCS": True,
        "hasScanner": False,
    }
    assert scanner_status["hasAECCS"] is True
    assert scanner_status["hasScanner"] is True
    assert scanner_status["loaded"] is True
    assert scanner_status["initStage"] == "ready"
    assert scanner_status["initError"] is None


def test_tracker_data_records_init_error_when_shared_config_is_missing() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "sourcepoint_like.html").as_uri())

        page.add_script_tag(path=str(TRACKER_DATA))
        tracker_state = page.evaluate(
            """() => ({
                loaded: !!globalThis._AECCSTrackerDataLoaded,
                hasAECCS: !!globalThis.AECCS,
                initStage: globalThis._AECCSTrackerDataInitStage,
                initError: globalThis._AECCSTrackerDataInitError
            })"""
        )
        browser.close()

    assert tracker_state["loaded"] is False
    assert tracker_state["hasAECCS"] is False
    assert tracker_state["initStage"] == "runtime"
    assert tracker_state["initError"] is not None
    assert "AECCSSharedConfig missing" in tracker_state["initError"]


def test_consent_scanner_recovers_after_failed_init_without_poisoning_frame() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "sourcepoint_like.html").as_uri())

        _install_scanner_script(page)

        failed_state = page.evaluate(
            """() => ({
                loaded: !!globalThis._AECCSConsentScannerLoaded,
                hasScanner: !!globalThis.AECCSConsentScanner,
                initStage: globalThis._AECCSConsentScannerInitStage,
                initError: globalThis._AECCSConsentScannerInitError
            })"""
        )

        _install_runtime(page)
        _install_scanner_script(page)
        recovered_state = page.evaluate(
            """async () => ({
                loaded: !!globalThis._AECCSConsentScannerLoaded,
                hasScanner: !!globalThis.AECCSConsentScanner,
                initStage: globalThis._AECCSConsentScannerInitStage,
                initError: globalThis._AECCSConsentScannerInitError,
                scanResult: await globalThis.AECCSConsentScanner.scanPageWithRetries({
                    attempts: 2,
                    delayMs: 20
                })
            })"""
        )
        browser.close()

    assert failed_state["loaded"] is False
    assert failed_state["hasScanner"] is False
    assert failed_state["initStage"] == "runtime"
    assert failed_state["initError"] is not None
    assert "AECCS runtime unavailable" in failed_state["initError"]

    assert recovered_state["loaded"] is True
    assert recovered_state["hasScanner"] is True
    assert recovered_state["initStage"] == "ready"
    assert recovered_state["initError"] is None
    assert recovered_state["scanResult"]["bannerFound"] is True
    assert recovered_state["scanResult"]["rejectButtonText"] == "Essential cookies only"


def test_consent_scanner_bootstraps_on_sky_news_like_sourcepoint_fixture() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        top_frame_result = _scan_fixture(page, "sky_news_sourcepoint_like.html")
        merged = _scan_fixture_all_frames(page, "sky_news_sourcepoint_like.html")
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

    iframe_scans = [
        entry for entry in merged["frames"]
        if entry["frameUrl"].endswith("sourcepoint_iframe_inner.html")
    ]
    assert len(iframe_scans) == 1
    assert iframe_scans[0]["scanResult"]["bannerFound"] is True
    assert iframe_scans[0]["scanResult"]["cmpDetected"] == "Sourcepoint"
    assert iframe_scans[0]["scanResult"]["acceptButtonText"] == "Accept all"


def test_consent_scanner_records_direct_essential_action_in_local_session() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "sourcepoint_like.html").as_uri())
        _install_scanner(page)

        armed = page.evaluate(
            """() => AECCSConsentScanner.armInteractionAuditSession({
                baseline: {
                    totalCookies: 8,
                    thirdPartyCount: 2,
                    trackerCount: 1,
                    categoryCounts: { Advertising: 1, Functional: 2, Unknown: 5 },
                    cookieKeys: ["cmp|.example.com|/"],
                    score: {
                        kind: "gdpr_compliance",
                        label: "GDPR Compliance Score",
                        overall_score: 38,
                        grade: "F",
                        criteria: {}
                    },
                    consentScan: { bannerFound: true, cmpDetected: "Sourcepoint" }
                },
                frameId: 0
            })"""
        )
        page.click("button:has-text('Essential cookies only')")
        session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert armed["status"] == "armed"
    assert armed["watching"] is True
    assert session["status"] == "observed"
    assert session["watching"] is False
    assert session["action"]["type"] == "essential"
    assert session["action"]["text"] == "Essential cookies only"
    assert session["action"]["observed"] is True


def test_consent_scanner_records_direct_accept_action_in_local_session() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "sourcepoint_like.html").as_uri())
        _install_scanner(page)

        armed = page.evaluate(
            """() => AECCSConsentScanner.armInteractionAuditSession({
                baseline: {
                    totalCookies: 8,
                    thirdPartyCount: 2,
                    trackerCount: 1,
                    categoryCounts: { Advertising: 1, Functional: 2, Unknown: 5 },
                    cookieKeys: ["cmp|.example.com|/"],
                    score: {
                        kind: "gdpr_compliance",
                        label: "GDPR Compliance Score",
                        overall_score: 38,
                        grade: "F",
                        criteria: {}
                    },
                    consentScan: { bannerFound: true, cmpDetected: "Sourcepoint" }
                },
                frameId: 0,
                pageKey: "https://example.com/news"
            })"""
        )
        page.click("button:has-text('Accept all')")
        session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert armed["status"] == "armed"
    assert armed["watching"] is True
    assert session["status"] == "observed"
    assert session["watching"] is False
    assert session["action"]["type"] == "accept"
    assert session["action"]["text"] == "Accept all"
    assert session["action"]["observed"] is True
    assert session["pageKey"] == "https://example.com/news"


def test_consent_scanner_promotes_pending_accept_action_on_fast_teardown() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "sourcepoint_like.html").as_uri())
        _install_scanner(page)

        page.evaluate(
            """() => {
                AECCSConsentScanner.armInteractionAuditSession({
                    baseline: {
                        totalCookies: 8,
                        thirdPartyCount: 2,
                        trackerCount: 1,
                        categoryCounts: { Advertising: 1, Functional: 2, Unknown: 5 },
                        cookieKeys: ["cmp|.example.com|/"],
                        score: {
                            kind: "gdpr_compliance",
                            label: "GDPR Compliance Score",
                            overall_score: 38,
                            grade: "F",
                            criteria: {}
                        },
                        consentScan: { bannerFound: true, cmpDetected: "Sourcepoint" }
                    },
                    frameId: 4,
                    pageKey: "https://news.sky.com/"
                });

                const accept = document.querySelector("button.primary");
                accept.addEventListener("pointerdown", () => {
                    document.getElementById("sp_message_container_1").remove();
                    window.dispatchEvent(new Event("pagehide"));
                }, { once: true });
            }"""
        )

        page.locator("button:has-text('Accept all')").dispatch_event("pointerdown")
        session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert session["status"] == "observed"
    assert session["watching"] is False
    assert session["action"]["type"] == "accept"
    assert session["action"]["text"] == "Accept all"
    assert session["action"]["observed"] is False
    assert session["pageKey"] == "https://news.sky.com/"


def test_consent_scanner_keeps_watching_after_settings_click_until_final_action() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "settings_path_interaction.html").as_uri())
        _install_scanner(page)

        page.evaluate(
            """() => AECCSConsentScanner.armInteractionAuditSession({
                baseline: {
                    totalCookies: 4,
                    thirdPartyCount: 1,
                    trackerCount: 0,
                    categoryCounts: { Functional: 1, Unknown: 3 },
                    cookieKeys: [],
                    score: {
                        kind: "gdpr_compliance",
                        label: "GDPR Compliance Score",
                        overall_score: 52,
                        grade: "D",
                        criteria: {}
                    },
                    consentScan: { bannerFound: true, cmpDetected: null }
                },
                frameId: 0
            })"""
        )

        page.click("text=Manage Preferences")
        intermediate = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")

        page.click("text=Reject All")
        final_session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert intermediate["status"] == "armed"
    assert intermediate["watching"] is True
    assert intermediate["action"] is None

    assert final_session["status"] == "observed"
    assert final_session["watching"] is False
    assert final_session["action"]["type"] == "reject"
    assert final_session["action"]["text"] == "Reject All"


def test_consent_scanner_keeps_eksi_session_armed_after_manage_choices_click() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "eksisozluk_settings_interaction.html").as_uri())
        _install_scanner(page)

        page.evaluate(
            """() => AECCSConsentScanner.armInteractionAuditSession({
                baseline: {
                    totalCookies: 4,
                    thirdPartyCount: 1,
                    trackerCount: 0,
                    categoryCounts: { Functional: 1, Unknown: 3 },
                    cookieKeys: [],
                    score: {
                        kind: "gdpr_compliance",
                        label: "GDPR Compliance Score",
                        overall_score: 52,
                        grade: "D",
                        criteria: {}
                    },
                    consentScan: { bannerFound: true, cmpDetected: null }
                },
                frameId: 0
            })"""
        )

        page.click("text=Seçenekleri yönetin")
        session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert session["status"] == "armed"
    assert session["watching"] is True
    assert session["action"] is None


def test_consent_scanner_infers_essential_from_confirm_choices_when_all_toggles_off() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "eksisozluk_settings_interaction.html").as_uri())
        _install_scanner(page)

        page.evaluate(
            """() => AECCSConsentScanner.armInteractionAuditSession({
                baseline: {
                    totalCookies: 5,
                    thirdPartyCount: 2,
                    trackerCount: 1,
                    categoryCounts: { Advertising: 1, Functional: 1, Unknown: 3 },
                    cookieKeys: [],
                    score: {
                        kind: "gdpr_compliance",
                        label: "GDPR Compliance Score",
                        overall_score: 28,
                        grade: "F",
                        criteria: {}
                    },
                    consentScan: { bannerFound: true, cmpDetected: null }
                },
                frameId: 0,
                pageKey: "https://eksisozluk.com/"
            })"""
        )

        page.click("text=Seçenekleri yönetin")
        page.evaluate("""() => window.__eksiSettings.setAllPreferences(false)""")
        page.click("text=Seçimleri onayla")
        session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert session["status"] == "observed"
    assert session["watching"] is False
    assert session["action"]["type"] == "essential"
    assert session["action"]["text"] == "Seçimleri onayla"
    assert session["action"]["observed"] is True


def test_consent_scanner_infers_accept_from_confirm_choices_when_all_toggles_on() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "eksisozluk_settings_interaction.html").as_uri())
        _install_scanner(page)

        page.evaluate(
            """() => AECCSConsentScanner.armInteractionAuditSession({
                baseline: {
                    totalCookies: 5,
                    thirdPartyCount: 2,
                    trackerCount: 1,
                    categoryCounts: { Advertising: 1, Functional: 1, Unknown: 3 },
                    cookieKeys: [],
                    score: {
                        kind: "gdpr_compliance",
                        label: "GDPR Compliance Score",
                        overall_score: 28,
                        grade: "F",
                        criteria: {}
                    },
                    consentScan: { bannerFound: true, cmpDetected: null }
                },
                frameId: 0
            })"""
        )

        page.click("text=Seçenekleri yönetin")
        page.evaluate("""() => window.__eksiSettings.setAllPreferences(true)""")
        page.click("text=Seçimleri onayla")
        session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert session["status"] == "observed"
    assert session["watching"] is False
    assert session["action"]["type"] == "accept"
    assert session["action"]["text"] == "Seçimleri onayla"
    assert session["action"]["observed"] is True


def test_consent_scanner_marks_confirm_choices_unknown_when_toggle_state_is_mixed() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "eksisozluk_settings_interaction.html").as_uri())
        _install_scanner(page)

        page.evaluate(
            """() => AECCSConsentScanner.armInteractionAuditSession({
                baseline: {
                    totalCookies: 5,
                    thirdPartyCount: 2,
                    trackerCount: 1,
                    categoryCounts: { Advertising: 1, Functional: 1, Unknown: 3 },
                    cookieKeys: [],
                    score: {
                        kind: "gdpr_compliance",
                        label: "GDPR Compliance Score",
                        overall_score: 28,
                        grade: "F",
                        criteria: {}
                    },
                    consentScan: { bannerFound: true, cmpDetected: null }
                },
                frameId: 0
            })"""
        )

        page.click("text=Seçenekleri yönetin")
        page.evaluate("""() => window.__eksiSettings.setPreferenceStates([true, false, true])""")
        page.click("text=Seçimleri onayla")
        session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert session["status"] == "observed"
    assert session["watching"] is False
    assert session["action"]["type"] == "unknown"
    assert session["action"]["text"] == "Seçimleri onayla"
    assert session["action"]["observed"] is True


def test_consent_scanner_promotes_pending_confirm_choices_action_on_fast_teardown() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((FIXTURES / "eksisozluk_settings_interaction.html").as_uri())
        _install_scanner(page)

        page.evaluate(
            """() => {
                AECCSConsentScanner.armInteractionAuditSession({
                    baseline: {
                        totalCookies: 5,
                        thirdPartyCount: 2,
                        trackerCount: 1,
                        categoryCounts: { Advertising: 1, Functional: 1, Unknown: 3 },
                        cookieKeys: [],
                        score: {
                            kind: "gdpr_compliance",
                            label: "GDPR Compliance Score",
                            overall_score: 28,
                            grade: "F",
                            criteria: {}
                        },
                        consentScan: { bannerFound: true, cmpDetected: null }
                    },
                    frameId: 4,
                    pageKey: "https://eksisozluk.com/"
                });

                window.__eksiSettings.setAllPreferences(false);
                const confirm = document.getElementById("confirm-choices");
                confirm.addEventListener("pointerdown", () => {
                    document.getElementById("eksi-settings-modal").remove();
                    document.getElementById("eksi-consent-banner").remove();
                    window.dispatchEvent(new Event("pagehide"));
                }, { once: true });
            }"""
        )

        page.click("text=Seçenekleri yönetin")
        page.locator("#confirm-choices").dispatch_event("pointerdown")
        session = page.evaluate("""() => AECCSConsentScanner.getInteractionAuditSession()""")
        browser.close()

    assert session["status"] == "observed"
    assert session["watching"] is False
    assert session["action"]["type"] == "essential"
    assert session["action"]["text"] == "Seçimleri onayla"
    assert session["action"]["observed"] is False
    assert session["pageKey"] == "https://eksisozluk.com/"


def test_service_worker_reports_scanner_init_context_when_all_frames_fail() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        result = page.evaluate(
            """() => selectBestConsentScan([
                {
                    frameId: 0,
                    result: {
                        scanResult: null,
                        scanScore: -1,
                        error: "Consent scanner unavailable: stage=runtime; AECCS runtime unavailable. Load lib/tracker-data.js before content/consent-scanner.js.",
                        initStage: "runtime",
                        initError: "AECCS runtime unavailable. Load lib/tracker-data.js before content/consent-scanner.js."
                    }
                }
            ])"""
        )
        browser.close()

    assert "Content script unavailable in all frames" in result["error"]
    assert "stage=runtime" in result["error"]
    assert "AECCS runtime unavailable" in result["error"]


def test_service_worker_stages_injection_across_verified_frames() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("<!DOCTYPE html><html><body></body></html>")
        page.evaluate(
            """() => {
                window.__executeCalls = [];
                window.browser = {
                    runtime: {
                        onMessage: {
                            addListener() {}
                        }
                    },
                    scripting: {
                        executeScript: async request => {
                            window.__executeCalls.push({
                                target: request.target,
                                files: request.files || null,
                                hasFunc: !!request.func
                            });
                            const step = window.__executeCalls.length;
                            if (step === 1) return [];
                            if (step === 2) {
                                return [
                                    { frameId: 0, result: { hasSharedConfig: true, hasAECCSSharedConfig: true, sharedConfigKeys: 14, error: null } },
                                    { frameId: 2, result: { hasSharedConfig: true, hasAECCSSharedConfig: true, sharedConfigKeys: 14, error: null } }
                                ];
                            }
                            if (step === 3) return [];
                            if (step === 4) {
                                return [
                                    { frameId: 0, result: { hasAECCS: true, initStage: "ready", initError: null, error: null } },
                                    { frameId: 2, result: { hasAECCS: false, initStage: "runtime", initError: "AECCS runtime missing", error: "AECCS runtime missing" } }
                                ];
                            }
                            if (step === 5) return [];
                            if (step === 6) {
                                return [
                                    { frameId: 0, result: { hasScanner: true, initStage: "ready", initError: null, error: null } }
                                ];
                            }
                            if (step === 7) {
                                return [
                                    {
                                        frameId: 0,
                                        result: {
                                            scanResult: {
                                                cmpDetected: "Sourcepoint",
                                                bannerFound: true,
                                                hasAcceptButton: true,
                                                hasRejectButton: true,
                                                hasSettingsButton: true,
                                                acceptButtonText: "Accept all",
                                                rejectButtonText: "Essential cookies only",
                                                settingsButtonText: "View options",
                                                acceptClicksRequired: 1,
                                                rejectClicksRequired: 1,
                                                darkPatterns: { count: 0, detected: [] }
                                            },
                                            scanScore: 14,
                                            initStage: "ready",
                                            initError: null
                                        }
                                    }
                                ];
                            }
                            throw new Error(`Unexpected executeScript step ${step}`);
                        }
                    }
                };
            }"""
        )
        page.add_script_tag(path=str(SERVICE_WORKER))
        payload = page.evaluate(
            """async () => ({
                result: await scanConsentAcrossFrames(123),
                calls: window.__executeCalls
            })"""
        )
        browser.close()

    assert payload["result"]["bannerFound"] is True
    assert payload["result"]["cmpDetected"] == "Sourcepoint"
    assert payload["result"]["acceptButtonText"] == "Accept all"
    assert payload["result"]["rejectButtonText"] == "Essential cookies only"

    calls = payload["calls"]
    assert calls[0]["files"] == ["lib/browser-polyfill.js", "lib/study-snapshot.js", "lib/shared-config.js"]
    assert calls[1]["target"]["allFrames"] is True
    assert calls[2]["files"] == ["lib/tracker-data.js"]
    assert calls[2]["target"]["frameIds"] == [0, 2]
    assert calls[4]["files"] == ["content/consent-scanner.js"]
    assert calls[4]["target"]["frameIds"] == [0]
    assert calls[6]["hasFunc"] is True
    assert calls[6]["target"]["frameIds"] == [0]


def test_service_worker_reports_shared_config_stage_error_when_unavailable() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("<!DOCTYPE html><html><body></body></html>")
        page.evaluate(
            """() => {
                let step = 0;
                window.browser = {
                    runtime: {
                        onMessage: {
                            addListener() {}
                        }
                    },
                    scripting: {
                        executeScript: async request => {
                            step += 1;
                            if (step === 1) return [];
                            if (step === 2) {
                                return [
                                    { frameId: 0, result: { hasSharedConfig: false, hasAECCSSharedConfig: false, sharedConfigKeys: 0, error: "AECCSSharedConfig missing" } },
                                    { frameId: 1, result: { hasSharedConfig: false, hasAECCSSharedConfig: false, sharedConfigKeys: 0, error: "AECCSSharedConfig missing" } }
                                ];
                            }
                            throw new Error(`Unexpected executeScript step ${step}`);
                        }
                    }
                };
            }"""
        )
        page.add_script_tag(path=str(SERVICE_WORKER))
        result = page.evaluate("""async () => await scanConsentAcrossFrames(55)""")
        browser.close()

    assert "shared config unavailable in all frames" in result["error"]
    assert "AECCSSharedConfig missing" in result["error"]


def test_service_worker_returns_post_interaction_analysis_when_current_state_is_meaningful() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        result = page.evaluate(
            """async () => {
                browser.tabs = {
                    get: async () => ({ id: 5, url: "https://news.sky.com" })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0] });
                runConsentScanAcrossReadyFrames = async () => ({
                    error: null,
                    frameId: 0,
                    scanResult: {
                        cmpDetected: "Sourcepoint",
                        bannerFound: false,
                        hasAcceptButton: false,
                        hasRejectButton: false,
                        hasSettingsButton: false,
                        acceptButtonText: null,
                        rejectButtonText: null,
                        settingsButtonText: null,
                        acceptClicksRequired: 999,
                        rejectClicksRequired: 999,
                        transparency: {},
                        darkPatterns: { count: 0, detected: [] },
                        buttonComparison: null
                    }
                });
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["cmp|news.sky.com|/", "pref|news.sky.com|/"],
                    classifiedCookies: [
                        { name: "cmp", domain: "news.sky.com", path: "/", category: "Functional", is_tracker: false, vendor: "First Party" },
                        { name: "pref", domain: "news.sky.com", path: "/", category: "Unknown", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 2,
                    categoryCounts: { Functional: 1, Unknown: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getBestInteractionAuditSession = async () => ({
                    status: "completed",
                    action: {
                        type: "essential",
                        text: "Essential cookies only",
                        observed: true,
                        observedAt: "2026-04-16T10:00:00.000Z"
                    },
                    baseline: {
                        totalCookies: 8,
                        thirdPartyCount: 2,
                        trackerCount: 1,
                        categoryCounts: { Advertising: 1, Functional: 2, Unknown: 5 },
                        cookieKeys: ["cmp|news.sky.com|/", "pref|news.sky.com|/"],
                        score: {
                            kind: "gdpr_compliance",
                            label: "GDPR Compliance Score",
                            overall_score: 38,
                            grade: "F",
                            criteria: {}
                        },
                        consentScan: {
                            cmpDetected: "Sourcepoint",
                            bannerFound: true,
                            hasAcceptButton: true,
                            hasRejectButton: true,
                            hasSettingsButton: true,
                            acceptButtonText: "Accept all",
                            rejectButtonText: "Essential cookies only",
                            settingsButtonText: "View options",
                            acceptClicksRequired: 1,
                            rejectClicksRequired: 1,
                            transparency: {},
                            darkPatterns: { count: 0, detected: [] },
                            buttonComparison: null
                        }
                    },
                    current: null,
                    delta: null,
                    honesty: { verdict: "unknown", findings: [] },
                    frameId: 0,
                    updatedAt: "2026-04-16T10:00:04.000Z"
                });

                return await handleAnalyze(5);
            }"""
        )
        browser.close()

    assert result["analysisMode"] == "post_interaction"
    assert result["score"]["kind"] == "state_outcome"
    assert result["baselineScore"]["kind"] == "gdpr_compliance"
    assert result["interactionAudit"]["status"] == "completed"
    assert result["interactionAudit"]["action"]["type"] == "essential"
    assert result["interactionAudit"]["honesty"]["verdict"] == "mixed"
    assert result["consentScan"]["bannerFound"] is False
    assert result["evaluationDisabled"] is None


def test_service_worker_returns_unknown_current_state_when_popup_opens_after_click() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        result = page.evaluate(
            """async () => {
                browser.tabs = {
                    get: async () => ({ id: 6, url: "https://example.com" })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0] });
                runConsentScanAcrossReadyFrames = async () => ({
                    error: null,
                    frameId: 0,
                    successfulFrameIds: [0],
                    timedOutFrameIds: [],
                    scanResult: {
                        cmpDetected: null,
                        bannerFound: false,
                        hasAcceptButton: false,
                        hasRejectButton: false,
                        hasSettingsButton: false,
                        acceptButtonText: null,
                        rejectButtonText: null,
                        settingsButtonText: null,
                        acceptClicksRequired: 999,
                        rejectClicksRequired: 999,
                        transparency: {},
                        darkPatterns: { count: 0, detected: [] },
                        buttonComparison: null
                    }
                });
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["sess|example.com|/"],
                    classifiedCookies: [
                        { name: "sess", domain: "example.com", path: "/", category: "Unknown", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 1,
                    categoryCounts: { Unknown: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getBestInteractionAuditSession = async () => null;

                return await handleAnalyze(6);
            }"""
        )
        browser.close()

    assert result["analysisMode"] == "post_interaction"
    assert result["baselineScore"] is None
    assert result["interactionAudit"]["status"] == "unknown_current_state"
    assert result["interactionAudit"]["action"]["type"] == "unknown"
    assert result["interactionAudit"]["baseline"] is None


def test_service_worker_does_not_return_post_interaction_when_only_subframes_scan_successfully() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        result = page.evaluate(
            """async () => {
                browser.tabs = {
                    get: async () => ({ id: 62, url: "https://eksisozluk.com/baslik" })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0, 7] });
                runConsentScanAcrossReadyFrames = async () => ({
                    error: null,
                    frameId: 7,
                    successfulFrameIds: [7],
                    timedOutFrameIds: [0],
                    scanResult: {
                        cmpDetected: null,
                        bannerFound: false,
                        hasAcceptButton: false,
                        hasRejectButton: false,
                        hasSettingsButton: false,
                        acceptButtonText: null,
                        rejectButtonText: null,
                        settingsButtonText: null,
                        acceptClicksRequired: 999,
                        rejectClicksRequired: 999,
                        transparency: {},
                        darkPatterns: { count: 0, detected: [] },
                        buttonComparison: null
                    }
                });
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["cmp_saved|eksisozluk.com|/"],
                    classifiedCookies: [
                        { name: "cmp_saved", domain: "eksisozluk.com", path: "/", category: "Functional", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 1,
                    categoryCounts: { Functional: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getBestInteractionAuditSession = async () => null;

                return await handleAnalyze(62);
            }"""
        )
        browser.close()

    assert "error" in result
    assert result.get("analysisMode") != "post_interaction"


def test_service_worker_does_not_return_post_interaction_when_scan_fails_without_interaction_evidence() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        result = page.evaluate(
            """async () => {
                browser.tabs = {
                    get: async () => ({ id: 61, url: "https://example.com" })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0] });
                runConsentScanAcrossReadyFrames = async () => ({
                    error: "Content script unavailable: scanner runtime lost",
                    frameId: null,
                    scanResult: null
                });
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["sess|example.com|/"],
                    classifiedCookies: [
                        { name: "sess", domain: "example.com", path: "/", category: "Unknown", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 1,
                    categoryCounts: { Unknown: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getBestInteractionAuditSession = async () => null;

                return await handleAnalyze(61);
            }"""
        )
        browser.close()

    assert "error" in result
    assert result.get("analysisMode") != "post_interaction"


def test_service_worker_returns_accept_action_from_background_session_store() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        result = page.evaluate(
            """async () => {
                const url = "https://news.sky.com/world?edition=uk";
                const pageKey = buildPageKey(url);
                const now = new Date();
                const recent = new Date(now.getTime() - 1000).toISOString();
                const updatedAt = now.toISOString();

                browser.tabs = {
                    get: async () => ({ id: 10, url })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0] });
                runConsentScanAcrossReadyFrames = async () => ({
                    error: null,
                    frameId: 0,
                    scanResult: {
                        cmpDetected: "Sourcepoint",
                        bannerFound: false,
                        hasAcceptButton: false,
                        hasRejectButton: false,
                        hasSettingsButton: false,
                        acceptButtonText: null,
                        rejectButtonText: null,
                        settingsButtonText: null,
                        acceptClicksRequired: 999,
                        rejectClicksRequired: 999,
                        transparency: {},
                        darkPatterns: { count: 0, detected: [] },
                        buttonComparison: null
                    }
                });
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["cmp|news.sky.com|/", "prefs|news.sky.com|/"],
                    classifiedCookies: [
                        { name: "cmp", domain: "news.sky.com", path: "/", category: "Functional", is_tracker: false, vendor: "First Party" },
                        { name: "prefs", domain: "news.sky.com", path: "/", category: "Unknown", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 2,
                    categoryCounts: { Functional: 1, Unknown: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getInteractionAuditSessionsFromFrames = async () => [];
                syncInteractionAuditSessionToTopFrame = async () => null;

                    persistInteractionSession(10, pageKey, {
                        status: "completed",
                        action: {
                            type: "accept",
                            text: "Accept all",
                            observed: true,
                            observedAt: recent
                        },
                    baseline: {
                        totalCookies: 8,
                        thirdPartyCount: 2,
                        trackerCount: 1,
                        cookieKeys: ["cmp|news.sky.com|/"],
                        score: {
                            kind: "gdpr_compliance",
                            label: "GDPR Compliance Score",
                            overall_score: 38,
                            grade: "F",
                            criteria: {}
                        },
                        consentScan: {
                            cmpDetected: "Sourcepoint",
                            bannerFound: true,
                            hasAcceptButton: true,
                            hasRejectButton: true,
                            hasSettingsButton: true,
                            acceptButtonText: "Accept all",
                            rejectButtonText: "Essential cookies only",
                            settingsButtonText: "View options",
                            acceptClicksRequired: 1,
                            rejectClicksRequired: 1,
                            transparency: {},
                            darkPatterns: { count: 0, detected: [] },
                            buttonComparison: null
                        }
                    },
                    current: null,
                    delta: null,
                        honesty: {
                            verdict: "not_applicable",
                            findings: ["Honesty checks are only applied to reject or essential-only outcomes."]
                        },
                        frameId: 2,
                        updatedAt
                    }, 2);

                return await handleAnalyze(10);
            }"""
        )
        browser.close()

    assert result["analysisMode"] == "post_interaction"
    assert result["interactionAudit"]["status"] == "completed"
    assert result["interactionAudit"]["action"]["type"] == "accept"
    assert result["interactionAudit"]["action"]["text"] == "Accept all"
    assert result["interactionAudit"]["action"]["observed"] is True
    assert result["interactionAudit"]["honesty"]["verdict"] == "not_applicable"


def test_service_worker_clears_interaction_session_for_tab_and_frames() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        payload = page.evaluate(
            """async () => {
                const url = "https://example.com";
                const pageKey = buildPageKey(url);
                const now = new Date().toISOString();

                persistInteractionSession(31, pageKey, {
                    status: "completed",
                    action: {
                        type: "accept",
                        text: "Accept all",
                        observed: true,
                        observedAt: now
                    },
                    updatedAt: now
                }, 0);

                window.__clearedFrameIds = [];
                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0, 2] });
                browser.scripting = {
                    executeScript: async request => {
                        const frameId = request.target.frameIds[0];
                        window.__clearedFrameIds.push(frameId);
                        return [{ frameId, result: null }];
                    }
                };

                const response = await handleClearInteractionSession(31);
                return {
                    response,
                    stored: getStoredInteractionSession(31, pageKey),
                    clearedFrames: window.__clearedFrameIds
                };
            }"""
        )
        browser.close()

    assert payload["response"] == {"ok": True}
    assert payload["stored"] is None
    assert payload["clearedFrames"] == [0, 2]


def test_service_worker_inject_and_verify_stage_times_out_with_stage_error() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page, {"frameStage": 20})
        result = page.evaluate(
            """async () => {
                browser.scripting = {
                    executeScript: async () => new Promise(() => {})
                };

                return await injectAndVerifyStage(
                    5,
                    [0],
                    ["lib/shared-config.js"],
                    "Shared config",
                    () => ({ hasSharedConfig: Boolean(globalThis.AECCSSharedConfig) }),
                    probe => probe.hasSharedConfig === true
                );
            }"""
        )
        browser.close()

    assert "Shared config unavailable in all frames" in result["error"]
    assert "timed out" in result["error"].lower()


def test_service_worker_falls_back_to_stored_session_when_consent_scan_times_out() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(
            page,
            {
                "analyzeTotal": 120,
                "consentScan": 20,
                "cookieRead": 20,
                "sessionRead": 20,
            },
        )
        result = page.evaluate(
            """async () => {
                const url = "https://news.sky.com/world";
                const pageKey = buildPageKey(url);
                const now = new Date().toISOString();

                browser.tabs = {
                    get: async () => ({ id: 21, url })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0] });
                runConsentScanAcrossReadyFrames = async () => new Promise(() => {});
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["cmp|news.sky.com|/", "pref|news.sky.com|/"],
                    classifiedCookies: [
                        { name: "cmp", domain: "news.sky.com", path: "/", category: "Functional", is_tracker: false, vendor: "First Party" },
                        { name: "pref", domain: "news.sky.com", path: "/", category: "Unknown", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 2,
                    categoryCounts: { Functional: 1, Unknown: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getBestInteractionAuditSession = async () => ({
                    status: "completed",
                    pageKey,
                    action: {
                        type: "accept",
                        text: "Accept all",
                        observed: true,
                        observedAt: now
                    },
                    baseline: {
                        totalCookies: 7,
                        thirdPartyCount: 2,
                        trackerCount: 1,
                        cookieKeys: ["cmp|news.sky.com|/"],
                        score: {
                            kind: "gdpr_compliance",
                            label: "GDPR Compliance Score",
                            overall_score: 42,
                            grade: "F",
                            criteria: {}
                        },
                        consentScan: {
                            cmpDetected: "Sourcepoint",
                            bannerFound: true,
                            hasAcceptButton: true,
                            hasRejectButton: true,
                            hasSettingsButton: true,
                            acceptButtonText: "Accept all",
                            rejectButtonText: "Essential cookies only",
                            settingsButtonText: "View options",
                            acceptClicksRequired: 1,
                            rejectClicksRequired: 1,
                            transparency: {},
                            darkPatterns: { count: 0, detected: [] },
                            buttonComparison: null
                        }
                    },
                    current: null,
                    delta: null,
                    honesty: {
                        verdict: "not_applicable",
                        findings: ["Honesty checks are only applied to reject or essential-only outcomes."]
                    },
                    frameId: 0,
                    updatedAt: now
                });

                return await handleAnalyze(21);
            }"""
        )
        browser.close()

    assert result["analysisMode"] == "post_interaction"
    assert result["interactionAudit"]["status"] == "completed"
    assert result["interactionAudit"]["action"]["type"] == "accept"
    assert result["score"]["kind"] == "state_outcome"


def test_service_worker_returns_unknown_current_state_when_consent_scan_times_out_without_session() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(
            page,
            {
                "analyzeTotal": 120,
                "consentScan": 20,
                "cookieRead": 20,
                "sessionRead": 20,
            },
        )
        result = page.evaluate(
            """async () => {
                const url = "https://example.com/article";

                browser.tabs = {
                    get: async () => ({ id: 22, url })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0] });
                runConsentScanAcrossReadyFrames = async () => new Promise(() => {});
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["pref|example.com|/"],
                    classifiedCookies: [
                        { name: "pref", domain: "example.com", path: "/", category: "Unknown", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 1,
                    categoryCounts: { Unknown: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getBestInteractionAuditSession = async () => null;

                return await handleAnalyze(22);
            }"""
        )
        browser.close()

    assert "error" in result
    assert result.get("analysisMode") != "post_interaction"


def test_service_worker_returns_explicit_timeout_error_when_no_fallback_is_available() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(
            page,
            {
                "analyzeTotal": 120,
                "consentScan": 20,
                "cookieRead": 20,
                "sessionRead": 20,
            },
        )
        result = page.evaluate(
            """async () => {
                const url = "https://example.com/plain";

                browser.tabs = {
                    get: async () => ({ id: 23, url })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0] });
                runConsentScanAcrossReadyFrames = async () => ({
                    error: null,
                    frameId: 0,
                    scanResult: {
                        cmpDetected: null,
                        bannerFound: false,
                        hasAcceptButton: false,
                        hasRejectButton: false,
                        hasSettingsButton: false,
                        acceptButtonText: null,
                        rejectButtonText: null,
                        settingsButtonText: null,
                        acceptClicksRequired: 999,
                        rejectClicksRequired: 999,
                        transparency: {},
                        darkPatterns: { count: 0, detected: [] },
                        buttonComparison: null
                    }
                });
                readCurrentSiteSnapshot = async () => new Promise(() => {});
                getBestInteractionAuditSession = async () => null;

                return await handleAnalyze(23);
            }"""
        )
        browser.close()

    assert result["error"] == (
        "Analysis timed out on this page before AECCS could finish scanning. Try reopening the popup."
    )


def test_service_worker_dead_frame_and_timeout_fallback_do_not_surface_raw_frame_errors() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(
            page,
            {
                "analyzeTotal": 120,
                "consentScan": 20,
                "cookieRead": 20,
                "sessionRead": 20,
            },
        )
        result = page.evaluate(
            """async () => {
                const url = "https://eksisozluk.com/baslik";
                const pageKey = buildPageKey(url);
                const now = new Date().toISOString();

                browser.tabs = {
                    get: async () => ({ id: 24, url })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0, 77] });
                runConsentScanAcrossReadyFrames = async () => new Promise(() => {});
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["cmp_saved|eksisozluk.com|/"],
                    classifiedCookies: [
                        { name: "cmp_saved", domain: "eksisozluk.com", path: "/", category: "Functional", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 1,
                    categoryCounts: { Functional: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getInteractionAuditSessionsFromFrames = async () => {
                    throw new Error("No frame with id 77 in tab with id 24");
                };
                syncInteractionAuditSessionToTopFrame = async () => null;

                persistInteractionSession(24, pageKey, {
                    status: "completed",
                    action: {
                        type: "essential",
                        text: "Seçimleri onayla",
                        observed: false,
                        observedAt: now
                    },
                    baseline: {
                        totalCookies: 6,
                        thirdPartyCount: 2,
                        trackerCount: 1,
                        cookieKeys: ["cmp|eksisozluk.com|/"],
                        score: {
                            kind: "gdpr_compliance",
                            label: "GDPR Compliance Score",
                            overall_score: 41,
                            grade: "F",
                            criteria: {}
                        },
                        consentScan: {
                            cmpDetected: "Funding Choices",
                            bannerFound: true,
                            hasAcceptButton: true,
                            hasRejectButton: false,
                            hasSettingsButton: true,
                            acceptButtonText: "İzin ver",
                            rejectButtonText: null,
                            settingsButtonText: "Seçenekleri yönetin",
                            acceptClicksRequired: 1,
                            rejectClicksRequired: 2,
                            transparency: {},
                            darkPatterns: { count: 1, detected: ["Missing reject option"] },
                            buttonComparison: null
                        }
                    },
                    current: null,
                    delta: null,
                    honesty: {
                        verdict: "mixed",
                        findings: ["Only functional or unknown cookies remained after essential-only action."]
                    },
                    frameId: 77,
                    updatedAt: now
                }, 77);

                return await handleAnalyze(24);
            }"""
        )
        browser.close()

    assert result["analysisMode"] == "post_interaction"
    assert result["interactionAudit"]["action"]["type"] == "essential"
    assert "error" not in result


def test_service_worker_returns_accept_action_from_top_frame_mirror_when_background_is_empty() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        payload = page.evaluate(
            """async () => {
                const url = "https://news.sky.com/world";
                const pageKey = buildPageKey(url);
                const now = new Date();
                const recent = new Date(now.getTime() - 1000).toISOString();
                const updatedAt = now.toISOString();

                browser.tabs = {
                    get: async () => ({ id: 11, url })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0, 2] });
                runConsentScanAcrossReadyFrames = async () => ({
                    error: null,
                    frameId: 0,
                    scanResult: {
                        cmpDetected: "Sourcepoint",
                        bannerFound: false,
                        hasAcceptButton: false,
                        hasRejectButton: false,
                        hasSettingsButton: false,
                        acceptButtonText: null,
                        rejectButtonText: null,
                        settingsButtonText: null,
                        acceptClicksRequired: 999,
                        rejectClicksRequired: 999,
                        transparency: {},
                        darkPatterns: { count: 0, detected: [] },
                        buttonComparison: null
                    }
                });
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["cmp|news.sky.com|/", "prefs|news.sky.com|/"],
                    classifiedCookies: [
                        { name: "cmp", domain: "news.sky.com", path: "/", category: "Functional", is_tracker: false, vendor: "First Party" },
                        { name: "prefs", domain: "news.sky.com", path: "/", category: "Unknown", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 2,
                    categoryCounts: { Functional: 1, Unknown: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getInteractionAuditSessionsFromFrames = async () => [
                    {
                        frameId: 0,
                        status: "completed",
                        pageKey,
                        action: {
                            type: "accept",
                            text: "Accept all",
                            observed: true,
                            observedAt: recent
                        },
                        baseline: {
                            totalCookies: 8,
                            thirdPartyCount: 2,
                            trackerCount: 1,
                            cookieKeys: ["cmp|news.sky.com|/"],
                            score: {
                                kind: "gdpr_compliance",
                                label: "GDPR Compliance Score",
                                overall_score: 38,
                                grade: "F",
                                criteria: {}
                            },
                            consentScan: {
                                cmpDetected: "Sourcepoint",
                                bannerFound: true,
                                hasAcceptButton: true,
                                hasRejectButton: true,
                                hasSettingsButton: true,
                                acceptButtonText: "Accept all",
                                rejectButtonText: "Essential cookies only",
                                settingsButtonText: "View options",
                                acceptClicksRequired: 1,
                                rejectClicksRequired: 1,
                                transparency: {},
                                darkPatterns: { count: 0, detected: [] },
                                buttonComparison: null
                            }
                        },
                        current: null,
                        delta: null,
                        honesty: {
                            verdict: "not_applicable",
                            findings: ["Honesty checks are only applied to reject or essential-only outcomes."]
                        },
                        updatedAt
                    }
                ];
                syncInteractionAuditSessionToTopFrame = async (_tabId, session) => {
                    window.__topFrameSync = session;
                    return session;
                };

                const result = await handleAnalyze(11);
                return {
                    result,
                    stored: getStoredInteractionSession(11, pageKey),
                    synced: window.__topFrameSync
                };
            }"""
        )
        browser.close()

    result = payload["result"]
    assert result["analysisMode"] == "post_interaction"
    assert result["interactionAudit"]["action"]["type"] == "accept"
    assert result["interactionAudit"]["action"]["text"] == "Accept all"
    assert payload["stored"]["action"]["type"] == "accept"
    assert payload["synced"]["action"]["type"] == "accept"


def test_service_worker_ignores_dead_frames_when_collecting_interaction_sessions() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        sessions = page.evaluate(
            """async () => {
                browser.scripting = {
                    executeScript: async request => {
                        const frameId = request.target.frameIds[0];
                        if (frameId === 77) {
                            throw new Error("No frame with id 77 in tab with id 5");
                        }
                        return [{
                            frameId,
                            result: {
                                status: "completed",
                                pageKey: "https://eksisozluk.com/",
                                action: {
                                    type: "essential",
                                    text: "Seçimleri onayla",
                                    observed: false,
                                    observedAt: "2026-04-16T13:00:00.000Z"
                                },
                                updatedAt: "2026-04-16T13:00:01.000Z"
                            }
                        }];
                    }
                };

                return await getInteractionAuditSessionsFromFrames(5, [77, 0]);
            }"""
        )
        browser.close()

    assert len(sessions) == 1
    assert sessions[0]["frameId"] == 0
    assert sessions[0]["action"]["type"] == "essential"
    assert sessions[0]["action"]["text"] == "Seçimleri onayla"


def test_service_worker_handle_analyze_degrades_cleanly_when_dead_frame_lookup_fails() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        result = page.evaluate(
            """async () => {
                const url = "https://eksisozluk.com/baslik";
                const pageKey = buildPageKey(url);
                const now = new Date();
                const recent = new Date(now.getTime() - 1000).toISOString();
                const updatedAt = now.toISOString();

                browser.tabs = {
                    get: async () => ({ id: 13, url })
                };

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0, 77] });
                runConsentScanAcrossReadyFrames = async () => ({
                    error: null,
                    frameId: 0,
                    scanResult: {
                        cmpDetected: "Funding Choices",
                        bannerFound: false,
                        hasAcceptButton: false,
                        hasRejectButton: false,
                        hasSettingsButton: false,
                        acceptButtonText: null,
                        rejectButtonText: null,
                        settingsButtonText: null,
                        acceptClicksRequired: 999,
                        rejectClicksRequired: 999,
                        transparency: {},
                        darkPatterns: { count: 0, detected: [] },
                        buttonComparison: null
                    }
                });
                readCurrentSiteSnapshot = async () => ({
                    cookies: [],
                    cookieKeys: ["cmp_saved|eksisozluk.com|/", "consent_mode|eksisozluk.com|/"],
                    classifiedCookies: [
                        { name: "cmp_saved", domain: "eksisozluk.com", path: "/", category: "Functional", is_tracker: false, vendor: "First Party" },
                        { name: "consent_mode", domain: "eksisozluk.com", path: "/", category: "Unknown", is_tracker: false, vendor: "First Party" }
                    ],
                    totalCookies: 2,
                    categoryCounts: { Functional: 1, Unknown: 1 },
                    trackersByVendor: {},
                    trackerCount: 0,
                    thirdPartyCount: 0
                });
                getInteractionAuditSessionsFromFrames = async () => {
                    throw new Error("No frame with id 77 in tab with id 13");
                };
                syncInteractionAuditSessionToTopFrame = async () => null;

                persistInteractionSession(13, pageKey, {
                    status: "completed",
                    action: {
                        type: "essential",
                        text: "Seçimleri onayla",
                        observed: false,
                        observedAt: recent
                    },
                    baseline: {
                        totalCookies: 6,
                        thirdPartyCount: 2,
                        trackerCount: 1,
                        cookieKeys: ["cmp|eksisozluk.com|/"],
                        score: {
                            kind: "gdpr_compliance",
                            label: "GDPR Compliance Score",
                            overall_score: 41,
                            grade: "F",
                            criteria: {}
                        },
                        consentScan: {
                            cmpDetected: "Funding Choices",
                            bannerFound: true,
                            hasAcceptButton: true,
                            hasRejectButton: false,
                            hasSettingsButton: true,
                            acceptButtonText: "İzin ver",
                            rejectButtonText: null,
                            settingsButtonText: "Seçenekleri yönetin",
                            acceptClicksRequired: 1,
                            rejectClicksRequired: 2,
                            transparency: {},
                            darkPatterns: { count: 1, detected: ["Missing reject option"] },
                            buttonComparison: null
                        }
                    },
                    current: null,
                    delta: null,
                    honesty: {
                        verdict: "mixed",
                        findings: ["Only functional or unknown cookies remained after the restrictive choice."]
                    },
                    frameId: 77,
                    updatedAt
                }, 77);

                return await handleAnalyze(13);
            }"""
        )
        browser.close()

    assert "error" not in result
    assert result["analysisMode"] == "post_interaction"
    assert result["interactionAudit"]["status"] == "completed"
    assert result["interactionAudit"]["action"]["type"] == "essential"
    assert result["interactionAudit"]["action"]["text"] == "Seçimleri onayla"


def test_service_worker_selects_richest_captured_post_interaction_outcome() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        payload = page.evaluate(
            """async () => {
                sleep = async () => {};
                let index = 0;
                const captures = [
                    { status: "completed", current: { totalCookies: 1, thirdPartyCount: 0, trackerCount: 0, capturedAt: "2026-04-16T10:00:00.000Z" } },
                    { status: "completed", current: { totalCookies: 3, thirdPartyCount: 1, trackerCount: 0, capturedAt: "2026-04-16T10:00:01.000Z" } },
                    { status: "completed", current: { totalCookies: 4, thirdPartyCount: 2, trackerCount: 1, capturedAt: "2026-04-16T10:00:02.000Z" } }
                ];

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0] });
                syncInteractionAuditSessionToTopFrame = async () => null;
                capturePostInteractionAudit = async () => captures[index++];
                window.__storedOutcome = null;
                storeInteractionOutcomeForFrame = async (_tabId, _frameId, interactionAudit) => {
                    window.__storedOutcome = interactionAudit;
                    return interactionAudit;
                };

                const result = await handleConsentInteractionObserved(
                    {
                        session: {
                            status: "observed",
                            action: { type: "reject", text: "Reject All", observed: true, observedAt: "2026-04-16T10:00:00.000Z" }
                        }
                    },
                    {
                        tab: { id: 9, url: "https://example.com" },
                        frameId: 2
                    }
                );

                return { result, stored: window.__storedOutcome };
            }"""
        )
        browser.close()

    assert payload["result"]["ok"] is True
    assert payload["stored"]["current"]["trackerCount"] == 1
    assert payload["stored"]["current"]["thirdPartyCount"] == 2
    assert payload["stored"]["current"]["totalCookies"] == 4


def test_service_worker_persists_accept_session_even_if_original_banner_frame_is_gone() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _install_service_worker_harness(page)
        payload = page.evaluate(
            """async () => {
                sleep = async () => {};
                const url = "https://news.sky.com/world";
                const pageKey = buildPageKey(url);

                ensureScannerRuntimeAcrossFrames = async () => ({ error: null, frameIds: [0, 2] });
                capturePostInteractionAudit = async () => ({
                    status: "observed",
                    action: {
                        type: "accept",
                        text: "Accept all",
                        observed: true,
                        observedAt: "2026-04-16T13:00:00.000Z"
                    },
                    baseline: {
                        totalCookies: 8,
                        thirdPartyCount: 2,
                        trackerCount: 1,
                        cookieKeys: ["cmp|news.sky.com|/"],
                        score: {
                            kind: "gdpr_compliance",
                            label: "GDPR Compliance Score",
                            overall_score: 38,
                            grade: "F",
                            criteria: {}
                        },
                        consentScan: {
                            cmpDetected: "Sourcepoint",
                            bannerFound: true,
                            hasAcceptButton: true,
                            hasRejectButton: true,
                            hasSettingsButton: true,
                            acceptButtonText: "Accept all",
                            rejectButtonText: "Essential cookies only",
                            settingsButtonText: "View options",
                            acceptClicksRequired: 1,
                            rejectClicksRequired: 1,
                            transparency: {},
                            darkPatterns: { count: 0, detected: [] },
                            buttonComparison: null
                        }
                    },
                    current: {
                        totalCookies: 30,
                        thirdPartyCount: 0,
                        trackerCount: 0,
                        capturedAt: "2026-04-16T13:00:03.000Z"
                    },
                    delta: {
                        totalCookies: 22,
                        thirdPartyCount: -2,
                        trackerCount: -1,
                        newCookies: [],
                        newTrackers: []
                    },
                    honesty: {
                        verdict: "not_applicable",
                        findings: ["Honesty checks are only applied to reject or essential-only outcomes."]
                    }
                });
                window.__topFrameSync = null;
                syncInteractionAuditSessionToTopFrame = async (_tabId, session) => {
                    window.__topFrameSync = session;
                    return session;
                };
                storeInteractionOutcomeForFrame = async () => {
                    throw new Error("frame gone");
                };

                const result = await handleConsentInteractionObserved(
                    {
                        session: {
                            status: "observed",
                            pageKey,
                            action: {
                                type: "accept",
                                text: "Accept all",
                                observed: true,
                                observedAt: "2026-04-16T13:00:00.000Z"
                            },
                            baseline: {
                                totalCookies: 8,
                                thirdPartyCount: 2,
                                trackerCount: 1,
                                cookieKeys: ["cmp|news.sky.com|/"],
                                score: {
                                    kind: "gdpr_compliance",
                                    label: "GDPR Compliance Score",
                                    overall_score: 38,
                                    grade: "F",
                                    criteria: {}
                                },
                                consentScan: { bannerFound: true, cmpDetected: "Sourcepoint" }
                            },
                            updatedAt: "2026-04-16T13:00:00.000Z"
                        }
                    },
                    {
                        tab: { id: 12, url },
                        frameId: 2
                    }
                );

                return {
                    result,
                    stored: getStoredInteractionSession(12, pageKey),
                    synced: window.__topFrameSync
                };
            }"""
        )
        browser.close()

    assert payload["result"]["ok"] is True
    assert payload["stored"]["status"] == "completed"
    assert payload["stored"]["action"]["type"] == "accept"
    assert payload["stored"]["action"]["text"] == "Accept all"
    assert payload["stored"]["current"]["totalCookies"] == 30
    assert payload["synced"]["status"] == "completed"
    assert payload["synced"]["action"]["type"] == "accept"


def test_extension_background_analyze_succeeds_on_sky_news_fixture_when_supported() -> None:
    with sync_playwright() as p:
        with _serve_fixture_dir(FIXTURES) as base_url:
            context = _launch_extension_context_or_skip(p)
            try:
                page = context.new_page()
                page.goto(f"{base_url}/sky_news_sourcepoint_like.html", wait_until="domcontentloaded")
                page.bring_to_front()
                service_worker = _get_extension_service_worker(context)
                result = service_worker.evaluate(
                    """async () => {
                        const tabs = await browser.tabs.query({ active: true, currentWindow: true });
                        const tabId = tabs[0]?.id;
                        return await handleAnalyze(tabId);
                    }"""
                )
            finally:
                context.close()

    assert result["analysisMode"] == "baseline_banner"
    assert result["consentScan"]["cmpDetected"] == "Sourcepoint"
    assert result["consentScan"]["bannerFound"] is True
    assert result["consentScan"]["acceptButtonText"] == "Accept all"
    assert result["consentScan"]["rejectButtonText"] == "Essential cookies only"
    assert result["consentScan"]["settingsButtonText"] == "View options"
    assert result["score"]["kind"] == "gdpr_compliance"
    assert result["interactionAudit"]["status"] == "armed"
    assert "error" not in result


def test_extension_background_preserves_accept_action_on_sky_news_fixture_when_supported() -> None:
    with sync_playwright() as p:
        with _serve_fixture_dir(FIXTURES) as base_url:
            context = _launch_extension_context_or_skip(p)
            try:
                page = context.new_page()
                page.goto(f"{base_url}/sky_news_sourcepoint_like.html", wait_until="domcontentloaded")
                page.bring_to_front()
                service_worker = _get_extension_service_worker(context)

                baseline = service_worker.evaluate(
                    """async () => {
                        const tabs = await browser.tabs.query({ active: true, currentWindow: true });
                        const tabId = tabs[0]?.id;
                        return await handleAnalyze(tabId);
                    }"""
                )

                consent_frame = next(
                    frame for frame in page.frames
                    if frame.url.endswith("sourcepoint_iframe_inner.html")
                )
                consent_frame.get_by_text("Accept all").click()
                page.wait_for_timeout(3500)

                after_click = service_worker.evaluate(
                    """async () => {
                        const tabs = await browser.tabs.query({ active: true, currentWindow: true });
                        const tabId = tabs[0]?.id;
                        return await handleAnalyze(tabId);
                    }"""
                )
            finally:
                context.close()

    assert baseline["analysisMode"] == "baseline_banner"
    assert baseline["interactionAudit"]["status"] == "armed"
    assert after_click["analysisMode"] == "post_interaction"
    assert after_click["interactionAudit"]["action"]["type"] == "accept"
    assert after_click["interactionAudit"]["action"]["text"] == "Accept all"
    assert after_click["interactionAudit"]["honesty"]["verdict"] == "not_applicable"


def test_extension_background_preserves_essential_action_on_eksi_settings_fixture_when_supported() -> None:
    with sync_playwright() as p:
        with _serve_fixture_dir(FIXTURES) as base_url:
            context = _launch_extension_context_or_skip(p)
            try:
                page = context.new_page()
                page.goto(f"{base_url}/eksisozluk_settings_interaction.html", wait_until="domcontentloaded")
                page.bring_to_front()
                service_worker = _get_extension_service_worker(context)

                baseline = service_worker.evaluate(
                    """async () => {
                        const tabs = await browser.tabs.query({ active: true, currentWindow: true });
                        const tabId = tabs[0]?.id;
                        return await handleAnalyze(tabId);
                    }"""
                )

                page.get_by_text("Seçenekleri yönetin").click()
                page.evaluate("""() => window.__eksiSettings.setAllPreferences(false)""")
                page.get_by_text("Seçimleri onayla").click()
                page.wait_for_timeout(3500)

                after_click = service_worker.evaluate(
                    """async () => {
                        const tabs = await browser.tabs.query({ active: true, currentWindow: true });
                        const tabId = tabs[0]?.id;
                        return await handleAnalyze(tabId);
                    }"""
                )
            finally:
                context.close()

    assert baseline["analysisMode"] == "baseline_banner"
    assert baseline["interactionAudit"]["status"] == "armed"
    assert after_click["analysisMode"] == "post_interaction"
    assert after_click["interactionAudit"]["action"]["type"] == "essential"
    assert after_click["interactionAudit"]["action"]["text"] == "Seçimleri onayla"
    assert "error" not in after_click


def test_extension_background_arms_baseline_on_realistic_eksi_funding_choices_fixture_when_supported() -> None:
    with sync_playwright() as p:
        with _serve_fixture_dir(FIXTURES) as base_url:
            context = _launch_extension_context_or_skip(p)
            try:
                page = context.new_page()
                page.goto(f"{base_url}/eksisozluk_funding_choices_realistic.html", wait_until="domcontentloaded")
                page.bring_to_front()
                service_worker = _get_extension_service_worker(context)

                baseline = service_worker.evaluate(
                    """async () => {
                        const tabs = await browser.tabs.query({ active: true, currentWindow: true });
                        const tabId = tabs[0]?.id;
                        return await handleAnalyze(tabId);
                    }"""
                )
            finally:
                context.close()

    assert baseline["analysisMode"] == "baseline_banner"
    assert baseline["baselineScore"] is None
    assert baseline["interactionAudit"]["status"] == "armed"
    assert baseline["consentScan"]["bannerFound"] is True
    assert baseline["consentScan"]["acceptButtonText"] == "İzin ver"
    assert baseline["consentScan"]["settingsButtonText"] == "Seçenekleri yönetin"


def test_extension_background_arms_baseline_on_fullscreen_eksi_funding_choices_fixture_when_supported() -> None:
    with sync_playwright() as p:
        with _serve_fixture_dir(FIXTURES) as base_url:
            context = _launch_extension_context_or_skip(p)
            try:
                page = context.new_page()
                page.goto(f"{base_url}/eksisozluk_funding_choices_fullscreen.html", wait_until="domcontentloaded")
                page.bring_to_front()
                service_worker = _get_extension_service_worker(context)

                baseline = service_worker.evaluate(
                    """async () => {
                        const tabs = await browser.tabs.query({ active: true, currentWindow: true });
                        const tabId = tabs[0]?.id;
                        return await handleAnalyze(tabId);
                    }"""
                )
            finally:
                context.close()

    assert baseline["analysisMode"] == "baseline_banner"
    assert baseline["baselineScore"] is None
    assert baseline["interactionAudit"]["status"] == "armed"
    assert baseline["consentScan"]["bannerFound"] is True
    assert baseline["consentScan"]["acceptButtonText"] == "İzin ver"
    assert baseline["consentScan"]["settingsButtonText"] == "Seçenekleri yönetin"


def test_consent_scanner_matches_expected_dark_patterns_for_direct_banner() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "direct_buttons.html")
        browser.close()

    assert result["darkPatterns"]["missingReject"]["detected"] is False
    assert result["darkPatterns"]["multiLayerRejection"]["detected"] is False
    assert "Missing reject option" not in result["darkPatterns"]["detected"]
    assert "Multi-layer rejection" not in result["darkPatterns"]["detected"]


def test_consent_scanner_matches_expected_dark_patterns_for_settings_path() -> None:
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


def test_consent_scanner_prefers_visible_funding_choices_surface_on_realistic_eksi_fixture() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 768})
        result = _scan_fixture(page, "eksisozluk_funding_choices_realistic.html")
        browser.close()

    assert result["bannerFound"] is True
    assert "fc-choice-dialog" in (result["bannerSelector"] or "")
    assert result["hasAcceptButton"] is True
    assert result["acceptButtonText"] == "İzin ver"
    assert result["hasRejectButton"] is False
    assert result["hasSettingsButton"] is True
    assert result["settingsButtonText"] == "Seçenekleri yönetin"
    assert result["rejectClicksRequired"] == 2
    assert result["buttonComparison"]["available"] is True
    assert result["buttonComparison"]["rejectSource"] == "settings"
    assert result["buttonComparison"]["reject"]["text"] == "Seçenekleri yönetin"


def test_consent_scanner_promotes_fullscreen_funding_choices_surface_over_footer_button_cluster() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 768})
        result = _scan_fixture(page, "eksisozluk_funding_choices_fullscreen.html")
        browser.close()

    assert result["bannerFound"] is True
    assert "fc-choice-dialog" in (result["bannerSelector"] or "")
    assert "fc-footer-buttons" not in (result["bannerSelector"] or "")
    assert result["hasAcceptButton"] is True
    assert result["acceptButtonText"] == "İzin ver"
    assert result["hasRejectButton"] is False
    assert result["hasSettingsButton"] is True
    assert result["settingsButtonText"] == "Seçenekleri yönetin"
    assert result["rejectClicksRequired"] == 2
    assert result["buttonComparison"]["available"] is True
    assert result["buttonComparison"]["rejectSource"] == "settings"
    assert result["buttonComparison"]["reject"]["text"] == "Seçenekleri yönetin"


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
        page.add_script_tag(path=str(SHARED_CONFIG))
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


def test_consent_scanner_does_not_treat_privacy_footer_as_banner() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        result = _scan_fixture(page, "privacy_footer_only.html")
        browser.close()

    assert result["bannerFound"] is False
    assert result["hasAcceptButton"] is False
    assert result["hasRejectButton"] is False
    assert result["hasSettingsButton"] is False
    assert result["darkPatterns"]["count"] == 0
    assert result["darkPatterns"]["detected"] == []


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
        page.add_script_tag(path=str(SHARED_CONFIG))
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
                        petSectionHidden: document.getElementById("petSection").classList.contains("hidden"),
                    };
                });
            }"""
        )
        browser.close()

    assert styles[0]["backgroundColor"] == "rgb(37, 99, 235)"
    assert styles[1]["backgroundColor"] == "rgb(37, 99, 235)"
    assert styles[0]["color"] == "rgb(255, 255, 255)"
    assert styles[1]["color"] == "rgb(255, 255, 255)"
    assert styles[0]["petSectionHidden"] is True


def test_popup_shows_disabled_state_when_no_active_banner_is_detected() -> None:
    popup_result = {
        "analysisMode": "unavailable",
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
            "reason": "no_meaningful_consent_state",
            "title": "Evaluation unavailable on this page",
            "message": "AECCS did not detect an active cookie banner or a meaningful post-interaction consent state, so this website was not evaluated.",
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
    assert "meaningful post-interaction consent state" in state["message"]
    assert "not evaluated" in state["message"]
    # Warm-paper light theme: Bone page, blue info panel, darkened-Ash dim text,
    # #185FA5 solid accent fill on the disabled-state icon.
    assert state["bodyBackground"] == "rgb(233, 231, 223)"      # --page-bg  #e9e7df Bone
    assert state["disabledBackground"] == "rgb(231, 239, 248)"  # --accent-panel #e7eff8
    assert state["disabledBorderColor"] == "rgb(187, 211, 236)" # --panel-border #bbd3ec
    assert state["disabledMessageColor"] == "rgb(91, 90, 84)"   # --text-dim #5b5a54
    assert state["disabledIconBackground"] == "rgb(24, 95, 165)" # --accent-solid #185fa5


def test_popup_places_browsing_setup_between_pet_tools_and_study_insights() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _mount_popup_shell(page)
        order = page.evaluate(
            """() => ({
                petNext: document.getElementById("petSection").nextElementSibling.id,
                browsingNext: document.getElementById("browsingSetupSection").nextElementSibling.id,
            })"""
        )
        browser.close()

    assert order["petNext"] == "browsingSetupSection"
    assert order["browsingNext"] == "studyInsightsSection"


def test_popup_first_run_onboarding_shows_then_stays_dismissed() -> None:
    popup_result = {
        "analysisMode": "baseline_banner",
        "site": "example.com",
        "url": "https://example.com",
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
        "score": {"label": "GDPR Compliance Score", "grade": "B", "overall_score": 78, "criteria": {}},
        "baselineScore": None,
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
            "hasRejectButton": True,
            "hasSettingsButton": False,
            "acceptButtonText": "Accept",
            "rejectButtonText": "Reject",
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

        # First run: empty storage means the onboarding card should reveal itself.
        _boot_popup_with_state(page, responses=[popup_result])
        page.wait_for_function(
            """() => !document.getElementById("onboardingCard").classList.contains("hidden")"""
        )
        page.locator("#aboutSection > summary").click()
        first_run = page.evaluate(
            """() => ({
                onboardingVisible: !document.getElementById("onboardingCard").classList.contains("hidden"),
                aboutOpen: document.getElementById("aboutSection").open,
                criteriaRows: document.querySelectorAll("#aboutCriteriaList .insight-kv").length,
                topCriterion: document.querySelector("#aboutCriteriaList .insight-kv span")?.textContent,
                studyBasis: document.getElementById("aboutStudyBasis").textContent,
            })"""
        )

        # Dismissing persists the flag and hides the card for the session.
        page.locator("#onboardingDismiss").click()
        page.wait_for_function(
            """() => window.__aeccsPopupStorage.aeccs_onboarded === true"""
        )
        dismissed = page.evaluate(
            """() => ({
                onboardingHidden: document.getElementById("onboardingCard").classList.contains("hidden"),
                flag: window.__aeccsPopupStorage.aeccs_onboarded,
            })"""
        )

        # Reopen with the flag already stored: the card must stay hidden.
        _boot_popup_with_state(
            page,
            responses=[popup_result],
            storage_state={"aeccs_onboarded": True},
        )
        page.wait_for_function(
            """() => !document.getElementById("results").classList.contains("hidden")"""
        )
        reopened_hidden = page.evaluate(
            """() => document.getElementById("onboardingCard").classList.contains("hidden")"""
        )

        browser.close()

    assert first_run["onboardingVisible"] is True
    assert first_run["aboutOpen"] is True
    assert first_run["criteriaRows"] == 6
    # COMPLIANCE_WEIGHTS is rendered weight-descending; no_pre_consent_trackers (0.3) leads.
    assert first_run["topCriterion"] == "No Pre-Consent Trackers"
    assert "1000" in first_run["studyBasis"]
    assert dismissed["onboardingHidden"] is True
    assert dismissed["flag"] is True
    assert reopened_hidden is True


def test_popup_shows_error_when_background_analyze_never_resolves() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _mount_popup_shell(page)
        page.evaluate(
            """timeoutMs => {
                window.__AECCS_POPUP_ANALYZE_TIMEOUT_MS = timeoutMs;
                window.browser = {
                    tabs: {
                        query: async () => [{ id: 1, url: "https://eksisozluk.com" }]
                    },
                    runtime: {
                        sendMessage: async () => new Promise(() => {})
                    }
                };
            }""",
            20,
        )
        page.add_script_tag(path=str(STUDY_SNAPSHOT))
        page.add_script_tag(path=str(SHARED_CONFIG))
        page.add_script_tag(path=str(TRACKER_DATA))
        page.add_script_tag(path=str(POPUP))
        page.wait_for_function(
            """() => !document.getElementById("errorState").classList.contains("hidden")"""
        )
        state = page.evaluate(
            """() => ({
                loadingHidden: document.getElementById("loading").classList.contains("hidden"),
                errorHidden: document.getElementById("errorState").classList.contains("hidden"),
                message: document.getElementById("errorMsg").textContent,
            })"""
        )
        browser.close()

    assert state["loadingHidden"] is True
    assert state["errorHidden"] is False
    assert "did not receive an analysis response in time" in state["message"]


def test_popup_shows_error_when_background_returns_undefined() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _mount_popup_shell(page)
        page.evaluate(
            """() => {
                window.browser = {
                    tabs: {
                        query: async () => [{ id: 1, url: "https://eksisozluk.com" }]
                    },
                    runtime: {
                        sendMessage: async () => undefined
                    }
                };
            }"""
        )
        page.add_script_tag(path=str(STUDY_SNAPSHOT))
        page.add_script_tag(path=str(SHARED_CONFIG))
        page.add_script_tag(path=str(TRACKER_DATA))
        page.add_script_tag(path=str(POPUP))
        page.wait_for_function(
            """() => !document.getElementById("errorState").classList.contains("hidden")"""
        )
        state = page.evaluate(
            """() => ({
                loadingHidden: document.getElementById("loading").classList.contains("hidden"),
                errorHidden: document.getElementById("errorState").classList.contains("hidden"),
                message: document.getElementById("errorMsg").textContent,
            })"""
        )
        browser.close()

    assert state["loadingHidden"] is True
    assert state["errorHidden"] is False
    assert "did not receive a usable analysis response" in state["message"]


def test_popup_renders_post_interaction_scores_and_honesty_details() -> None:
    popup_result = {
        "analysisMode": "post_interaction",
        "isGovDomain": False,
        "studyMetadata": {
            "label": "AECCS 1000-site combined study snapshot",
            "runId": "combined-1000",
            "sampleSize": 1000,
            "successfulCrawls": 861,
            "snapshotDateLabel": "March 6, 2026",
        },
        "score": {
            "kind": "state_outcome",
            "label": "Post-Interaction State Score",
            "grade": "A",
            "overall_score": 94.0,
            "criteria": {
                "low_tracker_load": {"score": 100, "details": "No trackers detected"},
                "low_third_party_load": {"score": 100, "details": "No third-party cookies detected"},
                "low_total_cookie_load": {"score": 100, "details": "2 cookies currently loaded"},
                "claimed_action_honesty": {
                    "score": 60,
                    "details": "Only functional or unknown cookies remained after reject/essential action",
                },
            },
        },
        "baselineScore": {
            "kind": "gdpr_compliance",
            "label": "GDPR Compliance Score",
            "grade": "F",
            "overall_score": 38.0,
            "criteria": {},
        },
        "interactionAudit": {
            "status": "completed",
            "action": {
                "type": "essential",
                "text": "Essential cookies only",
                "observed": True,
                "observedAt": "2026-04-16T10:00:00.000Z",
            },
            "baseline": {
                "totalCookies": 8,
                "thirdPartyCount": 2,
                "trackerCount": 1,
                "score": {
                    "kind": "gdpr_compliance",
                    "label": "GDPR Compliance Score",
                    "grade": "F",
                    "overall_score": 38.0,
                    "criteria": {},
                },
                "consentScan": {
                    "cmpDetected": "Sourcepoint",
                    "bannerFound": True,
                    "hasAcceptButton": True,
                    "hasRejectButton": True,
                    "hasSettingsButton": True,
                    "acceptButtonText": "Accept all",
                    "rejectButtonText": "Essential cookies only",
                    "settingsButtonText": "View options",
                    "acceptClicksRequired": 1,
                    "rejectClicksRequired": 1,
                    "transparency": {},
                    "darkPatterns": {"count": 0, "detected": []},
                    "buttonComparison": None,
                },
            },
            "current": {
                "totalCookies": 2,
                "thirdPartyCount": 0,
                "trackerCount": 0,
                "score": {
                    "kind": "state_outcome",
                    "label": "Post-Interaction State Score",
                    "grade": "A",
                    "overall_score": 94.0,
                    "criteria": {},
                },
            },
            "delta": {
                "totalCookies": -6,
                "thirdPartyCount": -2,
                "trackerCount": -1,
                "newCookies": [],
                "newTrackers": [],
            },
            "honesty": {
                "verdict": "mixed",
                "findings": [
                    "Only functional or unknown cookies remained after the claimed reject/essential action."
                ],
            },
        },
        "categoryCounts": {"Functional": 1, "Unknown": 1},
        "totalCookies": 2,
        "thirdPartyCount": 0,
        "trackerCount": 0,
        "trackersByVendor": {},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": "Sourcepoint",
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
                mainLabel: document.getElementById("scoreLabel").textContent,
                scoreContextHidden: document.getElementById("scoreContext").classList.contains("hidden"),
                completeness: document.getElementById("analysisCompleteness").textContent,
                baselineHidden: document.getElementById("baselineScoreSection").classList.contains("hidden"),
                baselineLabel: document.getElementById("baselineScoreLabel").textContent,
                interactionHidden: document.getElementById("interactionSection").classList.contains("hidden"),
                compareText: document.getElementById("compareFlow").textContent,
                interactionText: document.getElementById("interactionInfo").textContent,
                consentText: document.getElementById("consentInfo").textContent,
                footer: document.getElementById("footerNote").textContent
            })"""
        )
        browser.close()

    assert state["mainLabel"] == "Post-Interaction State Score"
    assert state["scoreContextHidden"] is True
    assert state["completeness"] == "Analysis completeness: Post-click state"
    assert state["baselineHidden"] is False
    assert state["baselineLabel"] == "GDPR Compliance Score"
    assert state["interactionHidden"] is False
    assert "Post-click result captured" in state["compareText"]
    assert "Post-click state" in state["compareText"]
    assert "Capture baseline" in state["compareText"]
    assert "Review outcome" in state["compareText"]
    assert "What AECCS Saw" in state["interactionText"]
    assert "Essential cookies only (observed)" in state["interactionText"]
    assert "Partially supports banner claim" in state["interactionText"]
    assert "Total cookies-6" in state["interactionText"]
    assert "Only functional or unknown cookies remained" in state["interactionText"]
    assert "No consent banner found" in state["consentText"]
    assert "Session-limited local consent audit" in state["footer"]


def test_popup_guided_compare_shows_waiting_for_action_state_when_baseline_is_captured() -> None:
    popup_result = {
        "analysisMode": "baseline_banner",
        "site": "example.com",
        "url": "https://example.com",
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
        "score": {"label": "GDPR Compliance Score", "grade": "F", "overall_score": 33, "criteria": {}},
        "baselineScore": None,
        "interactionAudit": {
            "status": "armed",
            "action": None,
            "baseline": {
                "totalCookies": 8,
                "thirdPartyCount": 3,
                "trackerCount": 2,
                "score": {"label": "GDPR Compliance Score", "grade": "F", "overall_score": 33, "criteria": {}},
                "consentScan": {"cmpDetected": "OneTrust"},
            },
            "current": {
                "totalCookies": 8,
                "thirdPartyCount": 3,
                "trackerCount": 2,
                "score": {"label": "Post-Interaction State Score", "grade": "F", "overall_score": 33, "criteria": {}},
            },
            "delta": None,
            "honesty": {"verdict": "unknown", "findings": []},
        },
        "categoryCounts": {"Advertising": 2, "Functional": 3, "Unknown": 3},
        "totalCookies": 8,
        "thirdPartyCount": 3,
        "trackerCount": 2,
        "trackersByVendor": {"Google": ["IDE"]},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": "OneTrust",
            "bannerFound": True,
            "hasAcceptButton": True,
            "hasRejectButton": True,
            "hasSettingsButton": True,
            "acceptButtonText": "Accept all",
            "rejectButtonText": "Reject all",
            "settingsButtonText": "Manage choices",
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
        state = page.evaluate(
            """() => ({
                completeness: document.getElementById("analysisCompleteness").textContent,
                compareText: document.getElementById("compareFlow").textContent,
                interactionHidden: document.getElementById("interactionSection").classList.contains("hidden"),
                recheckLabel: document.getElementById("recheckButton").textContent,
                startOverLabel: document.getElementById("startOverButton").textContent
            })"""
        )
        browser.close()

    assert state["interactionHidden"] is False
    assert state["completeness"] == "Analysis completeness: Banner visible"
    assert "Baseline captured" in state["compareText"]
    assert "Banner visible" in state["compareText"]
    assert "Click Accept, Reject, or Settings" in state["compareText"]
    assert "Capture baseline" in state["compareText"]
    assert state["recheckLabel"] == "Re-check now"
    assert state["startOverLabel"] == "Start over"


def test_popup_guided_compare_shows_no_comparable_baseline_state() -> None:
    popup_result = {
        "analysisMode": "post_interaction",
        "site": "example.com",
        "url": "https://example.com/article",
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
        "score": {"label": "Post-Interaction State Score", "grade": "A", "overall_score": 91, "criteria": {}},
        "baselineScore": None,
        "interactionAudit": {
            "status": "unknown_current_state",
            "action": {"type": "unknown", "text": None, "observed": False, "observedAt": None},
            "baseline": None,
            "current": {
                "totalCookies": 1,
                "thirdPartyCount": 0,
                "trackerCount": 0,
                "score": {"label": "Post-Interaction State Score", "grade": "A", "overall_score": 91, "criteria": {}},
            },
            "delta": None,
            "honesty": {"verdict": "unknown", "findings": ["No observed reject or essential-only action was available for honesty checking."]},
        },
        "categoryCounts": {"Unknown": 1},
        "totalCookies": 1,
        "thirdPartyCount": 0,
        "trackerCount": 0,
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
                completeness: document.getElementById("analysisCompleteness").textContent,
                compareText: document.getElementById("compareFlow").textContent
            })"""
        )
        browser.close()

    assert state["completeness"] == "Analysis completeness: No comparable baseline"
    assert "No comparable baseline" in state["compareText"]
    assert "Start over only if the banner can be shown again" in state["compareText"]


def test_popup_restores_saved_protection_profile_and_shows_caveat_banner() -> None:
    popup_result = {
        "analysisMode": "baseline_banner",
        "site": "example.com",
        "url": "https://example.com",
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
        "score": {"label": "GDPR Compliance Score", "grade": "C", "overall_score": 61, "criteria": {}},
        "baselineScore": None,
        "interactionAudit": {
            "status": "armed",
            "action": None,
            "baseline": None,
            "current": {
                "totalCookies": 4,
                "thirdPartyCount": 1,
                "trackerCount": 1,
                "score": {"label": "Post-Interaction State Score", "grade": "C", "overall_score": 61, "criteria": {}},
            },
            "delta": None,
            "honesty": {"verdict": "unknown", "findings": []},
        },
        "categoryCounts": {"Functional": 2, "Advertising": 1, "Unknown": 1},
        "totalCookies": 4,
        "thirdPartyCount": 1,
        "trackerCount": 1,
        "trackersByVendor": {"Google": ["IDE"]},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": "OneTrust",
            "bannerFound": True,
            "hasAcceptButton": True,
            "hasRejectButton": True,
            "hasSettingsButton": False,
            "acceptButtonText": "Accept all",
            "rejectButtonText": "Reject all",
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
        _boot_popup_with_state(
            page,
            responses=[popup_result],
            storage_state={
                "aeccsUserProtectionProfile": {
                    "browserProtection": "brave_shields",
                    "extraTools": ["ublock_origin", "consent_o_matic"],
                    "updatedAt": "2026-04-23T16:00:00.000Z",
                }
            },
        )
        state = page.evaluate(
            """() => ({
                summary: document.getElementById("browsingSetupSummary").textContent,
                browserProtection: document.getElementById("browserProtectionSelect").value,
                selectedTools: Array.from(document.querySelectorAll('input[name="extraTool"]:checked')).map(input => input.value),
                scoreValue: document.getElementById("scoreValue").textContent,
                scoreContextHidden: document.getElementById("scoreContext").classList.contains("hidden"),
                scoreContext: document.getElementById("scoreContext").textContent,
                caveatHidden: document.getElementById("protectionCaveat").classList.contains("hidden"),
                caveatText: document.getElementById("protectionCaveatText").textContent,
                explainerText: document.getElementById("protectionExplainerContent").textContent,
            })"""
        )
        browser.close()

    assert "Brave Shields" in state["summary"]
    assert "uBlock Origin" in state["summary"]
    assert "Consent-O-Matic" in state["summary"]
    assert state["browserProtection"] == "brave_shields"
    assert state["selectedTools"] == ["ublock_origin", "consent_o_matic"]
    assert state["scoreValue"] == "61"
    assert state["scoreContextHidden"] is False
    assert state["scoreContext"] == "Measured in your current browsing setup."
    assert state["caveatHidden"] is False
    assert "may change which cookies, trackers, or consent surfaces are visible" in state["caveatText"]
    assert "automate consent outcomes" in state["caveatText"]
    assert "keeps the live score exactly the same" in state["explainerText"]
    assert "Consent-O-Matic can automate consent choices" in state["explainerText"]


def test_popup_saves_declared_protection_profile_without_changing_score() -> None:
    popup_result = {
        "analysisMode": "baseline_banner",
        "site": "example.com",
        "url": "https://example.com",
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
        "score": {"label": "GDPR Compliance Score", "grade": "B", "overall_score": 78, "criteria": {}},
        "baselineScore": None,
        "interactionAudit": {
            "status": "armed",
            "action": None,
            "baseline": None,
            "current": {
                "totalCookies": 2,
                "thirdPartyCount": 1,
                "trackerCount": 1,
                "score": {"label": "Post-Interaction State Score", "grade": "B", "overall_score": 78, "criteria": {}},
            },
            "delta": None,
            "honesty": {"verdict": "unknown", "findings": []},
        },
        "categoryCounts": {"Advertising": 1, "Unknown": 1},
        "totalCookies": 2,
        "thirdPartyCount": 1,
        "trackerCount": 1,
        "trackersByVendor": {"Google": ["IDE"]},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": None,
            "bannerFound": True,
            "hasAcceptButton": True,
            "hasRejectButton": True,
            "hasSettingsButton": False,
            "acceptButtonText": "Accept",
            "rejectButtonText": "Reject",
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
        _boot_popup_with_state(page, responses=[popup_result])
        page.locator("#browsingSetupSection > summary").click()
        page.select_option("#browserProtectionSelect", "firefox_etp_strict")
        page.check('input[name="extraTool"][value="privacy_badger"]')
        page.wait_for_function(
            """() => {
                const stored = window.__aeccsPopupStorage.aeccsUserProtectionProfile;
                return stored &&
                    stored.browserProtection === "firefox_etp_strict" &&
                    stored.extraTools.includes("privacy_badger");
            }"""
        )
        state = page.evaluate(
            """() => ({
                scoreValue: document.getElementById("scoreValue").textContent,
                grade: document.getElementById("gradeLetter").textContent,
                storageKeys: Object.keys(window.__aeccsPopupStorage),
                stored: window.__aeccsPopupStorage.aeccsUserProtectionProfile,
                summary: document.getElementById("browsingSetupSummary").textContent,
                caveatHidden: document.getElementById("protectionCaveat").classList.contains("hidden")
            })"""
        )
        browser.close()

    assert state["scoreValue"] == "78"
    assert state["grade"] == "B"
    assert state["storageKeys"] == ["aeccsUserProtectionProfile"]
    assert state["stored"]["browserProtection"] == "firefox_etp_strict"
    assert state["stored"]["extraTools"] == ["privacy_badger"]
    assert "Firefox ETP Strict" in state["summary"]
    assert "Privacy Badger" in state["summary"]
    assert state["caveatHidden"] is False


def test_popup_recheck_now_reruns_analysis_and_updates_compare_state() -> None:
    initial_result = {
        "analysisMode": "baseline_banner",
        "site": "example.com",
        "url": "https://example.com",
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
        "score": {"label": "GDPR Compliance Score", "grade": "F", "overall_score": 30, "criteria": {}},
        "baselineScore": None,
        "interactionAudit": {
            "status": "armed",
            "action": None,
            "baseline": None,
            "current": {"totalCookies": 6, "thirdPartyCount": 2, "trackerCount": 2, "score": {"label": "Post-Interaction State Score", "grade": "F", "overall_score": 30, "criteria": {}}},
            "delta": None,
            "honesty": {"verdict": "unknown", "findings": []},
        },
        "categoryCounts": {"Advertising": 2, "Unknown": 4},
        "totalCookies": 6,
        "thirdPartyCount": 2,
        "trackerCount": 2,
        "trackersByVendor": {"Google": ["IDE"]},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": "OneTrust",
            "bannerFound": True,
            "hasAcceptButton": True,
            "hasRejectButton": True,
            "hasSettingsButton": False,
            "acceptButtonText": "Accept all",
            "rejectButtonText": "Reject all",
            "settingsButtonText": None,
            "acceptClicksRequired": 1,
            "rejectClicksRequired": 1,
            "transparency": {},
            "darkPatterns": {"count": 0, "detected": []},
            "buttonComparison": None,
        },
    }
    updated_result = {
        "analysisMode": "post_interaction",
        "site": "example.com",
        "url": "https://example.com",
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
        "score": {"label": "Post-Interaction State Score", "grade": "B", "overall_score": 81, "criteria": {}},
        "baselineScore": {"label": "GDPR Compliance Score", "grade": "F", "overall_score": 30, "criteria": {}},
        "interactionAudit": {
            "status": "completed",
            "action": {"type": "reject", "text": "Reject all", "observed": True, "observedAt": "2026-04-23T17:00:00.000Z"},
            "baseline": {"totalCookies": 6, "thirdPartyCount": 2, "trackerCount": 2, "score": {"label": "GDPR Compliance Score", "grade": "F", "overall_score": 30, "criteria": {}}, "consentScan": {"cmpDetected": "OneTrust"}},
            "current": {"totalCookies": 1, "thirdPartyCount": 0, "trackerCount": 0, "score": {"label": "Post-Interaction State Score", "grade": "B", "overall_score": 81, "criteria": {}}},
            "delta": {"totalCookies": -5, "thirdPartyCount": -2, "trackerCount": -2, "newCookies": [], "newTrackers": []},
            "honesty": {"verdict": "honest", "findings": ["No non-essential cookies or trackers remained after the claimed reject/essential action."]},
        },
        "categoryCounts": {"Functional": 1},
        "totalCookies": 1,
        "thirdPartyCount": 0,
        "trackerCount": 0,
        "trackersByVendor": {},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": "OneTrust",
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
        _boot_popup_with_state(page, responses=[initial_result])
        page.evaluate(
            """data => {
                window.__popupAnalyzeResponses = data;
                window.__aeccsPopupMessageHandler = async message => {
                    if (message.action === "analyze") {
                        return window.__popupAnalyzeResponses.shift();
                    }
                    return { ok: true };
                };
            }""",
            [updated_result],
        )
        page.click("#recheckButton")
        page.wait_for_function(
            """() => document.getElementById("compareFlow").textContent.includes("Post-click result captured")"""
        )
        state = page.evaluate(
            """() => ({
                calls: window.__aeccsMessageCalls.map(item => item.action),
                compareText: document.getElementById("compareFlow").textContent,
                scoreValue: document.getElementById("scoreValue").textContent
            })"""
        )
        browser.close()

    assert state["calls"] == ["analyze", "analyze"]
    assert "Post-click result captured" in state["compareText"]
    assert state["scoreValue"] == "81"


def test_popup_start_over_clears_session_and_can_land_in_disabled_state() -> None:
    initial_result = {
        "analysisMode": "baseline_banner",
        "site": "example.com",
        "url": "https://example.com",
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
        "score": {"label": "GDPR Compliance Score", "grade": "F", "overall_score": 30, "criteria": {}},
        "baselineScore": None,
        "interactionAudit": {
            "status": "armed",
            "action": None,
            "baseline": None,
            "current": {"totalCookies": 6, "thirdPartyCount": 2, "trackerCount": 2, "score": {"label": "Post-Interaction State Score", "grade": "F", "overall_score": 30, "criteria": {}}},
            "delta": None,
            "honesty": {"verdict": "unknown", "findings": []},
        },
        "categoryCounts": {"Advertising": 2, "Unknown": 4},
        "totalCookies": 6,
        "thirdPartyCount": 2,
        "trackerCount": 2,
        "trackersByVendor": {"Google": ["IDE"]},
        "cmpStats": None,
        "petRecommendations": [],
        "consentScan": {
            "cmpDetected": "OneTrust",
            "bannerFound": True,
            "hasAcceptButton": True,
            "hasRejectButton": True,
            "hasSettingsButton": False,
            "acceptButtonText": "Accept all",
            "rejectButtonText": "Reject all",
            "settingsButtonText": None,
            "acceptClicksRequired": 1,
            "rejectClicksRequired": 1,
            "transparency": {},
            "darkPatterns": {"count": 0, "detected": []},
            "buttonComparison": None,
        },
    }
    disabled_result = {
        "analysisMode": "unavailable",
        "evaluationDisabled": {
            "active": True,
            "reason": "no_meaningful_consent_state",
            "title": "Evaluation unavailable on this page",
            "message": "AECCS did not detect an active cookie banner or a meaningful post-interaction consent state, so this website was not evaluated.",
        },
        "studyMetadata": {"sampleSize": 1000, "successfulCrawls": 861, "snapshotDateLabel": "March 6, 2026"},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _boot_popup_with_state(page, responses=[initial_result])
        page.evaluate(
            """data => {
                window.__popupAnalyzeResponses = data;
                window.__aeccsPopupMessageHandler = async message => {
                    if (message.action === "clearInteractionSession") {
                        return { ok: true };
                    }
                    if (message.action === "analyze") {
                        return window.__popupAnalyzeResponses.shift();
                    }
                    return null;
                };
            }""",
            [disabled_result],
        )
        page.click("#startOverButton")
        page.wait_for_function(
            """() => !document.getElementById("disabledState").classList.contains("hidden")"""
        )
        state = page.evaluate(
            """() => ({
                calls: window.__aeccsMessageCalls.map(item => item.action),
                disabledTitle: document.getElementById("disabledTitle").textContent,
                resultsHidden: document.getElementById("results").classList.contains("hidden"),
                disabledHidden: document.getElementById("disabledState").classList.contains("hidden")
            })"""
        )
        browser.close()

    assert state["calls"] == ["analyze", "clearInteractionSession", "analyze"]
    assert state["disabledTitle"] == "Evaluation unavailable on this page"
    assert state["resultsHidden"] is True
    assert state["disabledHidden"] is False


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
        page.wait_for_function(
            """() => !document.getElementById("petSection").classList.contains("hidden")"""
        )
        before = page.evaluate(
            """() => ({
                petOpen: document.getElementById("petSection").open,
                petSubtitle: document.getElementById("petSubtitle").textContent,
                petList: document.getElementById("petList").textContent,
                petCardCount: document.querySelectorAll("#petList .pet-card").length,
                studyInsightsOpen: document.getElementById("studyInsightsSection").open,
                studyInsightsContent: document.getElementById("studyInsightsContent").textContent,
            })"""
        )

        page.click("#petSection summary")
        page.wait_for_function(
            """() => document.getElementById("petSection").open &&
                document.querySelectorAll("#petList .pet-card").length > 0"""
        )

        content = page.evaluate(
            """() => ({
                govNote: document.getElementById("govNote").textContent,
                govAlertBackground: getComputedStyle(document.getElementById("govAlert")).backgroundColor,
                govNoteColor: getComputedStyle(document.getElementById("govNote")).color,
                petOpen: document.getElementById("petSection").open,
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
            })"""
        )

        page.click("#petSection summary")
        page.wait_for_function(
            """() => {
                const petSection = document.getElementById("petSection");
                return !petSection.open &&
                    document.getElementById("petSubtitle").textContent === "" &&
                    document.getElementById("petList").textContent === "";
            }"""
        )
        after_close = page.evaluate(
            """() => ({
                petOpen: document.getElementById("petSection").open,
                petSubtitle: document.getElementById("petSubtitle").textContent,
                petList: document.getElementById("petList").textContent
            })"""
        )
        browser.close()

    assert before["petOpen"] is False
    assert before["petSubtitle"] == ""
    assert before["petList"] == ""
    assert before["petCardCount"] == 0
    assert before["studyInsightsOpen"] is False
    assert before["studyInsightsContent"] == ""
    assert content["petOpen"] is True
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
    assert after_close["petOpen"] is False
    assert after_close["petSubtitle"] == ""
    assert after_close["petList"] == ""
    # Warm-paper light theme tokens (re-skinned neutrals + blue accent).
    assert content["govAlertBackground"] == "rgb(231, 239, 248)"  # --accent-panel #e7eff8
    assert content["govNoteColor"] == "rgb(91, 90, 84)"           # --text-dim #5b5a54
    assert content["cmpPanelBackground"] == "rgb(228, 226, 216)"  # --bg #e4e2d8
    assert content["cmpTitleColor"] == "rgb(24, 95, 165)"         # --accent #185fa5


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
        page.click("#petSection summary")
        page.wait_for_function(
            """() => document.getElementById("petSection").open &&
                document.querySelectorAll("#petList .pet-study-info").length === 2"""
        )
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
        page.add_script_tag(path=str(SHARED_CONFIG))
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


def test_extension_copy_uses_local_audit_framing() -> None:
    readme_text = README.read_text(encoding="utf-8").lower()
    manifest_text = MANIFEST.read_text(encoding="utf-8")
    privacy_policy_text = PRIVACY_POLICY.read_text(encoding="utf-8").lower()

    assert "local, user-initiated" in readme_text
    assert "does not crawl in the background" in readme_text
    assert "does not auto-click banners" in readme_text
    assert "does not transmit browsing data" in readme_text

    assert "Local, user-initiated GDPR cookie-consent auditor with session-limited post-interaction analysis" in manifest_text

    assert "research-grounded browser extension" in privacy_policy_text
    assert "session-limited" in privacy_policy_text
    assert "page-wide click logging" in privacy_policy_text


def test_scorer_distinguishes_direct_and_settings_reject_paths() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("data:text/html,<html><body></body></html>")
        page.add_script_tag(path=str(STUDY_SNAPSHOT))
        page.add_script_tag(path=str(SHARED_CONFIG))
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
    assert scores["direct"]["criteria"]["post_reject_compliance"]["score"] is None
    assert scores["direct"]["criteria"]["post_reject_compliance"]["details"] == "Not available in baseline audit (no verified post-reject data)"
    assert scores["direct"]["overall_score"] == 88.2
    assert scores["direct"]["grade"] == "B"
    assert scores["settingsPath"]["criteria"]["reject_option_available"]["score"] == 50
    assert scores["settingsPath"]["criteria"]["equal_accept_reject_effort"]["score"] == 50
    assert scores["settingsPath"]["criteria"]["post_reject_compliance"]["score"] is None
    assert scores["settingsPath"]["criteria"]["post_reject_compliance"]["details"] == "Not available in baseline audit (no verified post-reject data)"
    assert scores["settingsPath"]["overall_score"] == 70.6
    assert scores["settingsPath"]["grade"] == "C"
    assert scores["noReject"]["criteria"]["reject_option_available"]["score"] == 0
    assert scores["noReject"]["criteria"]["equal_accept_reject_effort"]["score"] == 0
    assert scores["noReject"]["criteria"]["post_reject_compliance"]["score"] == 0
    assert scores["noReject"]["criteria"]["post_reject_compliance"]["details"] == "No reject option available"
    assert scores["noBanner"]["criteria"]["reject_option_available"]["score"] == 0
    assert scores["noBanner"]["criteria"]["post_reject_compliance"]["score"] is None
    assert scores["noBanner"]["criteria"]["post_reject_compliance"]["details"] == "Not available without a visible consent banner"


def test_scorer_computes_post_interaction_state_score_and_honesty() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("data:text/html,<html><body></body></html>")
        page.add_script_tag(path=str(STUDY_SNAPSHOT))
        page.add_script_tag(path=str(SHARED_CONFIG))
        page.add_script_tag(path=str(TRACKER_DATA))
        page.add_script_tag(path=str(SCORER))

        scores = page.evaluate(
            """() => {
                const essentialOutcome = Scorer.computeStateOutcomeScore(
                    {
                        totalCookies: 2,
                        thirdPartyCount: 0,
                        trackerCount: 0,
                        categoryCounts: { Functional: 1, Unknown: 1 }
                    },
                    {
                        action: { type: "essential", text: "Essential cookies only", observed: true },
                        baseline: { thirdPartyCount: 2 },
                        delta: { newTrackers: [] }
                    }
                );

                const acceptOutcome = Scorer.computeStateOutcomeScore(
                    {
                        totalCookies: 12,
                        thirdPartyCount: 4,
                        trackerCount: 3,
                        categoryCounts: { Advertising: 2, Analytics: 1, Unknown: 9 }
                    },
                    {
                        action: { type: "accept", text: "Accept all", observed: true },
                        baseline: { thirdPartyCount: 1 },
                        delta: { newTrackers: [{ name: "ad_id" }] }
                    }
                );

                return { essentialOutcome, acceptOutcome };
            }"""
        )
        browser.close()

    assert scores["essentialOutcome"]["kind"] == "state_outcome"
    assert scores["essentialOutcome"]["label"] == "Post-Interaction State Score"
    assert scores["essentialOutcome"]["overall_score"] == 86
    assert scores["essentialOutcome"]["criteria"]["claimed_action_honesty"]["score"] == 60
    assert "Only functional or unknown cookies remained" in scores["essentialOutcome"]["criteria"]["claimed_action_honesty"]["details"]
    assert scores["acceptOutcome"]["criteria"]["claimed_action_honesty"]["score"] is None
    assert scores["acceptOutcome"]["overall_score"] == 28.5
