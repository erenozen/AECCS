/*
 * AECCS Tracker Data — extension assembly layer.
 *
 * Python-owned shared constants are generated into lib/shared-config.js and
 * loaded first. This file keeps the extension runtime API stable while
 * combining those generated values with extension-only study metadata.
 */

(() => {
  "use strict";

  const ROOT = typeof globalThis !== "undefined" ? globalThis : self;
  const TRACKER_DATA_INIT_ERROR_KEY = "_AECCSTrackerDataInitError";
  const TRACKER_DATA_INIT_STAGE_KEY = "_AECCSTrackerDataInitStage";

  function setInitStage(stage) {
    ROOT[TRACKER_DATA_INIT_STAGE_KEY] = stage;
  }

  function failInit(err) {
    ROOT[TRACKER_DATA_INIT_ERROR_KEY] = err && err.message ? err.message : String(err);
    delete ROOT._AECCSTrackerDataLoaded;
    delete ROOT.AECCS;
  }

  try {
    setInitStage("runtime");

    const SHARED = ROOT.AECCSSharedConfig;
    if (!SHARED) {
      throw new Error("AECCSSharedConfig missing. Load lib/shared-config.js before lib/tracker-data.js.");
    }

    setInitStage("assembly");

    const FALLBACK_TRACKERS = SHARED.fallbackTrackers || {};
    const COOKIE_HEURISTICS = (SHARED.cookieHeuristics || []).map(spec => ({
      ...spec,
      pattern: new RegExp(spec.pattern, spec.flags || ""),
    }));
    const CMP_SIGNATURES = SHARED.cmpSignatures || {};
    const CONSENT_VOCABULARY = SHARED.consentVocabulary || {};
    const CONSENT_BUTTON_KEYWORDS = SHARED.consentButtonKeywords || { accept: [], reject: [] };
    const SETTINGS_KEYWORDS = SHARED.settingsKeywords || [];
    const DISMISS_BUTTON_KEYWORDS = SHARED.dismissButtonKeywords || [];
    const NECESSARY_KEYWORDS = SHARED.necessaryKeywords || [];
    const BANNER_SELECTORS = SHARED.bannerSelectors || [];
    const BANNER_TEXT_KEYWORDS = SHARED.bannerTextKeywords || [];
    const BANNER_TEXT_PHRASES = SHARED.bannerTextPhrases || [];
    const BANNER_ATTR_HINTS = SHARED.bannerAttrHints || [];
    const COMPLIANCE_WEIGHTS = SHARED.complianceWeights || {};
    const STATE_OUTCOME_WEIGHTS = SHARED.stateOutcomeWeights || {};
    const GRADES = SHARED.grades || [];
    const PRIVACY_LINK_KEYWORDS = SHARED.privacyLinkKeywords || [];
    const PURPOSE_KEYWORDS = SHARED.purposeKeywords || [];
    const VENDOR_KEYWORDS = SHARED.vendorKeywords || [];
    const GUILT_TRIP_PHRASES = SHARED.guiltTripPhrases || [];
    const DOUBLE_NEGATIVE_PATTERNS = (SHARED.doubleNegativePatterns || []).map(
      spec => new RegExp(spec.pattern, spec.flags || "")
    );

  // ── Frozen extension study snapshot (1000-site combined run) ────────────
  // The extension reads this lightweight generated layer first so popup copy,
  // PET context, and CMP stats stay aligned with data/real_combined.

    const SNAPSHOT = ROOT.AECCSStudySnapshot || {
    metadata: {
      label: "AECCS 1000-site combined study snapshot",
      sourceMode: "real_combined",
      runId: "combined-1000",
      snapshotDate: "2026-03-06",
      snapshotDateLabel: "March 6, 2026",
      generatedAt: "2026-03-06T19:06:23.797825+00:00",
      sampleSize: 1000,
      successfulCrawls: 861,
      failedCrawls: 139,
      bannerSites: 595,
      sitesWithoutBanners: 266,
      avgCompliance: 27.4,
      missingRejectRate: 0.84,
      multiLayerRate: 0.105,
      rejectReducesTrackersRate: 0.076,
      rejectEliminatesTrackersRate: 0.122,
      publicSector: {
        successfulSites: 77,
        avgCompliance: 30.9,
        preConsentTrackerRate: 0.753,
      },
    },
    petStudyResults: [
      {
        name: "Brave Shields",
        type: "browser",
        studyRank: 1,
        sitesTested: 878,
        trackerReductionPct: 22.8,
        requestReductionPct: 10.9,
        studyLabel: "+22.8% avg tracker reduction in study",
        highlight: "Strongest browser-level tracker reduction in the combined 1000-site study.",
      },
      {
        name: "Privacy Badger",
        type: "extension",
        studyRank: 2,
        sitesTested: 881,
        trackerReductionPct: 21.0,
        requestReductionPct: 8.4,
        studyLabel: "+21.0% avg tracker reduction in study",
        highlight: "Strong heuristic blocking across the combined study without requiring manual rules.",
      },
      {
        name: "uBlock Origin",
        type: "extension",
        studyRank: 3,
        sitesTested: 878,
        trackerReductionPct: 22.4,
        requestReductionPct: 5.2,
        studyLabel: "+22.4% avg tracker reduction in study",
        highlight: "Consistently reduced tracker exposure across the combined study snapshot.",
      },
      {
        name: "Firefox ETP Strict",
        type: "browser",
        studyRank: 4,
        sitesTested: 890,
        trackerReductionPct: -0.5,
        requestReductionPct: -7.2,
        studyLabel: "-0.5% avg tracker reduction in study",
        highlight: "Widely deployed browser protection, but near-flat tracker reduction in this measurement setup.",
      },
      {
        name: "Consent-O-Matic",
        type: "extension",
        studyRank: 5,
        sitesTested: 896,
        trackerReductionPct: -11.2,
        requestReductionPct: -11.9,
        studyLabel: "-11.2% avg tracker reduction in study",
        highlight: "Relevant for reject-flow automation rather than network blocking.",
      },
      {
        name: "Firefox ETP Standard",
        type: "browser",
        studyRank: 6,
        sitesTested: 890,
        trackerReductionPct: -2.2,
        requestReductionPct: -16.4,
        studyLabel: "-2.2% avg tracker reduction in study",
        highlight: "Default Firefox protection with modest results in the combined study.",
      },
    ],
    cmpStudyResults: [
      {
        name: "Didomi",
        sampleSize: 49,
        avgScore: 36.2,
        rejectRate: 0.388,
        petScore: 24.9,
        studyRank: 1,
        highlight: "Best CMP in the combined study by composite PET score.",
      },
      {
        name: "OneTrust",
        sampleSize: 138,
        avgScore: 35.5,
        rejectRate: 0.406,
        petScore: 24.1,
        studyRank: 2,
        highlight: "Most common detected CMP in the combined study with comparatively frequent reject availability.",
      },
      {
        name: "TrustArc",
        sampleSize: 121,
        avgScore: 28.8,
        rejectRate: 0.24,
        petScore: 16.3,
        studyRank: 3,
        highlight: "Meaningful presence in the corpus, but lower reject availability than the top two CMPs.",
      },
      {
        name: "Cookiebot",
        sampleSize: 91,
        avgScore: 22.7,
        rejectRate: 0.132,
        petScore: 12.1,
        studyRank: 4,
        highlight: "Frequently detected, but reject remained uncommon across the combined sample.",
      },
      {
        name: "Quantcast",
        sampleSize: 28,
        avgScore: 18.5,
        rejectRate: 0.143,
        petScore: 10.6,
        studyRank: 5,
        highlight: "Low scores and limited reject availability in the combined study.",
      },
      {
        name: "Usercentrics",
        sampleSize: 18,
        avgScore: 20.6,
        rejectRate: 0.056,
        petScore: 9.1,
        studyRank: 6,
        highlight: "Lowest-scoring named CMP in the combined study snapshot.",
      },
    ],
  };

  const STUDY_METADATA = SNAPSHOT.metadata;
  const PET_STUDY_RESULTS = SNAPSHOT.petStudyResults;
  const PET_STUDY_BY_NAME = Object.fromEntries(PET_STUDY_RESULTS.map(item => [item.name, item]));

  function formatStudyMetric(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return null;
    const rounded = Math.round(value * 10) / 10;
    const sign = rounded > 0 ? "+" : "";
    return `${sign}${rounded.toFixed(1)}%`;
  }

  function buildPetStudyTooltipText(name, studyMetricLabel, studySitesTested) {
    const studyLabel = STUDY_METADATA.label || "AECCS 1000-site combined study snapshot";
    if (studyMetricLabel && studySitesTested) {
      return `${studyLabel}: ${name} averaged ${studyMetricLabel} tracker reduction across ${studySitesTested} tested sites. This is not a live measurement for the current page.`;
    }
    if (studyMetricLabel) {
      return `${studyLabel}: ${name} averaged ${studyMetricLabel} tracker reduction in the study. This is not a live measurement for the current page.`;
    }
    return `${studyLabel}: study-backed context only. This is not a live measurement for the current page.`;
  }

  // ── PET Recommendations (grounded in the combined 1000-site snapshot) ───
  // Relevance is still page-specific, but the static study copy must stay
  // aligned with the completed real_combined dataset.

  const PET_PROFILES = [
    {
      name: "Brave Shields",
      type: "browser",
      description: "Built-in browser protection with the strongest average tracker reduction in the combined study.",
      helpsWith: ["pre_consent_trackers", "advertising", "fingerprinting", "analytics"],
      studyTrackerReductionPct: 22.8,
      studyRank: 1,
      studyLabel: "+22.8% avg tracker reduction across 878 sites",
      recommendationWeight: 100,
      url: "https://brave.com",
    },
    {
      name: "Privacy Badger",
      type: "extension",
      description: "EFF's heuristic tracker blocker with strong results in the combined study.",
      helpsWith: ["pre_consent_trackers", "fingerprinting"],
      studyTrackerReductionPct: 21.0,
      studyRank: 2,
      studyLabel: "+21.0% avg tracker reduction across 881 sites",
      recommendationWeight: 90,
      url: "https://privacybadger.org",
    },
    {
      name: "uBlock Origin",
      type: "extension",
      description: "Open-source content blocker with consistently strong tracker reduction in the combined study.",
      helpsWith: ["pre_consent_trackers", "advertising", "analytics"],
      studyTrackerReductionPct: 22.4,
      studyRank: 3,
      studyLabel: "+22.4% avg tracker reduction across 878 sites",
      recommendationWeight: 80,
      url: "https://ublockorigin.com",
    },
    {
      name: "Firefox ETP Strict",
      type: "browser",
      description: "Firefox's stricter built-in protection with near-flat average tracker reduction in the combined study.",
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
      description: "Firefox's default tracker protection with modest results in the combined study.",
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
      description: "Automates reject flows when a site exposes a usable path, rather than blocking requests directly.",
      helpsWith: ["dark_patterns", "reject_effort"],
      studyTrackerReductionPct: -11.2,
      studyRank: 5,
      studyLabel: "-11.2% avg tracker reduction across 896 sites",
      recommendationWeight: 50,
      url: "https://consentomatic.au.dk",
    },
  ].map(profile => {
    const study = PET_STUDY_BY_NAME[profile.name] || {};
    const studyTrackerReductionPct = typeof study.trackerReductionPct === "number"
      ? study.trackerReductionPct
      : profile.studyTrackerReductionPct;
    const studySitesTested = Number.isFinite(study.sitesTested) ? study.sitesTested : null;
    const studyRank = Number.isFinite(study.studyRank) ? study.studyRank : profile.studyRank;
    const studyMetricLabel = formatStudyMetric(studyTrackerReductionPct);

    return {
      ...profile,
      type: study.type || profile.type,
      studyTrackerReductionPct,
      studySitesTested,
      studyRank,
      studyMetricLabel,
      studyLabel: study.studyLabel || profile.studyLabel || null,
      studyTooltipText: buildPetStudyTooltipText(profile.name, studyMetricLabel, studySitesTested),
      highlight: study.highlight || profile.highlight || null,
    };
  });

  const CMP_STUDY_RESULTS = SNAPSHOT.cmpStudyResults;

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

  // ── CMP compliance statistics (1000-site combined study snapshot) ───────

  const CMP_STATS = {
    "Didomi":       { avgScore: 36.2, sampleSize: 49,  rejectRate: 0.388, petScore: 24.9 },
    "OneTrust":     { avgScore: 35.5, sampleSize: 138, rejectRate: 0.406, petScore: 24.1 },
    "TrustArc":     { avgScore: 28.8, sampleSize: 121, rejectRate: 0.240, petScore: 16.3 },
    "Cookiebot":    { avgScore: 22.7, sampleSize: 91,  rejectRate: 0.132, petScore: 12.1 },
    "Quantcast":    { avgScore: 18.5, sampleSize: 28,  rejectRate: 0.143, petScore: 10.6 },
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
      summary: "AECCS combines live consent-banner findings with study-backed PET guidance instead of treating consent dark patterns and PET effectiveness as separate problems.",
    },
    {
      title: "Six PETs, One Combined Snapshot",
      summary: "The extension references one shared 1000-site combined study spanning Brave Shields, Firefox ETP Standard/Strict, uBlock Origin, Privacy Badger, and Consent-O-Matic.",
    },
    {
      title: "Government/Public-Sector Coverage",
      summary: "The underlying AECCS corpus includes government and public-sector domains, so the extension can ground alerts in a broader compliance context.",
    },
    {
      title: "Best CMP In Study: Didomi",
      summary: "Didomi ranked highest among named CMPs in the combined study by composite PET score, ahead of OneTrust and TrustArc.",
    },
    {
      title: "Reproducible Pipeline",
      summary: "The released pipeline runs crawl → classify → dark-pattern detect → score → CMP analysis → PET comparison → reporting.",
    },
  ];

  const CLAIM_GUARDRAILS = {
    positioning:
      "AECCS is a local, user-initiated, session-limited cookie-consent auditor for the current page, grounded in the completed 1000-site combined study.",
    supportedClaims: [
      "Combines dark-pattern findings with study-backed PET guidance",
      "Surfaces six end-user PETs in one shared combined-study snapshot",
      "Includes government/public-sector context and a March 6, 2026 post-DMA combined snapshot",
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

    const AECCS = {
      FALLBACK_TRACKERS,
      COOKIE_HEURISTICS,
      CMP_SIGNATURES,
      CONSENT_VOCABULARY,
      CONSENT_BUTTON_KEYWORDS,
      SETTINGS_KEYWORDS,
      DISMISS_BUTTON_KEYWORDS,
      NECESSARY_KEYWORDS,
      BANNER_TEXT_KEYWORDS,
      BANNER_TEXT_PHRASES,
    BANNER_ATTR_HINTS,
    COMPLIANCE_WEIGHTS,
    STATE_OUTCOME_WEIGHTS,
    GRADES,
      PRIVACY_LINK_KEYWORDS,
      PURPOSE_KEYWORDS,
      VENDOR_KEYWORDS,
      BANNER_SELECTORS,
      GUILT_TRIP_PHRASES,
      DOUBLE_NEGATIVE_PATTERNS,
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

    ROOT.AECCS = AECCS;
    ROOT._AECCSTrackerDataLoaded = true;
    ROOT[TRACKER_DATA_INIT_STAGE_KEY] = "ready";
    ROOT[TRACKER_DATA_INIT_ERROR_KEY] = null;
  } catch (err) {
    failInit(err);
    throw err;
  }
})();
