/*
 * Service Worker — background orchestrator for the AECCS extension.
 *
 * Flow:
 *   1. Popup sends {action: "analyze"} message
 *   2. Inject the runtime across frames and collect the best consent result
 *   3. Read the current cookie state for the active tab
 *   4. If a banner is visible, compute the baseline GDPR audit and arm a
 *      session-limited watcher for that banner flow
 *   5. If the banner is gone but the page still has meaningful consent state,
 *      compute a post-interaction/current-state audit instead
 *   6. Return the best available local analysis to the popup
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
  if (msg.action === "analyze") {
    handleAnalyze(msg.tabId)
      .then(result => sendResponse(result))
      .catch(err => sendResponse({ error: err.message }));

    return true;
  }

  if (msg.action === "clearInteractionSession") {
    handleClearInteractionSession(msg.tabId)
      .then(result => sendResponse(result))
      .catch(err => sendResponse({ ok: false, error: err.message }));

    return true;
  }

  if (msg.action === "consentInteractionObserved") {
    handleConsentInteractionObserved(msg, sender)
      .then(result => sendResponse(result))
      .catch(err => sendResponse({ error: err.message }));

    return true;
  }
});

const TIMEOUT_OVERRIDES = globalThis.__AECCS_TIMEOUTS || {};
const ANALYZE_TOTAL_TIMEOUT_MS = getPositiveTimeoutOverride(TIMEOUT_OVERRIDES.analyzeTotal, 60000);
const FRAME_STAGE_TIMEOUT_MS = getPositiveTimeoutOverride(TIMEOUT_OVERRIDES.frameStage, 3500);
const CONSENT_SCAN_TIMEOUT_MS = getPositiveTimeoutOverride(TIMEOUT_OVERRIDES.consentScan, 3500);
const COOKIE_READ_TIMEOUT_MS = getPositiveTimeoutOverride(TIMEOUT_OVERRIDES.cookieRead, 2500);
const SESSION_READ_TIMEOUT_MS = getPositiveTimeoutOverride(TIMEOUT_OVERRIDES.sessionRead, 1500);
const ANALYZE_TIMEOUT_MESSAGE =
  "Analysis timed out on this page before AECCS could finish scanning. Try reopening the popup.";
const INTERACTION_SESSION_TTL_MS = 10 * 60 * 1000;
const TAB_INTERACTION_SESSIONS = new Map();

if (browser?.tabs?.onRemoved?.addListener) {
  browser.tabs.onRemoved.addListener(tabId => {
    TAB_INTERACTION_SESSIONS.delete(tabId);
  });
}

function cloneForTransport(value) {
  if (value == null) return value;
  if (typeof structuredClone === "function") {
    try {
      return structuredClone(value);
    } catch (_) {
      // Fall through to JSON clone.
    }
  }
  return JSON.parse(JSON.stringify(value));
}

function getPositiveTimeoutOverride(value, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
}

function buildTimeoutError(message) {
  const err = new Error(message);
  err.name = "AECCSTimeoutError";
  err.aeccsTimeout = true;
  return err;
}

function isTimeoutError(err) {
  return Boolean(err?.aeccsTimeout);
}

function buildConsentScanBudgetMs(frameIds) {
  const uniqueFrameIds = Array.from(new Set(frameIds || []))
    .filter(frameId => frameId != null);
  if (uniqueFrameIds.length === 0) return CONSENT_SCAN_TIMEOUT_MS;

  const extraFrameBudget = Math.ceil(CONSENT_SCAN_TIMEOUT_MS * 0.35);
  const topFrameBudget = uniqueFrameIds.includes(0)
    ? Math.ceil(CONSENT_SCAN_TIMEOUT_MS * 1.5)
    : CONSENT_SCAN_TIMEOUT_MS;

  return Math.min(20000, topFrameBudget + Math.max(0, uniqueFrameIds.length - 1) * extraFrameBudget);
}

async function withTimeout(promiseOrFactory, timeoutMs, message) {
  if (!(timeoutMs > 0)) {
    return typeof promiseOrFactory === "function"
      ? promiseOrFactory()
      : promiseOrFactory;
  }

  let timeoutId = null;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(buildTimeoutError(message));
    }, timeoutMs);
  });

  try {
    const mainPromise = typeof promiseOrFactory === "function"
      ? Promise.resolve().then(() => promiseOrFactory())
      : Promise.resolve(promiseOrFactory);
    return await Promise.race([mainPromise, timeoutPromise]);
  } finally {
    if (timeoutId != null) {
      clearTimeout(timeoutId);
    }
  }
}

function createAnalyzeProgress() {
  return {
    hostname: null,
    url: null,
    isGovDomain: false,
    consentScan: null,
    consentScanCompleted: false,
    consentScanError: null,
    readyFrameIds: [],
    consentScanFrameId: null,
    successfulConsentScanFrameIds: [],
    timedOutConsentScanFrameIds: [],
    currentSite: null,
    interactionSession: null,
    baselineScore: null,
  };
}

function buildBestEffortAnalysisFromProgress(progress) {
  if (!progress?.hostname || !progress?.url) return null;

  if (progress.currentSite && progress.consentScan?.bannerFound && progress.baselineScore) {
    const baseline = buildInteractionBaseline(progress.currentSite, progress.baselineScore, progress.consentScan);
    const interactionAudit = buildArmedInteractionAudit(progress.interactionSession, baseline, progress.currentSite);
    return buildAnalysisResponse({
      analysisMode: "baseline_banner",
      hostname: progress.hostname,
      url: progress.url,
      currentSite: progress.currentSite,
      consentScan: progress.consentScan,
      score: progress.baselineScore,
      baselineScore: null,
      interactionAudit,
      isGovDomain: progress.isGovDomain,
    });
  }

  if (canBuildPostInteractionAnalysis(progress)) {
    const interactionAudit = buildPostInteractionAudit(progress.currentSite, progress.interactionSession);
    return buildAnalysisResponse({
      analysisMode: "post_interaction",
      hostname: progress.hostname,
      url: progress.url,
      currentSite: progress.currentSite,
      consentScan: progress.consentScan,
      score: interactionAudit.current.score,
      baselineScore: interactionAudit.baseline?.score || progress.baselineScore || null,
      interactionAudit,
      isGovDomain: progress.isGovDomain,
    });
  }

  return null;
}

function buildAnalyzeFailureResponse(progress, err) {
  const fallback = buildBestEffortAnalysisFromProgress(progress);
  if (fallback) return fallback;
  if (isTimeoutError(err)) {
    return { error: ANALYZE_TIMEOUT_MESSAGE };
  }
  return { error: extractScriptErrorMessage(err) };
}

function buildPageKey(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return `${url.origin}${url.pathname}`;
  } catch (_) {
    return String(rawUrl || "");
  }
}

function normalizeInteractionSessionForStorage(session, pageKey, frameId = null) {
  if (!session || typeof session !== "object") return null;

  const cloned = cloneForTransport(session) || {};
  const timestamp = new Date().toISOString();
  return {
    status: cloned.status || "armed",
    action: cloned.action || null,
    baseline: cloned.baseline || null,
    current: cloned.current || null,
    delta: cloned.delta || null,
    honesty: cloned.honesty || { verdict: "unknown", findings: [] },
    frameId: frameId != null ? frameId : (cloned.frameId ?? null),
    pageKey: pageKey || cloned.pageKey || null,
    pendingAction: cloned.pendingAction || null,
    armedAt: cloned.armedAt || null,
    observedAt: cloned.observedAt || cloned.action?.observedAt || null,
    updatedAt: cloned.updatedAt || timestamp,
    stopReason: cloned.stopReason || null,
    watching: Boolean(cloned.watching),
  };
}

function isInteractionSessionExpired(session) {
  const updatedAt = Date.parse(session?.updatedAt || 0) || 0;
  if (!updatedAt) return true;
  return (Date.now() - updatedAt) > INTERACTION_SESSION_TTL_MS;
}

function sessionMatchesPageKey(session, pageKey) {
  if (!session) return false;
  if (!pageKey) return true;
  return !session.pageKey || session.pageKey === pageKey;
}

function getStoredInteractionSession(tabId, pageKey) {
  const session = TAB_INTERACTION_SESSIONS.get(tabId);
  if (!session) return null;
  if (isInteractionSessionExpired(session) || !sessionMatchesPageKey(session, pageKey)) {
    TAB_INTERACTION_SESSIONS.delete(tabId);
    return null;
  }
  return cloneForTransport(session);
}

function persistInteractionSession(tabId, pageKey, session, frameId = null) {
  const normalized = normalizeInteractionSessionForStorage(session, pageKey, frameId);
  if (!normalized) return null;
  TAB_INTERACTION_SESSIONS.set(tabId, normalized);
  return cloneForTransport(normalized);
}

function clearStoredInteractionSession(tabId) {
  TAB_INTERACTION_SESSIONS.delete(tabId);
}

async function clearInteractionAuditSessionsInFrames(tabId, frameIds) {
  if (!Array.isArray(frameIds) || frameIds.length === 0) return [];

  return await executeScriptAcrossSpecificFrames(
    tabId,
    frameIds,
    {
      func: () => {
        if (!globalThis.AECCSConsentScanner?.clearInteractionAuditSession) return null;
        return globalThis.AECCSConsentScanner.clearInteractionAuditSession();
      },
    },
    {
      ignoreMissingFrames: true,
      timeoutMs: SESSION_READ_TIMEOUT_MS,
    }
  );
}

async function handleClearInteractionSession(tabId) {
  if (tabId == null) {
    return { ok: false, error: "No tab id provided" };
  }

  clearStoredInteractionSession(tabId);

  let runtime = null;
  try {
    runtime = await ensureScannerRuntimeAcrossFrames(tabId);
  } catch (_) {
    runtime = null;
  }

  if (!runtime?.error && Array.isArray(runtime?.frameIds) && runtime.frameIds.length > 0) {
    try {
      await clearInteractionAuditSessionsInFrames(tabId, runtime.frameIds);
    } catch (_) {
      // Best effort only. The durable background session is already cleared.
    }
  }

  return { ok: true };
}

async function handleAnalyze(tabId) {
  const progress = createAnalyzeProgress();

  try {
    return await withTimeout(async () => {
      let tab;
      if (tabId) {
        tab = await withTimeout(
          () => browser.tabs.get(tabId),
          SESSION_READ_TIMEOUT_MS,
          "Active tab lookup timed out"
        );
      } else {
        const tabs = await withTimeout(
          () => browser.tabs.query({ active: true, currentWindow: true }),
          SESSION_READ_TIMEOUT_MS,
          "Active tab lookup timed out"
        );
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
      const pageKey = buildPageKey(tab.url);
      const isGovDomain = AECCS.GOV_SUFFIXES.some(suf => hostname.endsWith(suf));
      progress.hostname = hostname;
      progress.url = tab.url;
      progress.isGovDomain = isGovDomain;

      let recoverableError = null;
      let runtime = { error: null, frameIds: [] };
      try {
        runtime = await ensureScannerRuntimeAcrossFrames(tab.id);
      } catch (err) {
        recoverableError = recoverableError || err;
        runtime = { error: extractScriptErrorMessage(err), frameIds: [] };
      }
      if (runtime.error) {
        recoverableError = recoverableError || new Error(runtime.error);
      }

      const readyFrameIds = Array.isArray(runtime.frameIds) ? runtime.frameIds : [];
      progress.readyFrameIds = readyFrameIds;

      let consentScanDetail = {
        error: runtime.error || null,
        frameId: null,
        scanResult: null,
        successfulFrameIds: [],
        timedOutFrameIds: [],
      };
      if (!runtime.error && readyFrameIds.length > 0) {
        try {
          consentScanDetail = await withTimeout(
            () => runConsentScanAcrossReadyFrames(tab.id, readyFrameIds),
            buildConsentScanBudgetMs(readyFrameIds),
            "Consent scan timed out"
          );
        } catch (err) {
          recoverableError = recoverableError || err;
          consentScanDetail = { error: extractScriptErrorMessage(err), frameId: null, scanResult: null };
        }
        if (consentScanDetail.error) {
          recoverableError = recoverableError || new Error(consentScanDetail.error);
        }
        if (
          Array.isArray(consentScanDetail.timedOutFrameIds) &&
          consentScanDetail.timedOutFrameIds.includes(0)
        ) {
          recoverableError = recoverableError || new Error(
            "Consent scan timed out in the top frame before AECCS could confirm the banner state."
          );
        }
      }

      progress.consentScan = consentScanDetail.scanResult || null;
      progress.consentScanCompleted = Boolean(consentScanDetail.scanResult && !consentScanDetail.error);
      progress.consentScanError = consentScanDetail.error || runtime.error || null;
      progress.consentScanFrameId = consentScanDetail.frameId ?? null;
      progress.successfulConsentScanFrameIds = Array.isArray(consentScanDetail.successfulFrameIds)
        ? consentScanDetail.successfulFrameIds
        : [];
      progress.timedOutConsentScanFrameIds = Array.isArray(consentScanDetail.timedOutFrameIds)
        ? consentScanDetail.timedOutFrameIds
        : [];

      let currentSite = null;
      try {
        currentSite = await withTimeout(
          () => readCurrentSiteSnapshot(tab.url, hostname),
          COOKIE_READ_TIMEOUT_MS,
          "Cookie read timed out"
        );
      } catch (err) {
        recoverableError = recoverableError || err;
      }
      if (currentSite?.error) {
        recoverableError = recoverableError || new Error(currentSite.error);
      }
      if (currentSite && !currentSite.error) {
        progress.currentSite = currentSite;
      }

      let interactionSession = null;
      try {
        interactionSession = await withTimeout(
          () => getBestInteractionAuditSession(tab.id, pageKey, readyFrameIds),
          SESSION_READ_TIMEOUT_MS,
          "Interaction session read timed out"
        );
      } catch (err) {
        recoverableError = recoverableError || err;
      }
      progress.interactionSession = interactionSession;

      if (progress.consentScan?.bannerFound && progress.currentSite) {
        const baselineScore = Scorer.computeComplianceScore(progress.currentSite.classifiedCookies, progress.consentScan);
        progress.baselineScore = baselineScore;
        const baseline = buildInteractionBaseline(progress.currentSite, baselineScore, progress.consentScan);
        let armedSession = null;
        try {
          armedSession = await withTimeout(
            () => armInteractionAuditSessionForFrame(
              tab.id,
              consentScanDetail.frameId,
              baseline,
              pageKey
            ),
            SESSION_READ_TIMEOUT_MS,
            "Interaction watcher setup timed out"
          );
        } catch (_) {
          armedSession = null;
        }
        if (armedSession) {
          persistInteractionSession(tab.id, pageKey, armedSession, consentScanDetail.frameId);
          progress.interactionSession = armedSession;
          try {
            await withTimeout(
              () => syncInteractionAuditSessionToTopFrame(tab.id, armedSession, readyFrameIds),
              SESSION_READ_TIMEOUT_MS,
              "Top-frame interaction sync timed out"
            );
          } catch (_) {
            // Best effort only.
          }
        }
        const interactionAudit = buildArmedInteractionAudit(progress.interactionSession, baseline, progress.currentSite);
        return buildAnalysisResponse({
          analysisMode: "baseline_banner",
          hostname,
          url: tab.url,
          currentSite: progress.currentSite,
          consentScan: progress.consentScan,
          score: baselineScore,
          baselineScore: null,
          interactionAudit,
          isGovDomain,
        });
      }

      if (canBuildPostInteractionAnalysis(progress)) {
        const interactionAudit = buildPostInteractionAudit(progress.currentSite, progress.interactionSession);
        return buildAnalysisResponse({
          analysisMode: "post_interaction",
          hostname,
          url: tab.url,
          currentSite: progress.currentSite,
          consentScan: progress.consentScan,
          score: interactionAudit.current.score,
          baselineScore: interactionAudit.baseline?.score || progress.baselineScore || null,
          interactionAudit,
          isGovDomain,
        });
      }

      if (recoverableError) {
        return buildAnalyzeFailureResponse(progress, recoverableError);
      }

      clearStoredInteractionSession(tab.id);
      return buildUnavailableAnalysis(tab.url, hostname, progress.consentScan, isGovDomain);
    }, ANALYZE_TOTAL_TIMEOUT_MS, ANALYZE_TIMEOUT_MESSAGE);
  } catch (err) {
    return buildAnalyzeFailureResponse(progress, err);
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function buildCookieKey(cookie) {
  const name = cookie?.name || "";
  const domain = cookie?.domain || "";
  const path = cookie?.path || "/";
  return `${name}|${domain}|${path}`;
}

function summarizeClassifiedCookies(classified) {
  const categoryCounts = {};
  const trackersByVendor = {};
  let trackerCount = 0;
  let thirdPartyCount = 0;

  for (const cookie of classified) {
    categoryCounts[cookie.category] = (categoryCounts[cookie.category] || 0) + 1;
    if (cookie.is_third_party) thirdPartyCount += 1;
    if (cookie.is_tracker) {
      trackerCount += 1;
      if (!trackersByVendor[cookie.vendor]) {
        trackersByVendor[cookie.vendor] = [];
      }
      trackersByVendor[cookie.vendor].push(cookie.name);
    }
  }

  return { categoryCounts, trackersByVendor, trackerCount, thirdPartyCount };
}

async function readCurrentSiteSnapshot(tabUrl, hostname) {
  let cookies = [];
  try {
    cookies = await browser.cookies.getAll({ url: tabUrl });
  } catch (err) {
    return { error: `Failed to read cookies: ${err.message}` };
  }

  const classified = Classifier.classifyAll(cookies, hostname);
  const summary = summarizeClassifiedCookies(classified);

  return {
    cookies,
    cookieKeys: cookies.map(buildCookieKey),
    classifiedCookies: classified,
    totalCookies: cookies.length,
    categoryCounts: summary.categoryCounts,
    trackersByVendor: summary.trackersByVendor,
    trackerCount: summary.trackerCount,
    thirdPartyCount: summary.thirdPartyCount,
  };
}

function buildInteractionBaseline(currentSite, baselineScore, consentScan) {
  return {
    totalCookies: currentSite.totalCookies,
    thirdPartyCount: currentSite.thirdPartyCount,
    trackerCount: currentSite.trackerCount,
    categoryCounts: currentSite.categoryCounts,
    cookieKeys: currentSite.cookieKeys,
    score: baselineScore,
    consentScan,
  };
}

function sanitizeInteractionBaseline(baseline) {
  if (!baseline) return null;
  return {
    totalCookies: baseline.totalCookies,
    thirdPartyCount: baseline.thirdPartyCount,
    trackerCount: baseline.trackerCount,
    score: baseline.score || null,
    consentScan: baseline.consentScan || null,
  };
}

function buildCurrentInteractionState(currentSite, interactionAudit) {
  return {
    totalCookies: currentSite.totalCookies,
    thirdPartyCount: currentSite.thirdPartyCount,
    trackerCount: currentSite.trackerCount,
    score: Scorer.computeStateOutcomeScore(currentSite, interactionAudit),
  };
}

function buildCookieDelta(currentSite, baseline) {
  if (!baseline || !Array.isArray(baseline.cookieKeys)) {
    return null;
  }

  const baselineKeys = new Set(baseline.cookieKeys);
  const newClassifiedCookies = currentSite.classifiedCookies
    .filter(cookie => !baselineKeys.has(buildCookieKey(cookie)))
    .map(cookie => ({
      name: cookie.name,
      domain: cookie.domain,
      category: cookie.category,
      isTracker: cookie.is_tracker,
      vendor: cookie.vendor,
    }));

  return {
    totalCookies: currentSite.totalCookies - Number(baseline.totalCookies || 0),
    thirdPartyCount: currentSite.thirdPartyCount - Number(baseline.thirdPartyCount || 0),
    trackerCount: currentSite.trackerCount - Number(baseline.trackerCount || 0),
    newCookies: newClassifiedCookies,
    newTrackers: newClassifiedCookies.filter(cookie => cookie.isTracker),
  };
}

function buildHonestyVerdict(currentSite, interactionAudit) {
  const actionType = interactionAudit?.action?.type || "unknown";
  if (actionType === "accept") {
    return {
      verdict: "not_applicable",
      findings: ["Honesty checks are only applied to reject or essential-only outcomes."],
    };
  }
  if (actionType === "unknown" || actionType === "dismiss" || !interactionAudit?.action) {
    return {
      verdict: "unknown",
      findings: ["No observed reject or essential-only action was available for honesty checking."],
    };
  }

  const categoryCounts = currentSite.categoryCounts || {};
  const trackerCount = Number(currentSite.trackerCount || 0);
  const delta = interactionAudit?.delta || null;
  const baseline = interactionAudit?.baseline || null;
  const nonEssentialCount = (
    Number(categoryCounts.Analytics || 0) +
    Number(categoryCounts.Advertising || 0) +
    Number(categoryCounts.Social || 0) +
    Number(categoryCounts.Fingerprinting || 0)
  );

  const findings = [];

  if (trackerCount > 0) {
    findings.push("Trackers remained after the claimed reject/essential action.");
  }

  if (delta?.newTrackers?.length) {
    findings.push("New trackers appeared after the claimed reject/essential action.");
  }

  if (
    baseline &&
    Number(currentSite.thirdPartyCount || 0) > Number(baseline.thirdPartyCount || 0)
  ) {
    findings.push("Third-party cookie load increased after the claimed reject/essential action.");
  }

  if (nonEssentialCount > 0 && trackerCount === 0) {
    findings.push("Non-essential cookies remained even though no trackers are currently classified.");
  }

  if (
    trackerCount === 0 &&
    nonEssentialCount === 0 &&
    (Number(categoryCounts.Functional || 0) > 0 || Number(categoryCounts.Unknown || 0) > 0)
  ) {
    findings.push("Only functional or unknown cookies remained after the claimed reject/essential action.");
    return { verdict: "mixed", findings };
  }

  if (findings.length > 0) {
    return { verdict: "dishonest", findings };
  }

  return {
    verdict: "honest",
    findings: ["No non-essential cookies or trackers remained after the claimed reject/essential action."],
  };
}

function buildArmedInteractionAudit(session, baseline, currentSite) {
  const current = buildCurrentInteractionState(currentSite, {
    action: session?.action || null,
    baseline,
    delta: null,
  });

  return {
    status: session?.status || "armed",
    action: session?.action || null,
    baseline,
    current,
    delta: null,
    honesty: session?.honesty || { verdict: "unknown", findings: [] },
  };
}

function buildPostInteractionAudit(currentSite, session) {
  const baseline = session?.baseline || null;
  const action = session?.action || {
    type: "unknown",
    text: null,
    observed: false,
    observedAt: null,
  };

  const draft = {
    status: session?.status || "unknown_current_state",
    action,
    baseline,
    current: null,
    delta: baseline ? buildCookieDelta(currentSite, baseline) : null,
    honesty: { verdict: "unknown", findings: [] },
  };

  draft.honesty = buildHonestyVerdict(currentSite, draft);
  draft.current = buildCurrentInteractionState(currentSite, draft);

  if (!session && action.type === "unknown") {
    draft.status = "unknown_current_state";
  } else if (draft.status === "observed" && session?.current) {
    draft.status = "completed";
  }

  return draft;
}

function isUnavailableConsentScanError(error) {
  const message = String(error || "").toLowerCase();
  if (!message) return false;
  return (
    message.includes("content script unavailable") ||
    message.includes("scanner runtime lost") ||
    message.includes("scanner unavailable") ||
    message.includes("runtime unavailable") ||
    message.includes("unavailable in all frames") ||
    message.includes("aeccsconsentscanner missing")
  );
}

function hasMeaningfulCurrentState(currentSite, consentScan, interactionSession) {
  return Boolean(
    Number(currentSite?.totalCookies || 0) > 0 ||
    Number(currentSite?.trackerCount || 0) > 0 ||
    Number(currentSite?.thirdPartyCount || 0) > 0 ||
    consentScan?.cmpDetected ||
    interactionSession
  );
}

function canBuildPostInteractionAnalysis(progress) {
  if (!progress?.currentSite) return false;
  if (!hasMeaningfulCurrentState(progress.currentSite, progress.consentScan, progress.interactionSession)) {
    return false;
  }
  if (progress.interactionSession) return true;
  if (!progress.consentScanCompleted) return false;
  if (progress.consentScan?.bannerFound !== false) return false;
  if (!didTopFrameConsentScanSucceed(progress)) return false;
  if (isUnavailableConsentScanError(progress.consentScanError)) return false;
  return true;
}

function buildUnavailableAnalysis(url, hostname, consentScan, isGovDomain) {
  return {
    analysisMode: "unavailable",
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
      reason: "no_meaningful_consent_state",
      title: "Evaluation unavailable on this page",
      message: "AECCS did not detect an active cookie banner or a meaningful post-interaction consent state, so this website was not evaluated.",
    },
    score: null,
    baselineScore: null,
    interactionAudit: null,
    isGovDomain,
    studyMetadata: AECCS.STUDY_METADATA,
    cmpStats: null,
    petRecommendations: [],
  };
}

function didTopFrameConsentScanSucceed(progress) {
  const readyFrameIds = Array.isArray(progress?.readyFrameIds) ? progress.readyFrameIds : [];
  if (!readyFrameIds.includes(0)) return false;

  const successfulFrameIds = Array.isArray(progress?.successfulConsentScanFrameIds)
    ? progress.successfulConsentScanFrameIds
    : [];
  return successfulFrameIds.includes(0);
}

function sanitizeInteractionAuditForResponse(interactionAudit) {
  if (!interactionAudit) return null;
  return {
    status: interactionAudit.status,
    action: interactionAudit.action || null,
    baseline: sanitizeInteractionBaseline(interactionAudit.baseline),
    current: interactionAudit.current || null,
    delta: interactionAudit.delta || null,
    honesty: interactionAudit.honesty || { verdict: "unknown", findings: [] },
  };
}

function buildAnalysisResponse({
  analysisMode,
  hostname,
  url,
  currentSite,
  consentScan,
  score,
  baselineScore = null,
  interactionAudit = null,
  isGovDomain,
}) {
  const cmpName = interactionAudit?.baseline?.consentScan?.cmpDetected || consentScan?.cmpDetected || null;
  const cmpStats = cmpName ? (AECCS.CMP_STATS[cmpName] || null) : null;
  const petConsentScan = interactionAudit?.baseline?.consentScan || consentScan;
  const petRecommendations = buildPetRecommendations(currentSite.classifiedCookies, petConsentScan, score);

  return {
    analysisMode,
    site: hostname,
    url,
    totalCookies: currentSite.totalCookies,
    thirdPartyCount: currentSite.thirdPartyCount,
    trackerCount: currentSite.trackerCount,
    categoryCounts: currentSite.categoryCounts,
    trackersByVendor: currentSite.trackersByVendor,
    classifiedCookies: currentSite.classifiedCookies,
    consentScan,
    evaluationDisabled: null,
    score,
    baselineScore,
    interactionAudit: sanitizeInteractionAuditForResponse(interactionAudit),
    isGovDomain,
    studyMetadata: AECCS.STUDY_METADATA,
    cmpStats,
    petRecommendations,
  };
}

async function ensureScannerRuntimeAcrossFrames(tabId, frameIds = null) {
  try {
    const sharedStage = await injectAndVerifyStage(
      tabId,
      frameIds,
      ["lib/browser-polyfill.js", "lib/study-snapshot.js", "lib/shared-config.js"],
      "shared config",
      probeSharedConfigInFrame,
      result => result.hasSharedConfig
    );
    if (sharedStage.error) return { error: sharedStage.error };

    const trackerStage = await injectAndVerifyStage(
      tabId,
      sharedStage.frameIds,
      ["lib/tracker-data.js"],
      "tracker runtime",
      probeTrackerRuntimeInFrame,
      result => result.hasAECCS
    );
    if (trackerStage.error) return { error: trackerStage.error };

    const scannerStage = await injectAndVerifyStage(
      tabId,
      trackerStage.frameIds,
      ["content/consent-scanner.js"],
      "scanner",
      probeScannerRuntimeInFrame,
      result => result.hasScanner
    );
    if (scannerStage.error) return { error: scannerStage.error };

    return {
      error: null,
      frameIds: scannerStage.frameIds,
      stageResults: {
        shared: sharedStage.results,
        tracker: trackerStage.results,
        scanner: scannerStage.results,
      },
    };
  } catch (err) {
    return { error: `Content script unavailable: ${err.message}` };
  }
}

async function runConsentScanAcrossReadyFrames(tabId, frameIds) {
  try {
    const orderedFrameIds = Array.from(new Set(frameIds || []))
      .filter(frameId => frameId != null)
      .sort((a, b) => {
        if (a === 0 && b !== 0) return -1;
        if (b === 0 && a !== 0) return 1;
        return a - b;
      });
    const frameResults = [];

    for (const frameId of orderedFrameIds) {
      try {
        const frameTimeoutMs = frameId === 0
          ? Math.ceil(CONSENT_SCAN_TIMEOUT_MS * 1.5)
          : CONSENT_SCAN_TIMEOUT_MS;
        const [frameResult] = await executeScriptAcrossSpecificFrames(
          tabId,
          [frameId],
          { func: runScannerInFrame },
          {
            ignoreMissingFrames: false,
            timeoutMs: frameTimeoutMs,
          }
        );
        if (frameResult) {
          frameResults.push(frameResult);
        }
      } catch (err) {
        if (isMissingFrameError(err)) {
          continue;
        }

        frameResults.push({
          frameId,
          result: {
            error: extractScriptErrorMessage(err),
            timedOut: isTimeoutError(err),
            scanResult: null,
            scanScore: -1,
          },
        });
      }
    }

    return selectBestConsentScanDetailed(frameResults);
  } catch (err) {
    return { error: `Content script unavailable: ${err.message}` };
  }
}

async function scanConsentAcrossFrames(tabId) {
  const runtime = await ensureScannerRuntimeAcrossFrames(tabId);
  if (runtime.error) return { error: runtime.error };
  const detail = await runConsentScanAcrossReadyFrames(tabId, runtime.frameIds);
  if (detail.error) return { error: detail.error };
  return detail.scanResult;
}

function buildFrameTarget(tabId, frameIds = null) {
  if (Array.isArray(frameIds) && frameIds.length > 0) {
    return { tabId, frameIds: Array.from(new Set(frameIds)).sort((a, b) => a - b) };
  }
  return { tabId, allFrames: true };
}

function normalizeStageResult(executionResult) {
  return {
    frameId: executionResult?.frameId ?? null,
    ...(executionResult?.result || {}),
  };
}

async function injectAndVerifyStage(tabId, frameIds, files, stageLabel, probeFunc, isReady) {
  let injectionError = null;
  try {
    await withTimeout(
      () => browser.scripting.executeScript({
        target: buildFrameTarget(tabId, frameIds),
        files,
      }),
      FRAME_STAGE_TIMEOUT_MS,
      `${stageLabel} injection timed out`
    );
  } catch (err) {
    injectionError = err && err.message ? err.message : String(err);
  }

  let probeResults = [];
  try {
    probeResults = (await withTimeout(
      () => browser.scripting.executeScript({
        target: buildFrameTarget(tabId, frameIds),
        func: probeFunc,
      }),
      FRAME_STAGE_TIMEOUT_MS,
      `${stageLabel} probe timed out`
    )).map(normalizeStageResult);
  } catch (err) {
    const probeError = err && err.message ? err.message : String(err);
    return { error: buildStageUnavailableError(stageLabel, [], injectionError || probeError) };
  }

  const readyFrameIds = probeResults
    .filter(result => {
      try {
        return isReady(result);
      } catch (_) {
        return false;
      }
    })
    .map(result => result.frameId)
    .filter(frameId => frameId != null);

  if (readyFrameIds.length === 0) {
    return {
      error: buildStageUnavailableError(stageLabel, probeResults, injectionError),
      results: probeResults,
      frameIds: [],
    };
  }

  return {
    error: null,
    results: probeResults,
    frameIds: Array.from(new Set(readyFrameIds)).sort((a, b) => a - b),
    injectionError,
  };
}

function buildStageUnavailableError(stageLabel, probeResults, injectionError = null) {
  const diagnostics = Array.from(
    new Set(
      (probeResults || [])
        .map(result => {
          const parts = [];
          if (result.error) parts.push(result.error);
          if (result.initStage) parts.push(`stage=${result.initStage}`);
          if (result.initError) parts.push(result.initError);
          if (result.hasAECCSSharedConfig === false) parts.push("AECCSSharedConfig missing");
          if (result.hasAECCS === false) parts.push("AECCS runtime missing");
          if (result.hasScanner === false) parts.push("AECCSConsentScanner missing");
          if (result.sharedConfigKeys === 0 && result.hasSharedConfig === false) {
            parts.push("shared config unavailable");
          }
          return parts.filter(Boolean).join("; ");
        })
        .filter(Boolean)
    )
  );

  if (injectionError && !diagnostics.includes(injectionError)) {
    diagnostics.unshift(injectionError);
  }

  if (diagnostics.length > 0) {
    return `${stageLabel} unavailable in all frames: ${diagnostics.join("; ")}`;
  }
  return `${stageLabel} unavailable in all frames`;
}

function probeSharedConfigInFrame() {
  const shared = globalThis.AECCSSharedConfig;
  return {
    hasSharedConfig: Boolean(shared),
    hasAECCSSharedConfig: Boolean(shared),
    sharedConfigKeys: shared && typeof shared === "object" ? Object.keys(shared).length : 0,
    error: shared ? null : "AECCSSharedConfig missing",
  };
}

function probeTrackerRuntimeInFrame() {
  return {
    hasSharedConfig: Boolean(globalThis.AECCSSharedConfig),
    hasAECCSSharedConfig: Boolean(globalThis.AECCSSharedConfig),
    hasAECCS: Boolean(globalThis.AECCS),
    initStage: globalThis._AECCSTrackerDataInitStage || null,
    initError: globalThis._AECCSTrackerDataInitError || null,
    error: globalThis.AECCS
      ? null
      : (globalThis._AECCSTrackerDataInitError || "AECCS runtime missing"),
  };
}

function probeScannerRuntimeInFrame() {
  return {
    hasAECCS: Boolean(globalThis.AECCS),
    hasScanner: Boolean(globalThis.AECCSConsentScanner),
    initStage: globalThis._AECCSConsentScannerInitStage || null,
    initError: globalThis._AECCSConsentScannerInitError || null,
    error: globalThis.AECCSConsentScanner
      ? null
      : (globalThis._AECCSConsentScannerInitError || "AECCSConsentScanner missing"),
  };
}

async function runScannerInFrame() {
  try {
    if (!globalThis.AECCSConsentScanner) {
      const diagnostics = [];
      if (globalThis._AECCSTrackerDataInitStage) {
        diagnostics.push(`tracker-stage=${globalThis._AECCSTrackerDataInitStage}`);
      }
      if (globalThis._AECCSTrackerDataInitError) {
        diagnostics.push(globalThis._AECCSTrackerDataInitError);
      }
      if (globalThis._AECCSConsentScannerInitStage) {
        diagnostics.push(`scanner-stage=${globalThis._AECCSConsentScannerInitStage}`);
      }
      if (globalThis._AECCSConsentScannerInitError) {
        diagnostics.push(globalThis._AECCSConsentScannerInitError);
      }
      throw new Error(
        diagnostics.length > 0
          ? `Consent scanner unavailable: ${diagnostics.join("; ")}`
          : "Consent scanner unavailable"
      );
    }

    const scanResult = await globalThis.AECCSConsentScanner.scanPageWithRetries();
    const scoreFn = globalThis.AECCSConsentScanner.scoreResult;
    const scanScore = typeof scoreFn === "function" ? scoreFn(scanResult) : -1;

    return {
      scanResult,
      scanScore,
      initStage: globalThis._AECCSConsentScannerInitStage || null,
      initError: globalThis._AECCSConsentScannerInitError || null,
    };
  } catch (err) {
    return {
      error: err && err.message ? err.message : String(err),
      scanResult: null,
      scanScore: -1,
      initStage: globalThis._AECCSConsentScannerInitStage || null,
      initError: globalThis._AECCSConsentScannerInitError || null,
    };
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
    timedOut: Boolean(payload.timedOut),
    initStage: payload.initStage || null,
    initError: payload.initError || null,
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

function selectBestConsentScanDetailed(executionResults) {
  const normalized = (executionResults || []).map(normalizeFrameScan);
  const successful = normalized.filter(item => item.scanResult && !item.error);
  const successfulFrameIds = successful
    .map(item => item.frameId)
    .filter(frameId => frameId != null);
  const timedOutFrameIds = normalized
    .filter(item => item.timedOut)
    .map(item => item.frameId)
    .filter(frameId => frameId != null);

  if (successful.length === 0) {
    const messages = Array.from(new Set(normalized.map(item => item.error).filter(Boolean)));
    const initDetails = Array.from(
      new Set(
        normalized
          .map(item => {
            if (!item.initStage && !item.initError) return null;
            return [item.initStage ? `stage=${item.initStage}` : null, item.initError].filter(Boolean).join("; ");
          })
          .filter(Boolean)
      )
    );
    for (const detail of initDetails) {
      if (!messages.includes(detail)) {
        messages.push(detail);
      }
    }
    if (timedOutFrameIds.length > 0) {
      messages.push(`timed out in frames ${timedOutFrameIds.join(", ")}`);
    }
    if (messages.length > 0) {
      return {
        error: `Content script unavailable in all frames: ${messages.join("; ")}`,
        successfulFrameIds,
        timedOutFrameIds,
      };
    }
    return { error: "Content script unavailable in all frames", successfulFrameIds, timedOutFrameIds };
  }

  let best = null;
  for (const candidate of successful) {
    if (isBetterFrameScan(candidate, best)) {
      best = candidate;
    }
  }

  return best
    ? {
        error: null,
        frameId: best.frameId,
        scanResult: best.scanResult,
        successfulFrameIds,
        timedOutFrameIds,
      }
    : { error: "Content script unavailable in all frames", successfulFrameIds, timedOutFrameIds };
}

function selectBestConsentScan(executionResults) {
  const detail = selectBestConsentScanDetailed(executionResults);
  if (detail.error) return { error: detail.error };
  return detail.scanResult;
}

function normalizeInteractionSessionResult(executionResult) {
  return {
    frameId: executionResult?.frameId ?? null,
    ...(executionResult?.result || {}),
  };
}

function extractScriptErrorMessage(err) {
  return err && err.message ? err.message : String(err);
}

function isMissingFrameError(err) {
  return extractScriptErrorMessage(err).toLowerCase().includes("no frame with id");
}

async function executeScriptAcrossSpecificFrames(
  tabId,
  frameIds,
  spec,
  { ignoreMissingFrames = false, timeoutMs = null } = {}
) {
  const uniqueFrameIds = Array.from(new Set(frameIds || []))
    .filter(frameId => frameId != null)
    .sort((a, b) => a - b);
  if (uniqueFrameIds.length === 0) return [];

  const results = [];
  for (const frameId of uniqueFrameIds) {
    try {
      const frameResults = await withTimeout(
        () => browser.scripting.executeScript({
          target: buildFrameTarget(tabId, [frameId]),
          ...spec,
        }),
        timeoutMs,
        `Frame ${frameId} script execution timed out`
      );
      results.push(...frameResults);
    } catch (err) {
      if (ignoreMissingFrames && (isMissingFrameError(err) || isTimeoutError(err))) {
        continue;
      }
      throw err;
    }
  }

  return results;
}

function interactionStatusRank(status) {
  switch (status) {
    case "completed": return 4;
    case "observed": return 3;
    case "armed": return 2;
    case "unknown_current_state": return 1;
    default: return 0;
  }
}

function pickBetterInteractionSession(candidate, current) {
  if (!candidate) return current;
  if (!current) return candidate;

  const candidateRank = interactionStatusRank(candidate.status);
  const currentRank = interactionStatusRank(current.status);
  if (candidateRank !== currentRank) {
    return candidateRank > currentRank ? candidate : current;
  }

  if (Boolean(candidate.action?.observed) !== Boolean(current.action?.observed)) {
    return candidate.action?.observed ? candidate : current;
  }

  const candidateUpdated = Date.parse(candidate.updatedAt || 0) || 0;
  const currentUpdated = Date.parse(current.updatedAt || 0) || 0;
  if (candidateUpdated !== currentUpdated) {
    return candidateUpdated > currentUpdated ? candidate : current;
  }

  const candidateFrameId = candidate.frameId == null ? Number.MAX_SAFE_INTEGER : candidate.frameId;
  const currentFrameId = current.frameId == null ? Number.MAX_SAFE_INTEGER : current.frameId;
  return candidateFrameId < currentFrameId ? candidate : current;
}

async function getInteractionAuditSessionsFromFrames(tabId, frameIds) {
  if (!Array.isArray(frameIds) || frameIds.length === 0) return [];

  const results = (await executeScriptAcrossSpecificFrames(
    tabId,
    frameIds,
    {
      func: () => {
        if (!globalThis.AECCSConsentScanner?.getInteractionAuditSession) return null;
        return globalThis.AECCSConsentScanner.getInteractionAuditSession();
      },
    },
    {
      ignoreMissingFrames: true,
      timeoutMs: SESSION_READ_TIMEOUT_MS,
    }
  )).map(normalizeInteractionSessionResult);

  return results.filter(result => result && result.status != null);
}

async function syncInteractionAuditSessionToFrame(tabId, frameId, interactionSession) {
  if (frameId == null || !interactionSession) return null;

  const [result] = await executeScriptAcrossSpecificFrames(
    tabId,
    [frameId],
    {
      func: payload => {
        if (!globalThis.AECCSConsentScanner?.syncInteractionAuditSession) return null;
        return globalThis.AECCSConsentScanner.syncInteractionAuditSession(payload);
      },
      args: [interactionSession],
    },
    {
      ignoreMissingFrames: true,
      timeoutMs: SESSION_READ_TIMEOUT_MS,
    }
  );
  if (!result) return null;

  return normalizeInteractionSessionResult(result);
}

async function syncInteractionAuditSessionToTopFrame(tabId, interactionSession, readyFrameIds = null) {
  if (!interactionSession) return null;
  if (interactionSession.frameId === 0 && interactionSession.watching) {
    return cloneForTransport(interactionSession);
  }

  let frameIds = Array.isArray(readyFrameIds) && readyFrameIds.includes(0) ? readyFrameIds : null;
  if (!frameIds) {
    const runtime = await ensureScannerRuntimeAcrossFrames(tabId, [0]);
    if (runtime.error || !runtime.frameIds.includes(0)) {
      return null;
    }
    frameIds = runtime.frameIds;
  }

  if (!frameIds.includes(0)) return null;

  try {
    return await syncInteractionAuditSessionToFrame(tabId, 0, interactionSession);
  } catch (_) {
    return null;
  }
}

async function getBestInteractionAuditSession(tabId, pageKey, frameIds) {
  const storedSession = getStoredInteractionSession(tabId, pageKey);
  let liveResults = [];
  try {
    liveResults = await getInteractionAuditSessionsFromFrames(tabId, frameIds) || [];
  } catch (_) {
    liveResults = [];
  }

  const candidates = [];
  if (storedSession) {
    candidates.push(normalizeInteractionSessionForStorage(storedSession, pageKey));
  }

  const topFrameSession = liveResults.find(result => result.frameId === 0) || null;
  if (topFrameSession && sessionMatchesPageKey(topFrameSession, pageKey)) {
    candidates.push(normalizeInteractionSessionForStorage(topFrameSession, pageKey));
  }

  for (const result of liveResults) {
    if (!result || result.status == null) continue;
    if (!sessionMatchesPageKey(result, pageKey)) continue;
    candidates.push(normalizeInteractionSessionForStorage(result, pageKey));
  }

  let best = null;
  for (const candidate of candidates) {
    best = pickBetterInteractionSession(candidate, best);
  }

  if (!best) return null;

  persistInteractionSession(tabId, pageKey, best, best.frameId);
  if (Array.isArray(frameIds) && frameIds.length > 0) {
    await syncInteractionAuditSessionToTopFrame(tabId, best, frameIds);
  }
  return best;
}

async function armInteractionAuditSessionForFrame(tabId, frameId, baseline, pageKey = null) {
  if (frameId == null) return null;

  const [result] = await executeScriptAcrossSpecificFrames(
    tabId,
    [frameId],
    {
      func: (payload, currentFrameId, currentPageKey) => {
        if (!globalThis.AECCSConsentScanner?.armInteractionAuditSession) return null;
        return globalThis.AECCSConsentScanner.armInteractionAuditSession({
          baseline: payload,
          frameId: currentFrameId,
          pageKey: currentPageKey,
        });
      },
      args: [baseline, frameId, pageKey],
    },
    {
      ignoreMissingFrames: true,
      timeoutMs: SESSION_READ_TIMEOUT_MS,
    }
  );
  if (!result) return null;

  return normalizeInteractionSessionResult(result);
}

async function storeInteractionOutcomeForFrame(tabId, frameId, interactionAudit) {
  if (frameId == null) return null;

  const [result] = await executeScriptAcrossSpecificFrames(
    tabId,
    [frameId],
    {
      func: payload => {
        if (!globalThis.AECCSConsentScanner?.storeInteractionOutcome) return null;
        return globalThis.AECCSConsentScanner.storeInteractionOutcome(payload);
      },
      args: [interactionAudit],
    },
    {
      ignoreMissingFrames: true,
      timeoutMs: SESSION_READ_TIMEOUT_MS,
    }
  );
  if (!result) return null;

  return normalizeInteractionSessionResult(result);
}

function selectBestCapturedInteractionAudit(captures) {
  let best = null;

  for (const capture of captures) {
    if (!capture) continue;
    if (!best) {
      best = capture;
      continue;
    }

    const candidateRichness = (
      Number(capture.current?.trackerCount || 0) * 100 +
      Number(capture.current?.thirdPartyCount || 0) * 10 +
      Number(capture.current?.totalCookies || 0)
    );
    const currentRichness = (
      Number(best.current?.trackerCount || 0) * 100 +
      Number(best.current?.thirdPartyCount || 0) * 10 +
      Number(best.current?.totalCookies || 0)
    );

    if (candidateRichness !== currentRichness) {
      if (candidateRichness > currentRichness) {
        best = capture;
      }
      continue;
    }

    const candidateUpdated = Date.parse(capture.current?.capturedAt || 0) || 0;
    const currentUpdated = Date.parse(best.current?.capturedAt || 0) || 0;
    if (candidateUpdated >= currentUpdated) {
      best = capture;
    }
  }

  return best;
}

async function capturePostInteractionAudit(tabId, tabUrl, hostname, session) {
  const runtime = await ensureScannerRuntimeAcrossFrames(tabId);
  if (runtime.error) return null;

  const currentSite = await readCurrentSiteSnapshot(tabUrl, hostname);
  if (currentSite.error) return null;

  const interactionAudit = buildPostInteractionAudit(currentSite, session);
  interactionAudit.current.capturedAt = new Date().toISOString();
  return interactionAudit;
}

async function handleConsentInteractionObserved(msg, sender) {
  const tabId = sender?.tab?.id;
  const tabUrl = sender?.tab?.url;
  const hostname = tabUrl ? new URL(tabUrl).hostname : null;
  const pageKey = msg?.session?.pageKey || buildPageKey(tabUrl);
  const frameId = sender?.frameId ?? msg?.session?.frameId ?? null;
  const session = msg?.session || null;

  if (!tabId || !tabUrl || !hostname || !session) {
    return { ok: false };
  }

  const observedSession = persistInteractionSession(tabId, pageKey, session, frameId);

  const runtime = await ensureScannerRuntimeAcrossFrames(tabId);
  if (!runtime.error) {
    await syncInteractionAuditSessionToTopFrame(tabId, observedSession, runtime.frameIds);
  }

  const captures = [];
  let previousDelay = 0;
  for (const delay of [500, 1500, 3000]) {
    await sleep(Math.max(0, delay - previousDelay));
    previousDelay = delay;
    const capture = await capturePostInteractionAudit(tabId, tabUrl, hostname, session);
    if (capture) {
      captures.push(capture);
    }
  }

  const best = selectBestCapturedInteractionAudit(captures);
  if (best) {
    best.status = "completed";
    best.frameId = frameId;
    best.pageKey = pageKey;
    best.updatedAt = new Date().toISOString();
    const stored = persistInteractionSession(tabId, pageKey, best, frameId);
    if (!runtime.error) {
      await syncInteractionAuditSessionToTopFrame(tabId, stored, runtime.frameIds);
    }
    try {
      await storeInteractionOutcomeForFrame(tabId, frameId, stored);
    } catch (_) {
      // The original banner frame may be gone; the top-frame mirror and
      // background session remain the durable anchors.
    }
  }

  return { ok: true };
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
