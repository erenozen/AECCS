# AECCS Firefox Add-ons Listing

## Add-on Name

AECCS Cookie Compliance Checker

## Summary

Local, user-initiated GDPR cookie-consent auditor with session-limited post-interaction analysis for the current website.

## Description

AECCS is a lightweight Firefox extension for people who want evidence-based cookie-consent auditing without auto-clicking banners or blocking site functionality.

The add-on audits the page you are currently visiting and highlights:

- live cookies, third-party cookies, and tracker-heavy pages
- detected CMPs and consent-banner presence
- missing reject options and multi-layer rejection
- asymmetric buttons, hidden reject paths, preselected checkboxes, confusing language, forced action, and transparency signals
- accept vs reject UX comparison using the controls that are actually visible on the page
- study-backed privacy-tool guidance tied to the issues found on the current site
- session-limited before/after consent-state comparisons when the user opens AECCS before interacting with the banner

AECCS is grounded in the completed 1000-site combined study snapshot (`combined-1000`, generated March 6, 2026). That study context is bundled statically inside the extension and used only as frozen local reference data. The add-on does not auto-click consent banners, does not block requests, does not log page-wide clicks, and does not send browsing data to external services.

## AMO Reviewer-Friendly Notes

- The add-on is user-initiated and session-limited: analysis starts only when the user opens the popup, and any consent watch is limited to the tracked banner flow for the current tab session.
- The generated static assets `extension/lib/shared-config.js`, `extension/lib/study-snapshot.js`, and `extension/lib/tracker-index.js` are local artifacts built from repository data and filter lists, not remote code.
- Runtime behavior is local-only: no analytics, telemetry, remote requests, or external service integrations.

## Public URLs

- Homepage: https://github.com/erenozen/AECCS
- Support: https://github.com/erenozen/AECCS/issues
- Privacy policy: https://erenozen.github.io/AECCS/privacy-policy.html
