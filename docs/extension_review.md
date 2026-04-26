# AECCS Extension Review

Updated: April 13, 2026

## Scope and Assumptions

- Reviewed `extension/` as the browser extension implementation referenced by the user as `/browser-extension`.
- Traced extension behavior back to `analysis/classifier.py`, `analysis/scoring.py`, `dark_patterns/detector.py`, `scraper/crawler.py`, and `config.py`.
- Kept `data/pet_extensions/` out of scope except where it helps distinguish this extension from the PET evaluation assets elsewhere in the repo.
- Goal: explain current functionality and parity, not redesign or modify the extension logic.

## Runtime Architecture Map

### Static structure

| Layer | Files | Responsibility |
| --- | --- | --- |
| Manifest | `extension/manifest.json` | Declares MV3 wiring, permissions, popup entrypoint, service worker, and content script injection. |
| Popup UI | `extension/popup/popup.html`, `extension/popup/popup.js`, `extension/popup/popup.css` | Starts analysis for the active tab and renders results. |
| Background | `extension/background/service-worker.js` | Orchestrates analysis, reads cookies, requests DOM scanning, scores compliance, and prepares summary data. |
| Content script | `extension/content/consent-scanner.js` | Inspects the live page DOM for CMPs, banners, buttons, transparency signals, and dark patterns. |
| Shared data/constants | `extension/lib/tracker-data.js` | Provides the `AECCS` global: tracker map, heuristics, selector lists, scoring weights, study metadata, and dark-pattern descriptions. |
| Shared helpers | `extension/lib/browser-polyfill.js`, `extension/lib/domain-utils.js`, `extension/lib/classifier.js`, `extension/lib/scorer.js` | Normalize APIs, derive registered domains, classify cookies, and compute compliance scores. |

### Manifest wiring and runtime boundaries

- `extension/manifest.json:6-12` grants `cookies`, `activeTab`, `scripting`, and `<all_urls>` host access.
- `extension/manifest.json:14-18` registers the background service worker and popup.
- `extension/manifest.json:25-34` injects `browser-polyfill.js`, `tracker-data.js`, and `content/consent-scanner.js` on all matched pages at `document_idle`.
- There is no build step, bundler, or framework. The extension is plain HTML/CSS/JS with globals shared across files.

### End-to-end runtime flow

1. `extension/popup/popup.js:69-80` queries the active tab and sends `{ action: "analyze", tabId }` to the background.
2. `background/service-worker.js:21-29` listens for the `analyze` message and delegates to `handleAnalyze()`.
3. `background/service-worker.js:31-60` resolves the target tab, rejects non-HTTP(S) pages, and reads cookies via `browser.cookies.getAll({ url: tab.url })`.
4. `background/service-worker.js:62-63` classifies cookies with `Classifier.classifyAll()`.
5. `background/service-worker.js:65-84` requests a consent scan from the content script and falls back to `browser.scripting.executeScript()` if the content script is unavailable.
6. `background/service-worker.js:86-115` computes the compliance score, government-domain flag, CMP stats, and PET recommendations.
7. `background/service-worker.js:117-131` returns a single result object to the popup.
8. `extension/popup/popup.js:94-110` renders the score, cookie breakdown, tracker list, consent findings, button comparison, dark-pattern cards, criteria table, and PET recommendations into `extension/popup/popup.html:38-110`.

## Message and Data Contracts

### Popup to background

Request shape from `extension/popup/popup.js:76`:

```js
{ action: "analyze", tabId: tab.id }
```

Primary response fields from `background/service-worker.js:117-131`:

| Field | Meaning |
| --- | --- |
| `site`, `url` | Active tab hostname and full URL. |
| `totalCookies` | Number of cookies returned by `browser.cookies.getAll()`. |
| `thirdPartyCount`, `trackerCount` | Counts derived from the classified cookie list. |
| `categoryCounts` | Cookie counts grouped by category. |
| `trackersByVendor` | Tracker cookie names grouped by vendor. |
| `classifiedCookies` | Per-cookie output from `Classifier.classifyAll()`. |
| `consentScan` | Raw content-script scan payload. |
| `score` | Overall score, grade, and per-criterion details from `Scorer.computeComplianceScore()`. |
| `isGovDomain` | Boolean flag based on `AECCS.GOV_SUFFIXES`. |
| `cmpStats` | Static CMP summary if `consentScan.cmpDetected` matches `AECCS.CMP_STATS`. |
| `petRecommendations` | Up to three recommended PETs ranked by extension-specific relevance logic. |

Failure cases:

- `background/service-worker.js:41-50` rejects missing tabs and non-HTTP(S) pages.
- `background/service-worker.js:56-60` returns `Failed to read cookies`.
- `background/service-worker.js:81-82` wraps content-script failure as `Content script unavailable`.
- `extension/popup/popup.js:86-90` renders any `error` response in the popup error state.

### Background to content script

Request shape from `background/service-worker.js:68` and `80`:

```js
{ action: "scanConsent" }
```

Response shape from `content/consent-scanner.js:529-548`:

