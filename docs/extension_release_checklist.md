# AECCS Extension Release Checklist

## Release Baseline

- Release target: `1.0.2`
- Publisher identity: personal publisher account, using AECCS as the product brand
- Release model: listed add-on / public extension on both Firefox AMO and Chrome Web Store
- Product posture:
  - local, user-initiated, session-limited consent auditor
  - no blocking
  - no auto-clicking
  - no remote scan
  - no telemetry
  - no new permissions beyond `cookies`, `activeTab`, `scripting`, and `<all_urls>`

## Public URLs

- Homepage URL: `https://github.com/erenozen/AECCS`
- Support URL: `https://github.com/erenozen/AECCS/issues`
- Privacy policy URL: `https://erenozen.github.io/AECCS/privacy-policy.html`

## Freeze The Release Candidate

1. Use the current extension behavior and current permission set for the `1.0.2` store update.
2. If code changes after this point, bump `extension/manifest.json` before packaging.
3. Submit both stores from the same commit and the same packaged extension contents.

## Store Assets

1. Prepare 4 real popup screenshots:
   - score + cookie breakdown + trackers
   - consent analysis + accept vs reject UX comparison
   - dark-pattern cards + criteria breakdown
   - expanded `AECCS Study Insights`
2. Prepare Chrome promo art:
   - small promo tile `440x280`
3. Recheck that screenshots match the shipped UI and combined-study wording.

## Build Submission Artifacts

1. Run:
   - `python scripts/package_extension_release.py --version 1.0.2`
2. Confirm this generates into `dist/extension-release/`:
   - Chrome upload ZIP
   - Firefox upload ZIP
   - reviewer/source ZIP
   - release manifest JSON
3. Keep the reviewer/source ZIP ready for Firefox even if AMO does not require it immediately.

## Verify Before Submission

1. Run focused verification:
   - `node --check extension/lib/tracker-data.js`
   - `node --check extension/popup/popup.js`
   - `pytest -q tests/test_extension_scanner.py tests/test_extension_release.py`
2. Manually install the packaged extension in Chrome and Firefox.
3. Confirm:
   - popup opens
   - analysis runs only on demand
   - permissions shown match expectations
   - `manifest.json` is at the ZIP root
   - generated static assets are bundled
   - privacy policy URL opens correctly

## Submit Firefox First

1. Open the existing AECCS listing in AMO Developer Hub and create a new listed version.
2. Upload the Firefox ZIP from `dist/extension-release/`.
3. If source code is requested, answer **Yes** and upload the reviewer/source ZIP.
4. Fill the listing using `docs/extension_store_listing_firefox.md`.
5. Paste reviewer notes from `docs/extension_reviewer_notes.md`.
6. Use Firefox desktop as the compatible platform.
7. Do not mark the add-on experimental unless reduced visibility is intentional.
8. Be ready for reviewer questions about:
   - why `cookies`, `activeTab`, `scripting`, and `<all_urls>` are needed
   - generated static assets `shared-config.js`, `study-snapshot.js`, and `tracker-index.js`
   - local-only privacy posture with no data transmission

## Submit Chrome Immediately After

1. Open the existing AECCS item in the Chrome Web Store Developer Dashboard.
2. Upload the Chrome ZIP from `dist/extension-release/`.
3. Fill the listing using `docs/extension_store_listing_chrome.md`.
4. In the Privacy tab, use these exact justifications:
   - `cookies`: read cookies for the current site so they can be classified and counted
   - `activeTab`: access the current page URL when the user clicks the extension
   - `scripting`: inject the consent scanner only on demand into the active tab
   - `<all_urls>`: required for the cookies API to read cookies for the active page; not used for remote requests
5. Privacy answers should state:
   - no off-device transfer
   - no sale of user data
   - no analytics or telemetry
   - no remote code
   - privacy policy URL: `https://erenozen.github.io/AECCS/privacy-policy.html`
6. Use deferred publishing so Chrome approval does not go live before Firefox is ready.

## Launch Window

1. Wait for Firefox approval, or at least for Firefox review to be near completion.
2. Publish Chrome from deferred state and publish Firefox on the same day.
3. Save both public store URLs into repo docs after launch.
4. Tag the repo release after both listings are live.

## First-Week Monitoring

1. Watch AMO and Chrome review feedback closely.
2. Watch GitHub issues for user support.
3. Avoid privacy-posture or permission changes until the first release stabilizes.
