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

  // ── Frozen extension study snapshot (1000 sites, March 2026) ────────────
  // These values are a lightweight, static summary used only for popup copy
  // and CMP/PET provenance inside the extension.

  const STUDY_METADATA = {
    label: "AECCS 1000-site study snapshot",
    snapshotDate: "2026-03-06",
    snapshotDateLabel: "March 2026",
    sampleSize: 1000,
    successfulCrawls: 861,
    bannerSites: 861,
    avgCompliance: 27.4,
    missingRejectRate: 0.814,
    multiLayerRate: 0.042,
    rejectReducesTrackersRate: 0.094,
    rejectEliminatesTrackersRate: 0.021,
  };

  const PET_STUDY_RESULTS = [
    {
      name: "Brave Shields",
      type: "browser",
      studyRank: 1,
      trackerReductionPct: 22.8,
      studyLabel: "+22.8% avg tracker reduction in study",
      highlight: "Best average tracker reduction in the AECCS 1000-site snapshot.",
    },
    {
      name: "Privacy Badger",
      type: "extension",
      studyRank: 2,
      trackerReductionPct: 21.0,
      studyLabel: "+21.0% avg tracker reduction in study",
      highlight: "Strong heuristic-based tracker blocking across 881 tested sites.",
    },
    {
      name: "uBlock Origin",
      type: "extension",
      studyRank: 3,
      trackerReductionPct: 22.4,
      studyLabel: "+22.4% avg tracker reduction in study",
      highlight: "Open-source blocker with consistently strong tracker reduction.",
    },
    {
      name: "Firefox ETP Strict",
      type: "browser",
      studyRank: 4,
      trackerReductionPct: -0.5,
      studyLabel: "-0.5% avg tracker reduction in study",
      highlight: "Firefox's strict mode — minimal net reduction in the 1000-site snapshot.",
    },
    {
      name: "Consent-O-Matic",
      type: "extension",
      studyRank: 5,
      trackerReductionPct: -11.2,
      studyLabel: "-11.2% avg tracker reduction in study",
      highlight: "Consent-flow tool rather than a network blocker; mixed reduction results.",
    },
    {
      name: "Firefox ETP Standard",
      type: "browser",
      studyRank: 6,
      trackerReductionPct: -2.2,
      studyLabel: "-2.2% avg tracker reduction in study",
      highlight: "Default Firefox experience with modest tracker reduction.",
    },
  ];

  // ── PET Recommendations (frozen to the March 1, 2026 study snapshot) ────
  // The extension keeps a lightweight ranking model for relevance, while the
  // study-backed fields shown to users come from the final 1000-site run.

  const PET_PROFILES = [
    {
      name: "Brave Shields",
      type: "browser",
      description: "Built-in browser protection with the best average tracker reduction in the study.",
      helpsWith: ["pre_consent_trackers", "advertising", "fingerprinting", "analytics"],
      studyTrackerReductionPct: 22.8,
      studyRank: 1,
      studyLabel: "+22.8% avg tracker reduction across 878 sites",
      recommendationWeight: 100,
      url: "https://brave.com",
    },
    {
      name: "uBlock Origin",
      type: "extension",
      description: "Open-source content blocker with consistently strong tracker reduction.",
      helpsWith: ["pre_consent_trackers", "advertising", "analytics"],
      studyTrackerReductionPct: 22.4,
      studyRank: 3,
      studyLabel: "+22.4% avg tracker reduction across 878 sites",
      recommendationWeight: 90,
      url: "https://ublockorigin.com",
    },
    {
      name: "Privacy Badger",
      type: "extension",
      description: "EFF's heuristic tracker blocker with strong results in the 1000-site study.",
      helpsWith: ["pre_consent_trackers", "fingerprinting"],
      studyTrackerReductionPct: 21.0,
      studyRank: 2,
      studyLabel: "+21.0% avg tracker reduction across 881 sites",
      recommendationWeight: 80,
      url: "https://privacybadger.org",
    },
    {
      name: "Firefox ETP Strict",
      type: "browser",
      description: "Firefox's stricter built-in protection with minimal net reduction in the study.",
      helpsWith: ["pre_consent_trackers", "fingerprinting", "social"],
      studyTrackerReductionPct: -0.5,
      studyRank: 4,
      studyLabel: "-0.5% avg tracker reduction across 890 sites",
      recommendationWeight: 65,
      url: "https://support.mozilla.org/en-US/kb/enhanced-tracking-protection-firefox-desktop",
    },
    {
      name: "Firefox ETP Standard",
      type: "browser",
      description: "Firefox's default tracker protection with modest results in the study.",
      helpsWith: ["pre_consent_trackers", "social"],
      studyTrackerReductionPct: -2.2,
      studyRank: 6,
      studyLabel: "-2.2% avg tracker reduction across 890 sites",
      recommendationWeight: 55,
      url: "https://support.mozilla.org/en-US/kb/enhanced-tracking-protection-firefox-desktop",
    },
    {
      name: "Consent-O-Matic",
      type: "extension",
      description: "Auto-rejects banners when a site exposes a usable reject path.",
      helpsWith: ["dark_patterns", "reject_effort"],
      studyTrackerReductionPct: -11.2,
      studyRank: 5,
      studyLabel: "-11.2% avg tracker reduction across 896 sites",
      recommendationWeight: 50,
      url: "https://consentomatic.au.dk",
    },
  ];

  const CMP_STUDY_RESULTS = [
    {
      name: "Didomi",
      sampleSize: 49,
      avgScore: 36.2,
      rejectRate: 0.388,
      petScore: 24.9,
      highlight: "Best-performing CMP in the AECCS 1000-site snapshot.",
    },
    {
      name: "OneTrust",
      sampleSize: 138,
      avgScore: 35.5,
      rejectRate: 0.406,
      petScore: 24.1,
      highlight: "Most widely deployed CMP with reject available on 40.6% of sites.",
    },
    {
      name: "TrustArc",
      sampleSize: 121,
      avgScore: 28.8,
      rejectRate: 0.240,
      petScore: 16.3,
      highlight: "Third-ranked CMP with reject available on 24% of sampled sites.",
    },
    {
      name: "Cookiebot",
      sampleSize: 91,
      avgScore: 22.7,
      rejectRate: 0.132,
      petScore: 12.1,
      highlight: "Low reject rate (13.2%) despite being deployed on 91 sites.",
    },
    {
      name: "Quantcast",
      sampleSize: 28,
      avgScore: 18.5,
      rejectRate: 0.143,
      petScore: 10.6,
      highlight: "Low compliance scores with 100% pre-consent tracker rate.",
    },
    {
      name: "Usercentrics",
      sampleSize: 18,
      avgScore: 20.6,
      rejectRate: 0.056,
      petScore: 9.1,
      highlight: "Lowest reject availability (5.6%) among all CMPs in the snapshot.",
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

  // ── CMP compliance statistics (1000-site final study snapshot) ──────────

  const CMP_STATS = {
    "OneTrust":     { avgScore: 35.5, sampleSize: 138, rejectRate: 0.406, petScore: 24.1 },
    "Cookiebot":    { avgScore: 22.7, sampleSize: 91,  rejectRate: 0.132, petScore: 12.1 },
    "Quantcast":    { avgScore: 18.5, sampleSize: 28,  rejectRate: 0.143, petScore: 10.6 },
    "TrustArc":     { avgScore: 28.8, sampleSize: 121, rejectRate: 0.240, petScore: 16.3 },
    "Didomi":       { avgScore: 36.2, sampleSize: 49,  rejectRate: 0.388, petScore: 24.9 },
    "Usercentrics": { avgScore: 20.6, sampleSize: 18,  rejectRate: 0.056, petScore: 9.1 },
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
      summary: "The extension references one shared 1000-site snapshot spanning Brave Shields, Firefox ETP Standard/Strict, uBlock Origin, Privacy Badger, and Consent-O-Matic.",
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
      "Includes government/public-sector context and a March 2026 post-DMA snapshot",
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
