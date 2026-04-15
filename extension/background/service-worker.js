/*
 * Service Worker — background orchestrator for the AECCS extension.
 *
 * Flow:
 *   1. Popup sends {action: "analyze"} message
 *   2. Inject the scanner across frames and collect the best consent result
 *   3. If no active banner is found, return a non-applicable state
 *   4. Read cookies for the active tab via browser.cookies API
 *   5. Classify cookies using Classifier
 *   6. Compute GDPR compliance score using Scorer
 *   7. Return full analysis to popup
 */

if (typeof importScripts === "function") {
  importScripts(
    "../lib/browser-polyfill.js",
    "../lib/study-snapshot.js",
    "../lib/shared-config.js",
    "../lib/tracker-data.js",
    "../lib/tracker-index.js",
    "../lib/domain-utils.js",
    "../lib/classifier.js",
    "../lib/scorer.js"
  );
}

browser.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action !== "analyze") return;

  handleAnalyze(msg.tabId)
    .then(result => sendResponse(result))
    .catch(err => sendResponse({ error: err.message }));

  return true; // keep channel open for async response
});

async function handleAnalyze(tabId) {
  // 1. Get the active tab
  let tab;
  if (tabId) {
    tab = await browser.tabs.get(tabId);
  } else {
    const tabs = await browser.tabs.query({ active: true, currentWindow: true });
    tab = tabs[0];
  }

  if (!tab || !tab.url) {
    return { error: "No active tab found" };
  }

  const url = new URL(tab.url);

  // Only analyze http/https pages
  if (!url.protocol.startsWith("http")) {
    return { error: "Cannot analyze this page (not HTTP/HTTPS)" };
  }

  const hostname = url.hostname;

  const isGovDomain = AECCS.GOV_SUFFIXES.some(suf => hostname.endsWith(suf));

  // 2. Inject the scanner across frames and pick the best consent result.
  //    We inject programmatically on-demand rather than via manifest
  //    content_scripts — this avoids running code on every page load and
  //    improves the extension's privacy posture for store review.
  const consentScan = await scanConsentAcrossFrames(tab.id);

  if (consentScan?.error) {
    return { error: consentScan.error };
  }

  if (!consentScan?.bannerFound) {
    return buildDisabledAnalysis(tab.url, hostname, consentScan, isGovDomain);
  }

  // 3. Read cookies
  let cookies = [];
  try {
    cookies = await browser.cookies.getAll({ url: tab.url });
  } catch (err) {
    return { error: `Failed to read cookies: ${err.message}` };
  }

  // 4. Classify cookies
  const classified = Classifier.classifyAll(cookies, hostname);

  // 5. Compute compliance score
  const score = Scorer.computeComplianceScore(classified, consentScan);

  // 6. Build summary
  const categoryCounts = {};
  const trackersByVendor = {};
  let trackerCount = 0;
  let thirdPartyCount = 0;

  for (const c of classified) {
    categoryCounts[c.category] = (categoryCounts[c.category] || 0) + 1;
    if (c.is_third_party) thirdPartyCount++;
    if (c.is_tracker) {
      trackerCount++;
      if (!trackersByVendor[c.vendor]) {
        trackersByVendor[c.vendor] = [];
      }
      trackersByVendor[c.vendor].push(c.name);
    }
  }

  // 6. CMP statistics from our study
  const cmpName = consentScan?.cmpDetected || null;
  const cmpStats = cmpName ? (AECCS.CMP_STATS[cmpName] || null) : null;

  // 7. PET recommendations — pick the most relevant PETs based on findings
  const petRecommendations = buildPetRecommendations(classified, consentScan, score);

  return {
    site: hostname,
    url: tab.url,
    totalCookies: cookies.length,
    thirdPartyCount,
    trackerCount,
    categoryCounts,
    trackersByVendor,
    classifiedCookies: classified,
    consentScan,
    evaluationDisabled: null,
    score,
    isGovDomain,
    studyMetadata: AECCS.STUDY_METADATA,
    cmpStats,
    petRecommendations,
  };
}

function buildDisabledAnalysis(url, hostname, consentScan, isGovDomain) {
  return {
    site: hostname,
    url,
    totalCookies: null,
    thirdPartyCount: null,
    trackerCount: null,
    categoryCounts: {},
    trackersByVendor: {},
    classifiedCookies: [],
    consentScan,
    evaluationDisabled: {
      active: true,
      reason: "no_active_cookie_banner",
      title: "Evaluation unavailable on this page",
      message: "AECCS works with active visible cookie banners. No cookie banner was detected, so this website was not evaluated.",
    },
    score: null,
    isGovDomain,
    studyMetadata: AECCS.STUDY_METADATA,
    cmpStats: null,
    petRecommendations: [],
  };
}

async function scanConsentAcrossFrames(tabId) {
  try {
    // Inject scripts into every accessible frame. The consent scanner IIFE has
    // a guard that skips re-initialisation if it was already loaded, so this
    // remains idempotent even when the popup is reopened.
    await browser.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: [
        "lib/browser-polyfill.js",
        "lib/study-snapshot.js",
        "lib/shared-config.js",
        "lib/tracker-data.js",
        "content/consent-scanner.js",
      ],
    });

    const frameResults = await browser.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: async () => {
        try {
          if (!globalThis.AECCSConsentScanner) {
            throw new Error("Consent scanner unavailable");
          }

          const scanResult = await globalThis.AECCSConsentScanner.scanPageWithRetries();
          const scoreFn = globalThis.AECCSConsentScanner.scoreResult;
          const scanScore = typeof scoreFn === "function" ? scoreFn(scanResult) : -1;

          return { scanResult, scanScore };
        } catch (err) {
          return {
            error: err && err.message ? err.message : String(err),
            scanResult: null,
            scanScore: -1,
          };
        }
      },
    });

    return selectBestConsentScan(frameResults);
  } catch (err) {
    return { error: `Content script unavailable: ${err.message}` };
  }
}

