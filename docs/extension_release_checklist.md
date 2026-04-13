# AECCS Extension Release Checklist

## Public URLs

- Homepage URL: `https://github.com/erenozen/AECCS`
- Support URL: `https://github.com/erenozen/AECCS/issues`
- Privacy policy URL: host `docs/privacy-policy.html` at a stable HTTPS URL before submission
- Recommended hosting path if using GitHub Pages: `https://erenozen.github.io/AECCS/privacy-policy.html`

## Before Packaging

1. Update `extension/manifest.json` version for the release.
2. Confirm `docs/privacy-policy.html` still matches the extension’s real behavior.
3. Confirm `docs/extension_store_listing.md`, `docs/extension_store_listing_chrome.md`, and `docs/extension_store_listing_firefox.md` use the same product framing.
4. Confirm `docs/extension_reviewer_notes.md` still matches permissions and generated assets.
5. Collect store screenshots:
   - popup score / cookie breakdown / trackers
   - consent analysis + accept vs reject UX comparison
   - dark-pattern cards + criteria breakdown
   - expanded `AECCS Study Insights`

## Build And Verify

1. Run:
   - `python scripts/package_extension_release.py --version X.Y.Z`
2. This should:
   - regenerate `study-snapshot.js`
   - regenerate `tracker-index.js`
   - build Chrome and Firefox upload ZIPs from `extension/`
   - build a reviewer/source archive
3. Run focused verification:
   - `node --check extension/lib/tracker-data.js`
   - `node --check extension/popup/popup.js`
   - `pytest -q tests/test_extension_scanner.py`
4. Manually load the packaged extension in Chrome and Firefox and confirm:
   - popup opens
   - analysis still works on demand
   - permission prompts are expected
   - privacy-policy URL is ready for store submission

## Chrome Web Store Submission

1. Create or open the Chrome Web Store developer account.
2. Upload the Chrome ZIP built from `extension/`.
3. Use the Chrome store copy from `docs/extension_store_listing_chrome.md`.
4. In privacy answers and reviewer text, state:
   - passive local auditor
   - no remote code
   - no telemetry
   - no off-device data transmission
   - permissions are required only for current-page analysis
5. Use deferred publishing so approval does not go live before Firefox is ready.

## Firefox AMO Submission

1. Create or open the AMO developer account.
2. Submit the Firefox ZIP as a listed add-on.
3. Use the Firefox listing copy from `docs/extension_store_listing_firefox.md`.
4. Paste reviewer notes from `docs/extension_reviewer_notes.md`.
5. Be ready to answer manual review questions about:
   - generated static assets
   - large tracker index file
   - local-only privacy model

## Launch Window

1. Submit Firefox slightly earlier if timing needs help.
2. Keep Chrome deferred until Firefox is approved or close to approval.
3. Publish both stores on the same day.
4. Tag the repo release after both listings are live.

## First-Week Monitoring

1. Watch store review feedback and policy messages.
2. Watch GitHub issues for user support.
3. Avoid adding permissions or changing privacy posture until the first release stabilizes.
