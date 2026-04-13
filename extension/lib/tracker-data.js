/*
 * AECCS Tracker Data — ported from the Python pipeline.
 *
 * Sources:
 *   analysis/classifier.py  → FALLBACK_TRACKERS, COOKIE_HEURISTICS
 *   config.py               → CMP_SIGNATURES, CONSENT_BUTTON_KEYWORDS, COMPLIANCE_WEIGHTS
 *   analysis/scoring.py     → PRIVACY_LINK_KEYWORDS, PURPOSE_KEYWORDS, GRADES
 *   scraper/crawler.py      → BANNER_SELECTORS
 */

const AECCS = (() => {
  "use strict";

  // ── Fallback tracker map (39 domains) ─────────────────────────────────────
  // From analysis/classifier.py lines 39-88
  const FALLBACK_TRACKERS = {
    // Advertising
    "doubleclick.net":          { vendor: "Google",          category: "Advertising" },
    "googlesyndication.com":    { vendor: "Google",          category: "Advertising" },
    "googleadservices.com":     { vendor: "Google",          category: "Advertising" },
    "googleads.g.doubleclick.net": { vendor: "Google",       category: "Advertising" },
    "adnxs.com":                { vendor: "Xandr/Microsoft", category: "Advertising" },
    "criteo.com":               { vendor: "Criteo",          category: "Advertising" },
    "criteo.net":               { vendor: "Criteo",          category: "Advertising" },
    "amazon-adsystem.com":      { vendor: "Amazon",          category: "Advertising" },
    "adsrvr.org":               { vendor: "The Trade Desk",  category: "Advertising" },
    "rubiconproject.com":       { vendor: "Rubicon Project", category: "Advertising" },
    "pubmatic.com":             { vendor: "PubMatic",        category: "Advertising" },
    "casalemedia.com":          { vendor: "Casale Media",    category: "Advertising" },
    "openx.net":                { vendor: "OpenX",           category: "Advertising" },
    "taboola.com":              { vendor: "Taboola",         category: "Advertising" },
    "outbrain.com":             { vendor: "Outbrain",        category: "Advertising" },
    // Analytics
    "google-analytics.com":     { vendor: "Google",          category: "Analytics" },
    "googletagmanager.com":     { vendor: "Google",          category: "Analytics" },
    "hotjar.com":               { vendor: "Hotjar",          category: "Analytics" },
    "hotjar.io":                { vendor: "Hotjar",          category: "Analytics" },
    "mouseflow.com":            { vendor: "Mouseflow",       category: "Analytics" },
    "newrelic.com":             { vendor: "New Relic",       category: "Analytics" },
    "segment.io":               { vendor: "Segment",         category: "Analytics" },
    "segment.com":              { vendor: "Segment",         category: "Analytics" },
    "amplitude.com":            { vendor: "Amplitude",       category: "Analytics" },
    "mixpanel.com":             { vendor: "Mixpanel",        category: "Analytics" },
    "clarity.ms":               { vendor: "Microsoft",       category: "Analytics" },
    "scorecardresearch.com":    { vendor: "comScore",        category: "Analytics" },
    "chartbeat.com":            { vendor: "Chartbeat",       category: "Analytics" },
    "chartbeat.net":            { vendor: "Chartbeat",       category: "Analytics" },
    // Social
    "facebook.net":             { vendor: "Meta",            category: "Social" },
    "facebook.com":             { vendor: "Meta",            category: "Social" },
    "fbcdn.net":                { vendor: "Meta",            category: "Social" },
    "connect.facebook.net":     { vendor: "Meta",            category: "Social" },
    "twitter.com":              { vendor: "X/Twitter",       category: "Social" },
    "platform.twitter.com":     { vendor: "X/Twitter",       category: "Social" },
    "linkedin.com":             { vendor: "LinkedIn",        category: "Social" },
    "snap.licdn.com":           { vendor: "LinkedIn",        category: "Social" },
    "tiktok.com":               { vendor: "TikTok",          category: "Social" },
    // Fingerprinting
    "demdex.net":               { vendor: "Adobe",           category: "Fingerprinting" },
    "omtrdc.net":               { vendor: "Adobe",           category: "Fingerprinting" },
    "krxd.net":                 { vendor: "Salesforce/Krux", category: "Fingerprinting" },
    "bluekai.com":              { vendor: "Oracle",          category: "Fingerprinting" },
    "exelator.com":             { vendor: "Nielsen",         category: "Fingerprinting" },
    "quantserve.com":           { vendor: "Quantcast",       category: "Fingerprinting" },
  };

  // ── Heuristic cookie-name patterns (13 regexes) ──────────────────────────
  // From analysis/classifier.py lines 91-105
  const COOKIE_HEURISTICS = [
    { pattern: /^_ga$|^_ga_/i,                                        vendor: "Google",    category: "Analytics" },
    { pattern: /^_gid$/i,                                              vendor: "Google",    category: "Analytics" },
    { pattern: /^_gat/i,                                               vendor: "Google",    category: "Analytics" },
    { pattern: /^__utm/i,                                              vendor: "Google",    category: "Analytics" },
    { pattern: /_fbp|_fbc|fbp/i,                                       vendor: "Meta",      category: "Social" },
    { pattern: /^_hjid|^_hj/i,                                         vendor: "Hotjar",    category: "Analytics" },
    { pattern: /^_tt_/i,                                                vendor: "TikTok",    category: "Social" },
    { pattern: /^li_|^bcookie|^lidc/i,                                  vendor: "LinkedIn",  category: "Social" },
    { pattern: /^IDE$|^test_cookie$|^DSID$/i,                           vendor: "Google",    category: "Advertising" },
    { pattern: /^NID$|^APISID$|^SAPISID$|^SID$|^SSID$|^HSID$/i,       vendor: "Google",    category: "Functional" },
    { pattern: /^_pin_|^_pinterest_/i,                                  vendor: "Pinterest", category: "Social" },
    { pattern: /^amp_/i,                                                vendor: "Amplitude", category: "Analytics" },
    { pattern: /^mp_/i,                                                 vendor: "Mixpanel",  category: "Analytics" },
  ];

  // ── CMP Detection Signatures ─────────────────────────────────────────────
  // From config.py lines 305-312
  const CMP_SIGNATURES = {
    "OneTrust":     ["onetrust", "optanon", "cookie-consent-banner"],
    "Cookiebot":    ["cookiebot", "CookieConsent", "Cybot"],
    "Quantcast":    ["quantcast", "__cmpLocator", "cmp2.js"],
    "TrustArc":     ["trustarc", "truste", "consent-manager"],
    "Didomi":       ["didomi"],
    "Usercentrics": ["usercentrics"],
  };

  // ── Consent Button Keywords (multilingual, 7 languages) ──────────────────
  // From config.py lines 268-301
  const CONSENT_BUTTON_KEYWORDS = {
    accept: [
      // English
      "Accept", "Accept All", "Accept Cookies", "I Agree", "Allow All",
      // German
      "Akzeptieren", "Alle akzeptieren", "Zustimmen", "Alle Cookies akzeptieren",
      // French
      "Accepter", "Tout accepter", "J'accepte", "Accepter tout",
      // Dutch
      "Accepteren", "Alle accepteren", "Alle cookies accepteren",
      // Spanish
      "Aceptar", "Aceptar todo", "Aceptar todas",
      // Italian
      "Accetta", "Accetta tutto", "Accetta tutti",
      // Turkish
      "Kabul Et", "Tümünü Kabul Et", "İzin Ver",
    ],
    reject: [
      // English
      "Reject", "Reject All", "Decline", "Deny", "Refuse All",
      // German
      "Ablehnen", "Alle ablehnen",
      // French
      "Refuser", "Tout refuser",
      // Dutch
      "Weigeren", "Alle weigeren",
      // Spanish
      "Rechazar", "Rechazar todo", "Rechazar todas",
      // Italian
      "Rifiuta", "Rifiuta tutto", "Rifiuta tutti",
      // Turkish
      "Reddet", "Tümünü Reddet",
    ],
  };

  // ── GDPR Compliance Scoring Weights ──────────────────────────────────────
  // From config.py lines 316-323
  const COMPLIANCE_WEIGHTS = {
    no_pre_consent_trackers:   0.25,
    reject_option_available:   0.20,
    equal_accept_reject_effort: 0.15,
    no_dark_patterns:          0.15,
    post_reject_compliance:    0.15,
    transparent_information:   0.10,
  };

  // ── Grade thresholds ─────────────────────────────────────────────────────
  // From analysis/scoring.py lines 35-41
  const GRADES = [
    { threshold: 90, grade: "A" },
    { threshold: 75, grade: "B" },
    { threshold: 60, grade: "C" },
    { threshold: 40, grade: "D" },
    { threshold: 0,  grade: "F" },
  ];

  // ── Privacy-policy link keywords (multilingual) ──────────────────────────
  // From analysis/scoring.py lines 44-52
  const PRIVACY_LINK_KEYWORDS = [
    "privacy policy", "privacy notice", "data protection",
    "datenschutz", "datenschutzerklaerung", "datenschutzerklärung",
    "politique de confidentialité", "politique de confidentialite",
    "privacybeleid", "privacyverklaring",
    "politica de privacidad", "política de privacidad",
    "informativa sulla privacy",
    "gizlilik politikası", "gizlilik politikasi",
  ];

  // ── Purpose keywords for transparency check ─────────────────────────────
  // From analysis/scoring.py lines 55-60
  const PURPOSE_KEYWORDS = [
    "analytics", "advertising", "personalization", "marketing",
    "functional", "preferences", "statistics", "targeting",
    "analyse", "werbung", "personalisierung",
    "analytique", "publicité", "personnalisation",
  ];

  // ── Vendor keywords for transparency check ──────────────────────────────
  // From analysis/scoring.py line 221
  const VENDOR_KEYWORDS = [
    "google", "facebook", "meta", "analytics", "advertisement",
  ];

  // ── Consent banner CSS selectors ─────────────────────────────────────────
  // From scraper/crawler.py lines 56-81
  const BANNER_SELECTORS = [
    "#cookie-banner",
    "#cookie-consent",
    "#consent-banner",
    "#cookieConsent",
    "#onetrust-banner-sdk",
    "#CybotCookiebotDialog",
    "#qc-cmp2-container",
    ".cookie-banner",
    ".cookie-consent",
    ".consent-banner",
    ".cookie-notice",
    "[class*='cookie-banner']",
    "[class*='cookie-consent']",
    "[class*='consent-banner']",
    "[id*='cookie']",
    "[id*='consent']",
    "[id*='gdpr']",
    "[id*='privacy']",
    "[class*='cookie']",
    "[class*='consent']",
    "[class*='gdpr']",
    "[role='dialog'][aria-label*='cookie' i]",
    "[role='dialog'][aria-label*='consent' i]",
    "div[data-testid*='cookie']",
    "div[data-testid*='consent']",
  ];

  // ── Frozen extension study snapshot (100 sites, 1 March 2026) ───────────
  // These values are a lightweight, static summary used only for popup copy
  // and CMP/PET provenance inside the extension.

  const STUDY_METADATA = {
    label: "AECCS 100-site study snapshot",
    snapshotDate: "2026-03-01",
    snapshotDateLabel: "March 1, 2026",
    sampleSize: 100,
    successfulCrawls: 97,
    bannerSites: 72,
    avgCompliance: 33.1,
    missingRejectRate: 0.69,
    multiLayerRate: 0.14,
    rejectReducesTrackersRate: 0.072,
    rejectEliminatesTrackersRate: 0.093,
  };

  const PET_STUDY_RESULTS = [
    {
      name: "Brave Shields",
      type: "browser",
      studyRank: 1,
      trackerReductionPct: 14.7,
      studyLabel: "+14.7% avg tracker reduction in study",
      highlight: "Best average tracker reduction in the AECCS 100-site snapshot.",
    },
    {
      name: "Firefox ETP Strict",
      type: "browser",
      studyRank: 2,
      trackerReductionPct: -8.7,
      studyLabel: "-8.7% avg tracker reduction in study",
      highlight: "Widely deployed browser protection with mixed results in the snapshot.",
    },
    {
      name: "uBlock Origin",
      type: "extension",
      studyRank: 3,
      trackerReductionPct: -13.7,
      studyLabel: "-13.7% avg tracker reduction in study",
      highlight: "Strong site-level wins, but a negative snapshot-wide average in this methodology.",
    },
    {
      name: "Firefox ETP Standard",
      type: "browser",
      studyRank: 4,
      trackerReductionPct: -16.3,
      studyLabel: "-16.3% avg tracker reduction in study",
      highlight: "Represents the default Firefox experience in the PET comparison.",
    },
    {
      name: "Consent-O-Matic",
      type: "extension",
      studyRank: 5,
      trackerReductionPct: -17.7,
      studyLabel: "-17.7% avg tracker reduction in study",
      highlight: "Relevant as a consent-flow tool rather than a network blocker.",
    },
    {
      name: "Privacy Badger",
      type: "extension",
      studyRank: 6,
      trackerReductionPct: -18.4,
      studyLabel: "-18.4% avg tracker reduction in study",
      highlight: "Heuristic blocker with site-specific wins but a negative snapshot average.",
    },
  ];

  // ── PET Recommendations (frozen to the March 1, 2026 study snapshot) ────
  // The extension keeps a lightweight ranking model for relevance, while the
  // study-backed fields shown to users come from the final 100-site run.

  const PET_PROFILES = [
    {
      name: "Brave Shields",
      type: "browser",
      description: "Built-in browser protection with the best average tracker reduction in the study.",
      helpsWith: ["pre_consent_trackers", "advertising", "fingerprinting", "analytics"],
      studyTrackerReductionPct: 14.7,
      studyRank: 1,
      studyLabel: "+14.7% avg tracker reduction in study",
      recommendationWeight: 100,
      url: "https://brave.com",
    },
    {
      name: "uBlock Origin",
      type: "extension",
      description: "Open-source blocker with strong site-level wins, but a negative study-wide average.",
      helpsWith: ["pre_consent_trackers", "advertising", "analytics"],
      studyTrackerReductionPct: -13.7,
      studyRank: 3,
      studyLabel: "-13.7% avg tracker reduction in study",
      recommendationWeight: 90,
      url: "https://ublockorigin.com",
    },
    {
      name: "Firefox ETP Strict",
      type: "browser",
      description: "Firefox's stricter built-in protection, with mixed real-study results.",
      helpsWith: ["pre_consent_trackers", "fingerprinting", "social"],
      studyTrackerReductionPct: -8.7,
      studyRank: 2,
      studyLabel: "-8.7% avg tracker reduction in study",
      recommendationWeight: 80,
      url: "https://support.mozilla.org/en-US/kb/enhanced-tracking-protection-firefox-desktop",
    },
    {
      name: "Privacy Badger",
      type: "extension",
      description: "EFF's heuristic tracker blocker with site-specific wins but a negative study average.",
      helpsWith: ["pre_consent_trackers", "fingerprinting"],
      studyTrackerReductionPct: -18.4,
      studyRank: 6,
      studyLabel: "-18.4% avg tracker reduction in study",
      recommendationWeight: 65,
      url: "https://privacybadger.org",
    },
    {
      name: "Firefox ETP Standard",
      type: "browser",
      description: "Firefox's default tracker protection with modest friction and mixed study outcomes.",
      helpsWith: ["pre_consent_trackers", "social"],
      studyTrackerReductionPct: -16.3,
      studyRank: 4,
      studyLabel: "-16.3% avg tracker reduction in study",
      recommendationWeight: 55,
      url: "https://support.mozilla.org/en-US/kb/enhanced-tracking-protection-firefox-desktop",
    },
    {
      name: "Consent-O-Matic",
      type: "extension",
      description: "Auto-rejects banners when a site exposes a usable reject path.",
      helpsWith: ["dark_patterns", "reject_effort"],
      studyTrackerReductionPct: -17.7,
      studyRank: 5,
      studyLabel: "-17.7% avg tracker reduction in study",
      recommendationWeight: 50,
      url: "https://consentomatic.au.dk",
    },
  ];

  const CMP_STUDY_RESULTS = [
    {
      name: "OneTrust",
      sampleSize: 26,
      avgScore: 45.1,
      rejectRate: 0.615,
      petScore: 33.4,
      highlight: "Best-performing CMP in the AECCS snapshot.",
    },
    {
      name: "TrustArc",
      sampleSize: 17,
      avgScore: 37.2,
      rejectRate: 0.471,
      petScore: 24.1,
      highlight: "Second-best CMP with a visible reject path on nearly half the sampled sites.",
    },
    {
      name: "Cookiebot",
      sampleSize: 6,
      avgScore: 18.8,
      rejectRate: 0.0,
      petScore: 5.6,
      highlight: "Low-score snapshot result with no sampled direct reject availability.",
    },
    {
      name: "Usercentrics",
      sampleSize: 1,
      avgScore: 16.5,
      rejectRate: 0.0,
      petScore: 5.0,
      highlight: "Single-site sample in the snapshot; included for provenance completeness.",
    },
    {
      name: "Didomi",
      sampleSize: 3,
      avgScore: 14.0,
      rejectRate: 0.0,
      petScore: 4.0,
      highlight: "Low-score snapshot result with no sampled direct reject availability.",
    },
    {
      name: "Quantcast",
      sampleSize: 1,
      avgScore: 18.5,
      rejectRate: 0.0,
      petScore: 2.2,
      highlight: "Lowest CMP PET score in the AECCS snapshot.",
    },
  ];

  // ── Government domain suffixes ───────────────────────────────────────────
  // Government / public-sector sites have stricter GDPR obligations.

  const GOV_SUFFIXES = [
    ".gov", ".gov.uk", ".gov.au", ".gov.tr", ".gov.br", ".gov.in",
    ".gob.es", ".gob.mx", ".gouv.fr", ".governo.it", ".bund.de",
    ".govt.nz", ".gov.ie", ".gov.pl", ".gov.gr", ".gov.pt",
    ".gov.ro", ".gov.bg", ".gov.cz", ".gov.hu", ".gov.sk",
    ".gov.si", ".gov.lt", ".gov.lv", ".gov.ee", ".gov.hr",
    ".gov.mt", ".gov.cy",
  ];

  // ── CMP compliance statistics (100-site final study snapshot) ───────────

  const CMP_STATS = {
    "OneTrust":     { avgScore: 45.1, sampleSize: 26, rejectRate: 0.615, petScore: 33.4 },
    "Cookiebot":    { avgScore: 18.8, sampleSize: 6,  rejectRate: 0.0,   petScore: 5.6 },
    "Quantcast":    { avgScore: 18.5, sampleSize: 1,  rejectRate: 0.0,   petScore: 2.2 },
    "TrustArc":     { avgScore: 37.2, sampleSize: 17, rejectRate: 0.471, petScore: 24.1 },
    "Didomi":       { avgScore: 14.0, sampleSize: 3,  rejectRate: 0.0,   petScore: 4.0 },
    "Usercentrics": { avgScore: 16.5, sampleSize: 1,  rejectRate: 0.0,   petScore: 5.0 },
  };

  // ── Dark pattern explanations ───────────────────────────────────────────
  // User-friendly explanations + GDPR article references for each dark pattern.

  const DARK_PATTERN_INFO = {
    "Pre-selected checkboxes": {
      description: "Non-essential cookie categories are pre-checked, tricking users into accepting tracking.",
      gdprArticle: "Art. 7(2) — Consent must not be bundled; Art. 4(11) — requires freely given, specific consent.",
      severity: "high",
    },
    "Asymmetric buttons": {
      description: "The accept button is visually larger, bolder, or more prominent than the reject button.",
      gdprArticle: "Art. 7(2), Recital 42 — Consent must be presented without undue influence.",
      severity: "medium",
    },
    "Hidden reject button": {
      description: "The reject option exists but is hidden via CSS (invisible, zero-size, or blending with background).",
      gdprArticle: "Art. 7(3) — Withdrawal of consent must be as easy as giving it.",
      severity: "high",
    },
    "Missing reject option": {
      description: "The banner offers no direct reject option, so users cannot decline tracking in one step.",
      gdprArticle: "Art. 7(3) — Refusing consent must be as easy as giving it.",
      severity: "high",
    },
    "Multi-layer rejection": {
      description: "Rejecting cookies takes more clicks than accepting them, creating unequal effort.",
      gdprArticle: "Art. 7(3) — Withdrawal of consent must be as easy as giving it.",
      severity: "medium",
    },
    "Confusing language": {
      description: "Banner text uses guilt-tripping, double negatives, or ambiguous button labels to manipulate choice.",
      gdprArticle: "Art. 12(1) — Information must be concise, transparent, and in clear language.",
      severity: "medium",
    },
    "Forced action / Cookie wall": {
      description: "Site content is blocked until the user accepts cookies — a 'cookie wall'.",
      gdprArticle: "Art. 7(4), EDPB Guidelines 05/2020 — consent is not freely given if access is conditional.",
      severity: "critical",
    },
  };

  const RESEARCH_HIGHLIGHTS = [
    {
      title: "PETs × Dark Patterns",
      summary: "AECCS combines live consent-banner findings with study-backed PET guidance instead of treating them as separate problems.",
    },
    {
      title: "Six PETs, One Snapshot",
      summary: "The extension references one shared 100-site snapshot spanning Brave Shields, Firefox ETP Standard/Strict, uBlock Origin, Privacy Badger, and Consent-O-Matic.",
    },
    {
      title: "Government/Public-Sector Coverage",
      summary: "The underlying AECCS corpus includes public-sector domains, which matters because those sites face stronger consent obligations.",
    },
    {
      title: "Reproducible Pipeline",
      summary: "The released pipeline runs crawl → classify → dark-pattern detect → score → CMP analysis → PET comparison → reporting.",
    },
  ];

  const CLAIM_GUARDRAILS = {
    positioning:
      "AECCS is a passive, research-grounded cookie-consent auditor for the current page.",
    supportedClaims: [
      "Combines dark-pattern findings with study-backed PET guidance",
      "Surfaces six end-user PETs in one shared study snapshot",
      "Includes government/public-sector context and a March 1, 2026 post-DMA snapshot",
      "Built on a reproducible open-source measurement pipeline",
    ],
    unsupportedClaims: [
      "First to detect dark patterns",
      "First to measure pre-consent tracking",
      "First CMP study",
      "First legal analysis of GDPR violations",
    ],
    notThis: [
      "Not a blocker or auto-clicker",
      "Not a remote scanner",
      "Not a generic site-fix or copy-paste remediation tool",
    ],
  };

  return {
    FALLBACK_TRACKERS,
    COOKIE_HEURISTICS,
    CMP_SIGNATURES,
    CONSENT_BUTTON_KEYWORDS,
    COMPLIANCE_WEIGHTS,
    GRADES,
    PRIVACY_LINK_KEYWORDS,
    PURPOSE_KEYWORDS,
    VENDOR_KEYWORDS,
    BANNER_SELECTORS,
    STUDY_METADATA,
    PET_STUDY_RESULTS,
    PET_PROFILES,
    CMP_STUDY_RESULTS,
    GOV_SUFFIXES,
    CMP_STATS,
    DARK_PATTERN_INFO,
    RESEARCH_HIGHLIGHTS,
    CLAIM_GUARDRAILS,
  };
})();

// Make available globally (for content scripts + importScripts in service worker)
if (typeof globalThis !== "undefined") {
  globalThis.AECCS = AECCS;
}
