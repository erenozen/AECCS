# AECCS Chrome Web Store Listing

## Name

AECCS Cookie Compliance Checker

## Short Description

Passive, research-grounded GDPR cookie-consent auditor for the current website.

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

AECCS is grounded in the completed 1000-site combined study snapshot (`combined-1000`, generated March 6, 2026). The extension uses that completed combined snapshot as frozen local reference data. It does not fetch remote reports, does not simulate PETs live, and does not transmit browsing data off-device.

## Privacy Practices Summary

- No data sold to third parties
- No data transferred off-device
- No analytics or telemetry
- No remote code
- All analysis is triggered on demand when the user opens the popup

## Permission Justification Summary

- `cookies`: read cookies for the current site so they can be classified and counted
- `activeTab`: access the current page URL when the user clicks the extension
- `scripting`: inject the consent scanner only on demand into the active tab
- `<all_urls>` host permission: required for the cookies API to read cookies for the active page; not used for remote requests

## Public URLs

- Homepage: https://github.com/erenozen/AECCS
- Support: https://github.com/erenozen/AECCS/issues
- Privacy policy: https://erenozen.github.io/AECCS/privacy-policy.html