| Field | Meaning |
| --- | --- |
| `cmpDetected` | CMP matched from script URLs and page HTML. |
| `bannerFound` | Whether any banner selector matched a visible banner-like element. |
| `hasAcceptButton`, `hasRejectButton` | Whether button detection found accept/reject controls. |
| `acceptButtonText`, `rejectButtonText` | Human-readable button labels when found. |
| `darkPatterns` | Dark-pattern count, detected names, and per-detector detail payloads. |
| `transparency` | Purpose/vendor mentions, privacy-link presence, and clear-language flag. |
| `buttonComparison` | Side-by-side accept/reject styling snapshot plus UX issues. |
| `bannerText` | Truncated banner text, capped at 500 characters. |

Error behavior:

- `content/consent-scanner.js:553-560` wraps scan exceptions into `{ error: err.message }`.

### Shared globals and provenance

| Global | Defined in | Used by | Provenance |
| --- | --- | --- | --- |
| `AECCS` | `extension/lib/tracker-data.js:11-344` | Background, content script, popup | Direct ports from `analysis/classifier.py`, `analysis/scoring.py`, `scraper/crawler.py`, and `config.py`, plus extension-specific study metadata and labels. |
| `DomainUtils` | `extension/lib/domain-utils.js:6-71` | `Classifier` | Lightweight replacement for Python `tldextract`, using a curated multi-part TLD list. |
| `Classifier` | `extension/lib/classifier.js:10-102` | Background | JS port of the cookie classification cascade. |
| `Scorer` | `extension/lib/scorer.js:14-170` | Background | JS port of the six-criterion compliance scorer. |

## Parity vs. Simplification Matrix

| Area | Extension implementation | Upstream source | Parity status | Notes |
| --- | --- | --- | --- | --- |
| Tracker constants and heuristics | `extension/lib/tracker-data.js:14-209` | `analysis/classifier.py`, `analysis/scoring.py`, `scraper/crawler.py`, `config.py` | Direct port | Fallback tracker map, cookie-name heuristics, CMP signatures, consent keywords, scoring weights, grade thresholds, banner selectors, privacy keywords, and vendor keywords are direct JS copies. |
| Cookie classification | `extension/lib/classifier.js:23-95` | `analysis/classifier.py` | Partial | Matches the fallback-domain and regex heuristics, but omits EasyList, EasyPrivacy, Disconnect Services, and request/domain evidence from the Python classifier. |
| Registered-domain logic | `extension/lib/domain-utils.js:9-64` | `analysis/classifier.py` via `tldextract` | Simplified | Uses a hard-coded set of common multi-part TLDs instead of the full public suffix list. |
| CMP detection and banner discovery | `extension/content/consent-scanner.js:94-186` | `scraper/crawler.py`, `config.py` | Mostly direct | Same signatures, selector strategy, and multilingual button keywords, but applied to the live DOM of the active page. |
| Dark-pattern detection | `extension/content/consent-scanner.js:191-390` | `dark_patterns/detector.py` | Mostly direct | Preselected checkboxes, asymmetric buttons, hidden reject, confusing language, and forced action are direct ports. Missing-reject and multi-layer rejection are not counted as dark-pattern types in the JS payload. |
| Transparency scoring inputs | `extension/content/consent-scanner.js:395-425` | `analysis/scoring.py` | Direct logic port | Checks purposes, vendors, privacy links, and sentence length against banner text/html. |
| Compliance scoring | `extension/lib/scorer.js:24-163` | `analysis/scoring.py` | Partial | Same weights and grading thresholds, but treats all visible cookies as pre-consent, uses button asymmetry instead of click counts for equal effort, and approximates post-reject compliance as `50` or `0`. |
| PET recommendations | `background/service-worker.js:139-174` | Extension-specific | Extension-only | This ranking is not part of the Python pipeline. It maps current findings to static PET profiles embedded in `AECCS.PET_PROFILES`. |
| Popup presentation | `extension/popup/popup.html:41-110`, `extension/popup/popup.js:94-352` | Extension-specific | Extension-only | Government alert, CMP study card, GDPR article cards, and accept/reject button mockups are UI features unique to the extension. |

## Scenario Walkthroughs

### Known third-party tracker cookie classification

- `Classifier.classifyCookie()` strips leading dots, derives the registered domain, and checks `AECCS.FALLBACK_TRACKERS` first (`extension/lib/classifier.js:23-56`).
- A cookie like `IDE` on `.doubleclick.net` will be marked third-party and classified as `Google / Advertising` via the fallback tracker map.
- This behavior is anchored by the upstream Python test `tests/test_validation_and_provenance.py:166-185`.

### Banner with no reject button

- `findButtons()` reports `hasRejectButton: false` when no reject keyword matches (`extension/content/consent-scanner.js:148-185`).
- The scorer then returns:
  - `reject_option_available = 0` (`extension/lib/scorer.js:42-53`)
  - `equal_accept_reject_effort = 0` (`extension/lib/scorer.js:59-78`)
  - `post_reject_compliance = 0` (`extension/lib/scorer.js:102-113`)
- The popup also shows "No reject button found" in both the consent summary and button comparison (`extension/popup/popup.js:210-214`, `236-275`).

### Asymmetric accept/reject styling

