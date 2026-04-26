# AECCS Extension Store Listing Draft

## Short Description

Local, user-initiated GDPR cookie-consent auditor for Chrome and Firefox. Audit the current page locally, inspect live cookies and trackers, compare accept vs reject UX, and review post-interaction consent outcomes.

## Long Description

AECCS is a lightweight browser extension for people who want evidence-based cookie-consent auditing without auto-clicking banners or blocking site functionality.

It runs only when the user opens the popup. If a cookie banner is visible, AECCS captures a baseline GDPR audit and can keep watching that consent flow locally for the current tab session. If the banner is already gone, AECCS can still audit the current post-interaction cookie state when the page exposes meaningful cookie or CMP evidence.

It audits the page you are currently visiting and highlights:

- live cookies, third-party cookies, and tracker-heavy pages
- detected CMPs and consent-banner presence
- missing reject options and multi-layer rejection
- asymmetric buttons, hidden reject paths, preselected checkboxes, confusing language, forced action, and transparency signals
- accept vs reject UX comparison using the controls that are actually visible on the page
- post-interaction cookie outcomes after observed Accept All, Reject All, or Essential Only flows
- study-backed privacy-tool guidance tied to the issues found on the current site
- an optional locally saved browsing-setup profile so AECCS can explain how blockers or consent tools may affect the measured result

AECCS is grounded in the completed 1000-site combined study snapshot (`combined-1000`, generated March 6, 2026). The extension uses that completed combined snapshot, not the older smaller run, as its frozen study baseline. The extension keeps that study context static and local, so it can stay lightweight while still surfacing:

- PET effectiveness combined with dark-pattern analysis
- six end-user PETs in one study-backed product surface
- government/public-sector coverage
- post-DMA 2026 snapshot context
- reproducible open-pipeline provenance

The only persistent data is the user's optional browsing-setup declaration stored locally in the browser; AECCS does not store site-specific audit history or transmit browsing data off-device.

Project repo / methodology reference: https://github.com/erenozen/AECCS
Privacy policy: https://erenozen.github.io/AECCS/privacy-policy.html

## Key Differentiators

- Local, session-limited consent auditor, not a blocker
- Live cookie/tracker evidence plus consent UX analysis in one popup
- Accept vs reject UX comparison instead of only a yes/no consent check
- Before/after cookie-state comparison when the user opens AECCS before clicking a consent control
- Study-backed PET guidance tied to current-page findings
- CMP context and government/public-sector framing grounded in the combined dataset

## What AECCS Is Not

- Not an auto-consent clicker
- Not a blocker or tracker-removal extension
- Not a remote website scanner
- Not a generic site-fix or copy-paste remediation assistant

## Approved Framing

- Combines dark patterns with PET effectiveness in one framework
- Surfaces six end-user PETs in one study-backed surface
- Includes government/public-sector coverage
- Reflects a post-DMA 2026 combined snapshot
- Built on a reproducible open pipeline

## Banned Claims

- First to detect dark patterns
- First to measure pre-consent tracking
- First CMP study
- First legal analysis of GDPR violations

## Screenshot Plan

1. Popup top section showing score, cookie breakdown, and detected trackers.
2. Consent banner analysis plus accept vs reject UX comparison on a site with a visible settings-based reject path.
3. Dark-pattern cards and criteria breakdown.
4. Expanded `AECCS Study Insights` section showing the 1000-site provenance badge, six-PET study card, CMP context, and methodology/guardrails.