function normalizeFrameScan(executionResult) {
  const payload = executionResult?.result || {};
  const scanScore = Number.isFinite(payload.scanScore) ? payload.scanScore : -1;
  const scanResult = payload.scanResult || null;
  const scanError = payload.error || scanResult?.error || null;

  return {
    frameId: executionResult?.frameId ?? null,
    scanResult,
    scanScore,
    error: scanError,
  };
}

function hasActionableControls(scanResult) {
  return Boolean(
    scanResult && (scanResult.hasAcceptButton || scanResult.hasRejectButton || scanResult.hasSettingsButton)
  );
}

function isBetterFrameScan(candidate, current) {
  if (!current) return true;

  if (candidate.scanScore !== current.scanScore) {
    return candidate.scanScore > current.scanScore;
  }

  const candidateDirectReject = Boolean(candidate.scanResult?.hasRejectButton);
  const currentDirectReject = Boolean(current.scanResult?.hasRejectButton);
  if (candidateDirectReject !== currentDirectReject) {
    return candidateDirectReject;
  }

  const candidateActionable = hasActionableControls(candidate.scanResult);
  const currentActionable = hasActionableControls(current.scanResult);
  if (candidateActionable !== currentActionable) {
    return candidateActionable;
  }

  const candidateFrameId = candidate.frameId == null ? Number.MAX_SAFE_INTEGER : candidate.frameId;
  const currentFrameId = current.frameId == null ? Number.MAX_SAFE_INTEGER : current.frameId;
  return candidateFrameId < currentFrameId;
}

function selectBestConsentScan(executionResults) {
  const normalized = (executionResults || []).map(normalizeFrameScan);
  const successful = normalized.filter(item => item.scanResult && !item.error);

  if (successful.length === 0) {
    const messages = Array.from(new Set(normalized.map(item => item.error).filter(Boolean)));
    if (messages.length > 0) {
      return { error: `Content script unavailable in all frames: ${messages.join("; ")}` };
    }
    return { error: "Content script unavailable in all frames" };
  }

  let best = null;
  for (const candidate of successful) {
    if (isBetterFrameScan(candidate, best)) {
      best = candidate;
    }
  }

  return best ? best.scanResult : { error: "Content script unavailable in all frames" };
}

/**
 * Build PET recommendations based on the site's specific compliance issues.
 * This is the novel intersection from our study: which PETs compensate for
 * which compliance failures and dark patterns.
 */
function buildPetRecommendations(classified, consentScan, score) {
  const issues = new Set();
  const trackerCategories = new Set();
  const issueLabels = [];

  // Identify the site's specific problems
  for (const c of classified) {
    if (c.is_tracker) {
      issues.add("pre_consent_trackers");
      trackerCategories.add(c.category.toLowerCase());
    }
  }

  if (consentScan && !consentScan.error) {
    if (!consentScan.hasRejectButton || consentScan.rejectClicksRequired > consentScan.acceptClicksRequired) {
      issues.add("reject_effort");
    }
    if (consentScan.darkPatterns?.count > 0) {
      issues.add("dark_patterns");
      issues.add("reject_effort");
    }
  }

  if (issues.size === 0) return [];

  if (issues.has("pre_consent_trackers")) issueLabels.push("pre-consent trackers");
  if (issues.has("dark_patterns")) issueLabels.push("dark patterns");
  if (issues.has("reject_effort")) issueLabels.push("unequal reject path");

  // Score each PET by how many of the site's issues it addresses
  return AECCS.PET_PROFILES
    .map(pet => {
      let relevance = 0;
      const matchedReasons = [];
      for (const help of pet.helpsWith) {
        if (issues.has(help)) {
          relevance += 2;
          matchedReasons.push(labelForIssue(help));
        }
        if (trackerCategories.has(help)) {
          relevance += 1;
          matchedReasons.push(labelForIssue(help));
        }
      }
      return {
        ...pet,
        relevance,
        matchedReasons: Array.from(new Set(matchedReasons)).slice(0, 3),
        whyRecommended: buildWhyRecommended(Array.from(new Set(matchedReasons)).slice(0, 3), issueLabels),
      };
    })
    .filter(p => p.relevance > 0)
    .sort((a, b) =>
      b.relevance - a.relevance ||
      (b.recommendationWeight || 0) - (a.recommendationWeight || 0) ||
      (b.studyTrackerReductionPct || 0) - (a.studyTrackerReductionPct || 0)
    )
    .slice(0, 3); // top 3 recommendations
}

function labelForIssue(issue) {
  const labels = {
    pre_consent_trackers: "pre-consent trackers",
    dark_patterns: "dark patterns",
    reject_effort: "reject friction",
    analytics: "analytics trackers",
    advertising: "advertising trackers",
    social: "social trackers",
    fingerprinting: "fingerprinting signals",
  };
  return labels[issue] || issue.replace(/_/g, " ");
}

function buildWhyRecommended(matchedReasons, fallbackReasons) {
  const reasons = matchedReasons.length > 0 ? matchedReasons : fallbackReasons;
  if (!reasons || reasons.length === 0) return null;
  if (reasons.length === 1) return `Helps with ${reasons[0]}.`;
  if (reasons.length === 2) return `Helps with ${reasons[0]} and ${reasons[1]}.`;
  return `Helps with ${reasons[0]}, ${reasons[1]}, and ${reasons[2]}.`;
}
