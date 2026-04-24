# AECCS Chrome Web Store Listing

## Name

AECCS Cookie Compliance Checker

## Short Description

Local, user-initiated GDPR cookie-consent auditor with session-limited post-interaction analysis for the current website.

## Single Purpose

AECCS analyzes the currently loaded page locally to assess cookie-consent GDPR compliance using live cookies, consent-banner UX, dark-pattern detection, and frozen study-backed reference data.

## Detailed Description

AECCS is a lightweight Chrome extension for people who want evidence-based cookie-consent auditing without auto-clicking banners or blocking site functionality.

It audits the page you are currently visiting and highlights:

- live cookies, third-party cookies, and tracker-heavy pages
- detected CMPs and consent-banner presence
- missing reject options and multi-layer rejection
- asymmetric buttons, hidden reject paths, preselected checkboxes, confusing language, forced action, and transparency signals
- accept vs reject UX comparison using the controls that are actually visible on the page
- study-backed privacy-tool guidance tied to the issues found on the current site
- session-limited before/after consent-state comparisons when the user opens AECCS before interacting with the banner
- an optional locally saved browsing-setup profile so the popup can explain how blockers or consent tools may affect the measured result

AECCS is grounded in the completed 1000-site combined study snapshot (`combined-1000`, generated March 6, 2026). The extension uses that completed combined snapshot as frozen local reference data. It does not fetch remote reports, does not simulate PETs live, does not log page-wide clicks, and does not transmit browsing data off-device. The only persistent data is the user's optional browsing-setup declaration stored locally in the browser; AECCS does not store site-specific audit history.

## Privacy Practices Summary

- No data sold to third parties
- No data transferred off-device
- No analytics or telemetry
- No remote code
- Analysis is user-initiated when the user opens the popup, and any consent watch is limited to the tracked banner flow for the current tab session
- One optional local preference object may be stored so the popup can remember the user's declared browsing setup

## Permission Justification Summary

- `cookies`: read cookies for the current site so they can be classified and counted
- `activeTab`: access the current page URL when the user clicks the extension
- `scripting`: inject the consent scanner only on demand into the active tab
- `storage`: save the user's optional browsing-setup declaration locally so AECCS can add the right caveats to measured results
- `<all_urls>` host permission: required for the cookies API to read cookies for the active page; not used for remote requests

## Public URLs

- Homepage: https://github.com/erenozen/AECCS
- Support: https://github.com/erenozen/AECCS/issues
- Privacy policy: https://erenozen.github.io/AECCS/privacy-policy.html
