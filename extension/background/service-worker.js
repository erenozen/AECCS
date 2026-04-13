/*
 * Service Worker — background orchestrator for the AECCS extension.
 *
 * Flow:
 *   1. Popup sends {action: "analyze"} message
 *   2. Read cookies for the active tab via browser.cookies API
 *   3. Classify cookies using Classifier
 *   4. Ask content script to scan the DOM for consent banners / dark patterns
 *   5. Compute GDPR compliance score using Scorer
 *   6. Return full analysis to popup
 */

importScripts(
  "../lib/browser-polyfill.js",
  "../lib/tracker-data.js",
  "../lib/domain-utils.js",
  "../lib/classifier.js",
  "../lib/scorer.js"
);

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

  // 2. Read cookies
  let cookies = [];
  try {
    cookies = await browser.cookies.getAll({ url: tab.url });
  } catch (err) {
    return { error: `Failed to read cookies: ${err.message}` };
  }

  // 3. Classify cookies
  const classified = Classifier.classifyAll(cookies, hostname);

  // 4. Ask content script to scan the DOM
  let consentScan = null;
  try {
    consentScan = await browser.tabs.sendMessage(tab.id, { action: "scanConsent" });
  } catch (_) {
    // Content script might not be injected yet — try programmatic injection
    try {
      await browser.scripting.executeScript({
        target: { tabId: tab.id },
        files: [
          "lib/browser-polyfill.js",
          "lib/tracker-data.js",
          "content/consent-scanner.js",
        ],
      });
      consentScan = await browser.tabs.sendMessage(tab.id, { action: "scanConsent" });
    } catch (err2) {
      consentScan = { error: `Content script unavailable: ${err2.message}` };
    }
  }

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

  // 7. Government domain detection
  const isGovDomain = AECCS.GOV_SUFFIXES.some(suf => hostname.endsWith(suf));

  // 8. CMP statistics from our study
  const cmpName = consentScan?.cmpDetected || null;
  const cmpStats = cmpName ? (AECCS.CMP_STATS[cmpName] || null) : null;

  // 9. PET recommendations — pick the most relevant PETs based on findings
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
    score,
    isGovDomain,
    cmpStats,
    petRecommendations,
  };
}

/**
 * Build PET recommendations based on the site's specific compliance issues.
 * This is the novel intersection from our study: which PETs compensate for
 * which compliance failures and dark patterns.
 */
function buildPetRecommendations(classified, consentScan, score) {
  const issues = new Set();
  const trackerCategories = new Set();

  // Identify the site's specific problems
  for (const c of classified) {
    if (c.is_tracker) {
      issues.add("pre_consent_trackers");
      trackerCategories.add(c.category.toLowerCase());
    }
  }

  if (consentScan && !consentScan.error) {
    if (!consentScan.hasRejectButton) issues.add("reject_effort");
    if (consentScan.darkPatterns?.count > 0) {
      issues.add("dark_patterns");
      issues.add("reject_effort");
    }
  }

  if (issues.size === 0) return [];

  // Score each PET by how many of the site's issues it addresses
  return AECCS.PET_PROFILES
    .map(pet => {
      let relevance = 0;
      for (const help of pet.helpsWith) {
        if (issues.has(help)) relevance += 2;
        if (trackerCategories.has(help)) relevance += 1;
      }
      return { ...pet, relevance };
    })
    .filter(p => p.relevance > 0)
    .sort((a, b) => b.relevance - a.relevance || b.effectiveness - a.effectiveness)
    .slice(0, 3); // top 3 recommendations
}