- `detectAsymmetricButtons()` compares button area, font size, font weight, and reject-button contrast (`extension/content/consent-scanner.js:224-275`).
- If the reject button is smaller, lighter, or lower-contrast than accept, the dark-pattern detector flags `Asymmetric buttons`.
- `Scorer._scoreEqualEffort()` downgrades the equal-effort criterion to `50` whenever asymmetry is detected (`extension/lib/scorer.js:72-77`).
- Upstream behavior is covered by `tests/test_validation_and_provenance.py:188-243`.

### Preselected non-essential checkbox detection

- `detectPreselectedCheckboxes()` scans checked checkboxes inside the banner and exempts labels that look "necessary" or "strictly necessary" (`extension/content/consent-scanner.js:191-219`).
- Any checked non-essential box becomes the `Pre-selected checkboxes` dark-pattern label in the outgoing payload.
- The Python baseline is covered by `tests/test_validation_and_provenance.py:239-240`.

### No-banner behavior

- If `findBanner()` returns `null`, `bannerFound` is false and the transparency block remains empty (`extension/content/consent-scanner.js:497-548`).
- `Scorer` then gives zero to reject availability, equal effort, post-reject compliance, and transparent information (`extension/lib/scorer.js:42-53`, `59-78`, `102-120`).
- The upstream no-banner case is anchored by `tests/test_validation_and_provenance.py:246-283`.

### CMP stats, government alerts, and PET recommendations

- Government-domain detection is a suffix match against `AECCS.GOV_SUFFIXES` (`background/service-worker.js:107-108`).
- CMP stats appear only when the content script detects a CMP present in `AECCS.CMP_STATS` (`background/service-worker.js:110-112`, `extension/popup/popup.js:216-226`).
- PET recommendations are derived from current findings only when at least one issue is detected (`background/service-worker.js:139-174`).

## Risk and Gap Register

| Impact | Finding | Why it matters |
| --- | --- | --- |
| High | The extension is not feature-parity with the Python classifier. | The Python pipeline uses EasyList, EasyPrivacy, Disconnect, and request/domain evidence; the extension uses only the built-in fallback tracker map and cookie heuristics (`analysis/classifier.py` vs. `extension/lib/classifier.js`). Scores from the extension are indicative, not equivalent to batch-study outputs. |
| High | Post-reject compliance and equal-effort are intentionally approximate in the extension. | The extension cannot click reject, rescan cookies, or measure extra clicks. It substitutes heuristics (`extension/lib/scorer.js:55-113`) for logic that is materially richer in `analysis/scoring.py`. |
| Medium | Two Python dark-pattern signals are not reproduced as JS dark-pattern labels. | The Python detector includes explicit `missing_reject` and `multi_layer_rejection`; the extension surfaces missing reject through button fields and scoring, but does not count it inside `darkPatterns.detected`, and it does not implement multi-layer rejection at all. |
| Medium | Embedded study metadata appears stale relative to the current repo state. | `extension/lib/tracker-data.js:211-320` and `extension/popup/popup.html:105-109` refer to a "1000-site study" and 2025-era comments, while the repo's current final-study documentation centers on the 100-site run dated March 1, 2026. This creates provenance ambiguity for users reading the popup at face value. |
| Medium | The extension has no JS parity tests. | Current evidence is syntax-only for JS plus upstream Python unit tests. That validates the baseline logic, but not the fidelity of the JS ports or popup/service-worker integration. |
| Medium | DOM scanning is intentionally heuristic and can drift from the user's first-page-load experience. | The content script scans the live DOM when the popup is opened. If the banner has already been dismissed, loaded inside an iframe/shadow root, or changed after user interaction, results can differ from what the crawler-style pipeline would have captured. |
| Low to Medium | `DomainUtils` is lighter than the Python domain extraction stack. | Unsupported public-suffix edge cases can change first-party vs. third-party classification for uncommon domains. |

## Validation Evidence

The following checks were run on April 13, 2026:

### JavaScript syntax checks

All of these completed successfully with `node --check`:

- `extension/background/service-worker.js`
- `extension/content/consent-scanner.js`
- `extension/popup/popup.js`
- `extension/lib/classifier.js`
- `extension/lib/scorer.js`
- `extension/lib/tracker-data.js`

### Upstream baseline tests

Command run:

```bash
pytest -q tests/test_validation_and_provenance.py -k "classify_cookie or dark_pattern_detectors or compute_compliance_score_handles_compliant_and_no_banner_cases"
```

Result:

```text
3 passed, 8 deselected in 8.66s
```

Covered baseline scenarios:

- known tracker-cookie classification
- dark-pattern detector behavior
- compliant and no-banner scoring behavior

## Bottom Line

`extension/` is a self-contained MV3 browser extension that turns the AECCS research pipeline into a local, user-initiated, session-limited audit tool. Its strengths are direct portability of the core heuristics, a clear runtime split between popup/background/content responsibilities, and a useful UI layer for dark-pattern explanations, before/after consent-state comparisons, and PET guidance. Its biggest limitation is that it should be treated as a local approximation of the Python pipeline, not a drop-in replacement for the full crawler-based study.
