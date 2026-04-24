/*
 * Popup script — requests analysis from the service worker and renders all
 * results including the AECCS-unique features: dark pattern detail cards with
 * GDPR article references, accept/reject UX comparison, PET recommendations,
 * CMP statistics, and government domain alerts.
 */

(() => {
  "use strict";

  const POPUP_ANALYZE_TIMEOUT_MS = getPositiveTimeoutOverride(
    globalThis.__AECCS_POPUP_ANALYZE_TIMEOUT_MS,
    62000
  );
  const POPUP_ANALYZE_TIMEOUT_MESSAGE =
    "AECCS did not receive an analysis response in time on this page. Try reopening the popup.";
  const POPUP_ACTION_TIMEOUT_MS = 8000;
  const PROTECTION_PROFILE_STORAGE_KEY = "aeccsUserProtectionProfile";
  const BROWSER_PROTECTION_LABELS = {
    none: "No protections declared",
    firefox_etp_standard: "Firefox ETP Standard",
    firefox_etp_strict: "Firefox ETP Strict",
    brave_shields: "Brave Shields",
  };
  const EXTRA_TOOL_LABELS = {
    ublock_origin: "uBlock Origin",
    privacy_badger: "Privacy Badger",
    consent_o_matic: "Consent-O-Matic",
  };

  const GRADE_COLORS = {
    A: "#22c55e",
    B: "#84cc16",
    C: "#eab308",
    D: "#f97316",
    F: "#ef4444",
  };

  const CATEGORY_COLORS = {
    Analytics:      "#3b82f6",
    Advertising:    "#ef4444",
    Social:         "#06b6d4",
    Functional:     "#6b7280",
    Fingerprinting: "#f97316",
    Unknown:        "#374151",
  };

  const CRITERIA_LABELS = {
    no_pre_consent_trackers:    "No Pre-Consent Trackers",
    reject_option_available:    "Reject Option Available",
    equal_accept_reject_effort: "Equal Accept/Reject Effort",
    no_dark_patterns:           "No Dark Patterns",
    post_reject_compliance:     "Post-Reject Compliance",
    transparent_information:    "Transparent Information",
    low_tracker_load:           "Low Tracker Load",
    low_third_party_load:       "Low Third-Party Load",
    low_total_cookie_load:      "Low Total Cookie Load",
    claimed_action_honesty:     "Claimed Action Honesty",
  };

  let currentAnalysis = null;
  let currentTabId = null;
  let currentProtectionProfile = defaultProtectionProfile();
  let renderedInsightsKey = null;
  let activePetTooltipTrigger = null;

  // ── DOM refs ──────────────────────────────────────────────────────────────

  const $ = id => document.getElementById(id);

  const els = {
    loading:           $("loading"),
    errorState:        $("errorState"),
    errorMsg:          $("errorMsg"),
    disabledState:     $("disabledState"),
    disabledTitle:     $("disabledTitle"),
    disabledMsg:       $("disabledMsg"),
    results:           $("results"),
    siteDomain:        $("siteDomain"),
    browsingSetupSection: $("browsingSetupSection"),
    browsingSetupSummary: $("browsingSetupSummary"),
    browsingSetupStatus: $("browsingSetupStatus"),
    browserProtectionSelect: $("browserProtectionSelect"),
    protectionExplainer: $("protectionExplainer"),
    protectionExplainerContent: $("protectionExplainerContent"),
    govAlert:          $("govAlert"),
    govNote:           $("govNote"),
    gradeBadge:        $("gradeBadge"),
    gradeLetter:       $("gradeLetter"),
    scoreValue:        $("scoreValue"),
    scoreLabel:        $("scoreLabel"),
    scoreContext:      $("scoreContext"),
    analysisCompleteness: $("analysisCompleteness"),
    protectionCaveat:  $("protectionCaveat"),
    protectionCaveatText: $("protectionCaveatText"),
    baselineScoreSection: $("baselineScoreSection"),
    baselineGradeBadge: $("baselineGradeBadge"),
    baselineGradeLetter: $("baselineGradeLetter"),
    baselineScoreValue: $("baselineScoreValue"),
    baselineScoreLabel: $("baselineScoreLabel"),
    cookieBar:         $("cookieBar"),
    cookieCounts:      $("cookieCounts"),
    cookieMeta:        $("cookieMeta"),
    trackerSection:    $("trackerSection"),
    trackerList:       $("trackerList"),
    consentInfo:       $("consentInfo"),
    cmpInfo:           $("cmpInfo"),
    interactionSection: $("interactionSection"),
    compareFlow:       $("compareFlow"),
    interactionInfo:   $("interactionInfo"),
    recheckButton:     $("recheckButton"),
    startOverButton:   $("startOverButton"),
    buttonCompSection: $("buttonCompSection"),
    buttonComparison:  $("buttonComparison"),
    darkPatternSection: $("darkPatternSection"),
    darkPatternDetails: $("darkPatternDetails"),
    criteriaBody:      $("criteriaBody"),
    petSection:        $("petSection"),
    petSubtitle:       $("petSubtitle"),
    petList:           $("petList"),
    studyInsightsSection: $("studyInsightsSection"),
    studyInsightsContent: $("studyInsightsContent"),
    footerNote:        $("footerNote"),
  };
  els.extraToolInputs = Array.from(document.querySelectorAll('input[name="extraTool"]'));

  function getPositiveTimeoutOverride(value, fallback) {
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
  }

  function defaultProtectionProfile() {
    return {
      browserProtection: "none",
      extraTools: [],
      updatedAt: null,
    };
  }

  function normalizeProtectionProfile(profile) {
    const normalized = defaultProtectionProfile();
    const browserProtection = String(profile?.browserProtection || "none");
    normalized.browserProtection = Object.prototype.hasOwnProperty.call(BROWSER_PROTECTION_LABELS, browserProtection)
      ? browserProtection
      : "none";
    normalized.extraTools = Array.from(new Set(
      Array.isArray(profile?.extraTools) ? profile.extraTools : []
    ))
      .map(tool => String(tool || ""))
      .filter(tool => Object.prototype.hasOwnProperty.call(EXTRA_TOOL_LABELS, tool))
      .sort((a, b) => toolOrder(a) - toolOrder(b));
    normalized.updatedAt = profile?.updatedAt || null;
    return normalized;
  }

  function toolOrder(tool) {
    switch (tool) {
      case "ublock_origin": return 1;
      case "privacy_badger": return 2;
      case "consent_o_matic": return 3;
      default: return 99;
    }
  }

  function hasDeclaredProtections(profile) {
    const normalized = normalizeProtectionProfile(profile);
    return normalized.browserProtection !== "none" || normalized.extraTools.length > 0;
  }

  function summarizeProtectionProfile(profile) {
    const normalized = normalizeProtectionProfile(profile);
    const parts = [];
    if (normalized.browserProtection !== "none") {
      parts.push(BROWSER_PROTECTION_LABELS[normalized.browserProtection]);
    }
    for (const tool of normalized.extraTools) {
      parts.push(EXTRA_TOOL_LABELS[tool]);
    }
    return parts.length > 0 ? parts.join(" + ") : "No protections declared";
  }

  function isConsentOMaticDeclared(profile) {
    return normalizeProtectionProfile(profile).extraTools.includes("consent_o_matic");
  }

  async function loadProtectionProfile() {
    try {
      if (!browser?.storage?.local?.get) {
        return defaultProtectionProfile();
      }
      const payload = await browser.storage.local.get(PROTECTION_PROFILE_STORAGE_KEY);
      return normalizeProtectionProfile(payload?.[PROTECTION_PROFILE_STORAGE_KEY]);
    } catch (_) {
      return defaultProtectionProfile();
    }
  }

  async function saveProtectionProfile(profile) {
    const normalized = normalizeProtectionProfile(profile);
    normalized.updatedAt = new Date().toISOString();
    currentProtectionProfile = normalized;
    try {
      if (browser?.storage?.local?.set) {
        await browser.storage.local.set({ [PROTECTION_PROFILE_STORAGE_KEY]: normalized });
      }
    } catch (_) {
      // Keep the in-memory profile even if local persistence is unavailable.
    }
    return normalized;
  }

  function buildTimeoutError(message) {
    const err = new Error(message);
    err.name = "AECCSTimeoutError";
    err.aeccsTimeout = true;
    return err;
  }

  async function withTimeout(promiseOrFactory, timeoutMs, message) {
    if (!(timeoutMs > 0)) {
      return typeof promiseOrFactory === "function"
        ? promiseOrFactory()
        : promiseOrFactory;
    }

    let timeoutId = null;
    const timeoutPromise = new Promise((_, reject) => {
      timeoutId = setTimeout(() => reject(buildTimeoutError(message)), timeoutMs);
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

  // ── Init ──────────────────────────────────────────────────────────────────

  async function init() {
    try {
      bindStudyInsights();
      bindPetSection();
      bindPetTooltips();
      bindInteractionActions();
      bindProtectionProfileControls();

      const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
      if (!tab) return showError("No active tab found.");

      currentTabId = tab.id;
      els.siteDomain.textContent = new URL(tab.url).hostname;
      currentProtectionProfile = await loadProtectionProfile();
      applyProtectionProfileToControls(currentProtectionProfile);
      renderProtectionProfileUi(currentProtectionProfile, null);
      await analyzeCurrentTab();
    } catch (err) {
      showError(err.message);
    }
  }

  function bindInteractionActions() {
    if (els.recheckButton) {
      els.recheckButton.addEventListener("click", () => {
        void analyzeCurrentTab();
      });
    }
    if (els.startOverButton) {
      els.startOverButton.addEventListener("click", () => {
        void startOverInteractionFlow();
      });
    }
  }

  function bindProtectionProfileControls() {
    if (els.browserProtectionSelect) {
      els.browserProtectionSelect.addEventListener("change", () => {
        void handleProtectionProfileChange();
      });
    }
    for (const input of els.extraToolInputs) {
      input.addEventListener("change", () => {
        void handleProtectionProfileChange();
      });
    }
  }

  async function handleProtectionProfileChange() {
    const profile = readProtectionProfileFromControls();
    currentProtectionProfile = await saveProtectionProfile(profile);
    renderProtectionProfileUi(currentProtectionProfile, currentAnalysis);
  }

  function readProtectionProfileFromControls() {
    return normalizeProtectionProfile({
      browserProtection: els.browserProtectionSelect?.value || "none",
      extraTools: els.extraToolInputs
        .filter(input => input.checked)
        .map(input => input.value),
    });
  }

  function applyProtectionProfileToControls(profile) {
    const normalized = normalizeProtectionProfile(profile);
    if (els.browserProtectionSelect) {
      els.browserProtectionSelect.value = normalized.browserProtection;
    }
    const selectedTools = new Set(normalized.extraTools);
    for (const input of els.extraToolInputs) {
      input.checked = selectedTools.has(input.value);
    }
  }

  async function analyzeCurrentTab() {
    if (currentTabId == null) {
      showError("No active tab found.");
      return null;
    }

    setPopupBusy(true);
    showLoadingState();
    try {
      const result = await withTimeout(
        () => browser.runtime.sendMessage({ action: "analyze", tabId: currentTabId }),
        POPUP_ANALYZE_TIMEOUT_MS,
        POPUP_ANALYZE_TIMEOUT_MESSAGE
      );

      if (result == null) {
        showError("AECCS did not receive a usable analysis response from the background worker.");
        return null;
      }

      if (result.error) {
        showError(result.error);
        return null;
      }

      render(result);
      return result;
    } catch (err) {
      showError(err.message);
      return null;
    } finally {
      setPopupBusy(false);
    }
  }

  async function startOverInteractionFlow() {
    if (currentTabId == null) {
      showError("No active tab found.");
      return;
    }

    setPopupBusy(true);
    showLoadingState();
    try {
      const response = await withTimeout(
        () => browser.runtime.sendMessage({ action: "clearInteractionSession", tabId: currentTabId }),
        POPUP_ACTION_TIMEOUT_MS,
        "AECCS could not reset the compare flow in time. Try reopening the popup."
      );
      if (response?.ok === false) {
        throw new Error(response.error || "AECCS could not reset the compare flow.");
      }
      await analyzeCurrentTab();
    } catch (err) {
      showError(err.message);
    } finally {
      setPopupBusy(false);
    }
  }

  function showLoadingState() {
    els.loading.classList.remove("hidden");
    els.errorState.classList.add("hidden");
    els.disabledState.classList.add("hidden");
    els.results.classList.add("hidden");
  }

  function setPopupBusy(isBusy) {
    if (els.recheckButton) {
      els.recheckButton.disabled = isBusy;
    }
    if (els.startOverButton) {
      els.startOverButton.disabled = isBusy;
    }
    if (els.browserProtectionSelect) {
      els.browserProtectionSelect.disabled = isBusy;
    }
    for (const input of els.extraToolInputs) {
      input.disabled = isBusy;
    }
  }

  function showError(msg) {
    els.loading.classList.add("hidden");
    els.disabledState.classList.add("hidden");
    els.results.classList.add("hidden");
    els.errorState.classList.remove("hidden");
    els.errorMsg.textContent = msg;
  }

  function showDisabledState(disabled) {
    els.loading.classList.add("hidden");
    els.errorState.classList.add("hidden");
    els.results.classList.add("hidden");
    els.disabledState.classList.remove("hidden");
    els.disabledTitle.textContent = disabled?.title || "Evaluation unavailable on this page";
    els.disabledMsg.textContent =
      disabled?.message ||
      "AECCS did not detect an active cookie banner or a meaningful post-interaction consent state, so this website was not evaluated.";
    renderProtectionProfileUi(currentProtectionProfile, null);
  }

  // ── Render ────────────────────────────────────────────────────────────────

  function render(data) {
    currentAnalysis = data;
    renderedInsightsKey = null;
    els.loading.classList.add("hidden");
    els.errorState.classList.add("hidden");
    els.disabledState.classList.add("hidden");
    els.results.classList.add("hidden");

    renderStudyCopy(data.studyMetadata);

    if (data.analysisMode === "unavailable" || data.evaluationDisabled?.active) {
      showDisabledState(data.evaluationDisabled);
      return;
    }

    els.results.classList.remove("hidden");

    // Government domain alert
    if (data.isGovDomain) {
      els.govAlert.classList.remove("hidden");
    } else {
      els.govAlert.classList.add("hidden");
    }

    renderScoreCard(els.gradeBadge, els.gradeLetter, els.scoreValue, els.scoreLabel, data.score);
    renderProtectionProfileUi(currentProtectionProfile, data);
    renderBaselineScore(data.baselineScore);
    renderCookies(data);
    renderTrackers(data.trackersByVendor);
    renderConsent(data.consentScan, data.cmpStats, data.studyMetadata);
    renderInteractionAudit(data);
    renderButtonComparison(data.consentScan?.buttonComparison);
    renderDarkPatterns(data.consentScan?.darkPatterns);
    renderCriteria(data.score.criteria);
    syncPetRecommendations(data.petRecommendations, data.studyMetadata);

    if (els.studyInsightsSection) {
      els.studyInsightsSection.classList.remove("hidden");
      if (els.studyInsightsSection.open) {
        renderStudyInsights(data);
      } else if (els.studyInsightsContent) {
        clearNode(els.studyInsightsContent);
      }
    }
  }

  function bindStudyInsights() {
    if (!els.studyInsightsSection) return;
    els.studyInsightsSection.addEventListener("toggle", () => {
      if (els.studyInsightsSection.open && currentAnalysis) {
        renderStudyInsights(currentAnalysis);
      } else if (els.studyInsightsContent) {
        clearNode(els.studyInsightsContent);
        renderedInsightsKey = null;
      }
    });
  }

  function bindPetSection() {
    if (!els.petSection) return;
    els.petSection.addEventListener("toggle", () => {
      if (els.petSection.open && currentAnalysis) {
        renderPetRecommendations(currentAnalysis.petRecommendations, currentAnalysis.studyMetadata);
      } else {
        clearPetRecommendations();
      }
    });
  }

  function bindPetTooltips() {
    if (!els.petList || els.petList.dataset.tooltipsBound === "true") return;
    els.petList.dataset.tooltipsBound = "true";

    els.petList.addEventListener("click", onPetTooltipClick);
    els.petList.addEventListener("focusin", onPetTooltipFocusIn);
    els.petList.addEventListener("focusout", onPetTooltipFocusOut);
    els.petList.addEventListener("mouseover", onPetTooltipMouseOver);
    els.petList.addEventListener("mouseout", onPetTooltipMouseOut);

    document.addEventListener("click", onDocumentClickForPetTooltip);
    document.addEventListener("keydown", onDocumentKeydownForPetTooltip);
  }

  function onPetTooltipClick(event) {
    const button = event.target.closest(".pet-study-info");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    openPetTooltip(button);
  }

  function onPetTooltipFocusIn(event) {
    const button = event.target.closest(".pet-study-info");
    if (!button) return;
    openPetTooltip(button);
  }

  function onPetTooltipFocusOut(event) {
    const container = event.target.closest(".pet-study");
    if (!container) return;
    const nextTarget = event.relatedTarget;
    if (nextTarget && container.contains(nextTarget)) return;
    closePetTooltip(container.querySelector(".pet-study-info"));
  }

  function onPetTooltipMouseOver(event) {
    const container = event.target.closest(".pet-study");
    if (!container) return;
    const related = event.relatedTarget;
    if (related && container.contains(related)) return;
    openPetTooltip(container.querySelector(".pet-study-info"));
  }

  function onPetTooltipMouseOut(event) {
    const container = event.target.closest(".pet-study");
    if (!container) return;
    const related = event.relatedTarget;
    if (related && container.contains(related)) return;
    const button = container.querySelector(".pet-study-info");
    if (document.activeElement === button) return;
    closePetTooltip(button);
  }

  function onDocumentClickForPetTooltip(event) {
    if (event.target.closest(".pet-study")) return;
    closeActivePetTooltip();
  }

  function onDocumentKeydownForPetTooltip(event) {
    if (event.key !== "Escape" || !activePetTooltipTrigger) return;
    event.preventDefault();
    const trigger = activePetTooltipTrigger;
    closeActivePetTooltip();
    if (trigger && typeof trigger.focus === "function") {
      trigger.focus();
    }
  }

  function openPetTooltip(button) {
    if (!button) return;
    if (activePetTooltipTrigger && activePetTooltipTrigger !== button) {
      closePetTooltip(activePetTooltipTrigger);
    }
    const tooltip = tooltipForButton(button);
    if (!tooltip) return;
    button.setAttribute("aria-expanded", "true");
    tooltip.hidden = false;
    button.closest(".pet-study")?.classList.add("open");
    activePetTooltipTrigger = button;
  }

  function closePetTooltip(button) {
    if (!button) return;
    const tooltip = tooltipForButton(button);
    button.setAttribute("aria-expanded", "false");
    if (tooltip) {
      tooltip.hidden = true;
    }
    button.closest(".pet-study")?.classList.remove("open");
    if (activePetTooltipTrigger === button) {
      activePetTooltipTrigger = null;
    }
  }

  function closeActivePetTooltip() {
    if (!activePetTooltipTrigger) return;
    closePetTooltip(activePetTooltipTrigger);
  }

  function tooltipForButton(button) {
    const tooltipId = button?.getAttribute("aria-controls");
    return tooltipId ? document.getElementById(tooltipId) : null;
  }

  function renderProtectionProfileUi(profile, analysis) {
    const normalized = normalizeProtectionProfile(profile);
    currentProtectionProfile = normalized;

    if (els.browsingSetupSummary) {
      els.browsingSetupSummary.textContent = summarizeProtectionProfile(normalized);
    }
    if (els.browsingSetupStatus) {
      els.browsingSetupStatus.textContent = hasDeclaredProtections(normalized)
        ? "Saved locally on this browser only. AECCS uses this profile for explanatory caveats and keeps scores unchanged."
        : "Saved locally on this browser only. Leave everything undeclared if you want no protection-specific caveats.";
    }

    renderProtectionExplainer(normalized);
    renderProtectionScoreContext(normalized, analysis);
  }

  function renderProtectionExplainer(profile) {
    if (!els.protectionExplainerContent || !els.protectionExplainer) return;

    clearNode(els.protectionExplainerContent);
    const normalized = normalizeProtectionProfile(profile);

    const intro = hasDeclaredProtections(normalized)
      ? `Declared setup: ${summarizeProtectionProfile(normalized)}. AECCS keeps the live score exactly the same, but adds these caveats to explain what your current setup may have changed before the audit ran.`
      : "No protections are declared. AECCS will interpret the current page state without any setup-specific caveat banner.";
    els.protectionExplainerContent.appendChild(createElement("div", { text: intro }));

    const notes = [];
    if (normalized.browserProtection !== "none") {
      notes.push(`${BROWSER_PROTECTION_LABELS[normalized.browserProtection]} can suppress some cookies, trackers, or third-party requests before AECCS reads the page, which may make the measured score look cleaner than an unprotected session.`);
    }
    if (normalized.extraTools.includes("ublock_origin")) {
      notes.push("uBlock Origin can block trackers and page resources before the audit runs, which may reduce observed trackers or change how consent UI loads.");
    }
    if (normalized.extraTools.includes("privacy_badger")) {
      notes.push("Privacy Badger can learn and block trackers dynamically, so repeated visits may not match a fresh-browser audit.");
    }
    if (normalized.extraTools.includes("consent_o_matic")) {
      notes.push("Consent-O-Matic can automate consent choices, so post-click outcomes may reflect automated consent handling rather than only your manual interaction.");
    }
    if (notes.length === 0) {
      notes.push("If you later declare blockers or browser protections here, AECCS will explain how they may affect measured cookies, trackers, banner behavior, and post-click outcomes.");
    }

    for (const note of notes) {
      els.protectionExplainerContent.appendChild(createElement("div", { text: note }));
    }
  }

  function renderProtectionScoreContext(profile, analysis) {
    if (els.scoreContext) {
      els.scoreContext.classList.add("hidden");
      els.scoreContext.textContent = "";
    }
    if (els.protectionCaveat) {
      els.protectionCaveat.classList.add("hidden");
    }
    if (els.protectionCaveatText) {
      els.protectionCaveatText.textContent = "";
    }

    const normalized = normalizeProtectionProfile(profile);
    if (!analysis || !hasDeclaredProtections(normalized)) {
      return;
    }

    if (els.scoreContext) {
      els.scoreContext.classList.remove("hidden");
      els.scoreContext.textContent = "Measured in your current browsing setup.";
    }

    const summary = summarizeProtectionProfile(normalized);
    const caveatParts = [
      `${summary} may change which cookies, trackers, or consent surfaces are visible before AECCS measures the page.`,
    ];
    if (isConsentOMaticDeclared(normalized)) {
      caveatParts.push("Consent-O-Matic can also automate consent outcomes, so post-click evidence may not reflect only manual interaction.");
    }

    if (els.protectionCaveatText) {
      els.protectionCaveatText.textContent = caveatParts.join(" ");
    }
    if (els.protectionCaveat) {
      els.protectionCaveat.classList.remove("hidden");
    }
  }

  function renderStudyCopy(studyMetadata) {
    const snapshotDateLabel = studyMetadata?.snapshotDateLabel || "March 6, 2026";
    const sampleSize = studyMetadata?.sampleSize || 1000;
    const successfulCrawls = studyMetadata?.successfulCrawls || 861;
    const publicSector = studyMetadata?.publicSector || {};

    if (els.govNote) {
      els.govNote.textContent =
        `Public-sector sites were included in the combined corpus. In the successful government/public-sector category (${publicSector.successfulSites || 77} sites), average compliance was ${publicSector.avgCompliance || 30.9}/100 and ${formatPercent(publicSector.preConsentTrackerRate ?? 0.753)} showed pre-consent trackers.`;
    }

    if (els.footerNote) {
      els.footerNote.textContent =
        `AECCS · Session-limited local consent audit · ${sampleSize}-site combined study snapshot · ${snapshotDateLabel}`;
    }
  }

  // ── Score Badge ───────────────────────────────────────────────────────────

  function renderScoreCard(gradeBadgeEl, gradeLetterEl, scoreValueEl, scoreLabelEl, score) {
    if (!score) return;
    const color = GRADE_COLORS[score.grade] || GRADE_COLORS.F;
    gradeBadgeEl.style.color = color;
    gradeBadgeEl.style.borderColor = color;
    gradeLetterEl.textContent = score.grade;
    scoreValueEl.textContent = score.overall_score;
    if (scoreLabelEl) {
      scoreLabelEl.textContent = score.label || "GDPR Compliance Score";
    }
  }

  function renderBaselineScore(score) {
    if (!score) {
      els.baselineScoreSection?.classList.add("hidden");
      return;
    }

    els.baselineScoreSection?.classList.remove("hidden");
    renderScoreCard(
      els.baselineGradeBadge,
      els.baselineGradeLetter,
      els.baselineScoreValue,
      els.baselineScoreLabel,
      score
    );
  }

  // ── Cookie Breakdown ──────────────────────────────────────────────────────

  function renderCookies(data) {
    const counts = data.categoryCounts || {};
    const total = data.totalCookies || 0;

    const order = ["Analytics", "Advertising", "Social", "Fingerprinting", "Functional", "Unknown"];
    clearNode(els.cookieBar);

    if (total === 0) {
      const filler = createElement("div");
      filler.style.flex = "1";
      filler.style.background = "var(--bg)";
      filler.style.borderRadius = "5px";
      els.cookieBar.appendChild(filler);
    } else {
      for (const cat of order) {
        const n = counts[cat] || 0;
        if (n === 0) continue;
        const pct = (n / total) * 100;
        const seg = document.createElement("div");
        seg.className = "cookie-bar-segment";
        seg.style.width = `${pct}%`;
        seg.style.background = CATEGORY_COLORS[cat] || CATEGORY_COLORS.Unknown;
        seg.title = `${cat}: ${n}`;
        els.cookieBar.appendChild(seg);
      }
    }

    clearNode(els.cookieCounts);
    for (const cat of order) {
      const n = counts[cat] || 0;
      if (n === 0) continue;
      const item = createElement("div", { className: "cookie-count-item" });
      const dot = createElement("span", { className: "cookie-dot" });
      dot.style.background = CATEGORY_COLORS[cat];
      item.append(dot, document.createTextNode(`${cat}: ${n}`));
      els.cookieCounts.appendChild(item);
    }

    els.cookieMeta.textContent =
      `${total} cookies total | ${data.thirdPartyCount || 0} third-party | ${data.trackerCount || 0} trackers`;
  }

  // ── Tracker List ──────────────────────────────────────────────────────────

  function renderTrackers(trackersByVendor) {
    clearNode(els.trackerList);
    const vendors = Object.keys(trackersByVendor || {});
    if (vendors.length === 0) {
      els.trackerList.appendChild(createElement("div", { className: "no-trackers", text: "No trackers detected" }));
      return;
    }
    for (const vendor of vendors) {
      const cookies = trackersByVendor[vendor];
      const group = createElement("div", { className: "tracker-group" });
      group.append(
        createElement("div", { className: "tracker-vendor", text: `${vendor} (${cookies.length})` }),
        createElement("div", { className: "tracker-cookies", text: cookies.join(", ") })
      );
      els.trackerList.appendChild(group);
    }
  }

  // ── Consent Banner + CMP Stats ────────────────────────────────────────────

  function renderConsent(scan, cmpStats, studyMetadata) {
    clearNode(els.consentInfo);
    els.cmpInfo.classList.add("hidden");
    clearNode(els.cmpInfo);

    if (!scan || scan.error) {
      els.consentInfo.appendChild(buildConsentRow("warn", "Consent scan unavailable"));
      return;
    }

    if (scan.cmpDetected) {
      els.consentInfo.appendChild(
        buildConsentRow("ok", [
          "CMP detected: ",
          createElement("strong", { text: scan.cmpDetected }),
        ])
      );
    } else {
      els.consentInfo.appendChild(buildConsentRow("warn", "No known CMP detected"));
    }

    if (!scan.bannerFound) {
      els.consentInfo.appendChild(buildConsentRow("warn", "No consent banner found"));
    } else {
      els.consentInfo.appendChild(buildConsentRow("ok", "Consent banner found"));
    }

    if (scan.hasAcceptButton) {
      els.consentInfo.appendChild(buildConsentRow("ok", `Accept button: "${scan.acceptButtonText}"`));
    } else {
      els.consentInfo.appendChild(buildConsentRow("warn", "No accept button found"));
    }

    if (scan.hasRejectButton) {
      els.consentInfo.appendChild(buildConsentRow("ok", `Reject button: "${scan.rejectButtonText}"`));
    } else if (scan.hasSettingsButton && scan.rejectClicksRequired < 999) {
      const clickLabel = scan.rejectClicksRequired === 2 ? "2 clicks" : `${scan.rejectClicksRequired} clicks`;
      const settingsLabel = scan.settingsButtonText || "Settings";
      els.consentInfo.appendChild(
        buildConsentRow("warn", `Reject available via settings: "${settingsLabel}" (${clickLabel})`)
      );
    } else {
      els.consentInfo.appendChild(buildConsentRow("bad", "No reject button found"));
    }

    if (cmpStats && scan.cmpDetected) {
      els.cmpInfo.classList.remove("hidden");
      const stats = createElement("div", { className: "cmp-stats" });
      stats.append(
        createElement("div", {
          className: "cmp-stats-title",
          text: `${scan.cmpDetected} in the ${studyMetadata?.sampleSize || 1000}-site AECCS combined snapshot`,
        }),
        buildLabeledValueRow("cmp-stat-row", "Avg compliance score", `${cmpStats.avgScore}/100`),
        buildLabeledValueRow("cmp-stat-row", "Sites with reject button", `${Math.round(cmpStats.rejectRate * 100)}%`),
        buildLabeledValueRow("cmp-stat-row", "Sample size", `${cmpStats.sampleSize} sites`),
        buildLabeledValueRow("cmp-stat-row", "CMP PET score", `${cmpStats.petScore}`)
      );
      els.cmpInfo.appendChild(stats);
    }
  }

  function renderInteractionAudit(data) {
    clearNode(els.compareFlow);
    clearNode(els.interactionInfo);

    if (!els.interactionSection) return;

    const compareState = deriveCompareState(data);
    renderAnalysisCompleteness(compareState.completeness);

    if (!compareState.showSection) {
      els.interactionSection.classList.add("hidden");
      return;
    }

    els.interactionSection.classList.remove("hidden");
    renderCompareFlow(compareState);
    renderInteractionNarrative(compareState, data.interactionAudit);
  }

  function deriveCompareState(data) {
    const interactionAudit = data?.interactionAudit || null;
    const analysisMode = data?.analysisMode || "baseline_banner";

    if (!interactionAudit && analysisMode !== "post_interaction") {
      return {
        key: "unavailable_or_expired",
        showSection: false,
        completeness: "Partial evidence",
      };
    }

    if (analysisMode === "baseline_banner" && interactionAudit?.status === "armed") {
      return {
        key: "waiting_for_action",
        showSection: true,
        title: "Baseline captured",
        badge: "Banner visible",
        completeness: "Banner visible",
        copy: "AECCS captured the banner state on this page. Click Accept, Reject, or Settings on the page itself, then reopen AECCS or use Re-check now to compare what changed.",
        steps: ["complete", "current", "pending", "pending"],
      };
    }

    if (interactionAudit?.status === "observed") {
      return {
        key: "partial_capture",
        showSection: true,
        title: "Consent action observed",
        badge: "Partial evidence",
        completeness: "Partial evidence",
        copy: "AECCS saw a consent action but does not have a stable post-click state yet. Re-check now in a moment to capture the after state.",
        steps: ["complete", "complete", "current", "pending"],
      };
    }

    if (analysisMode === "post_interaction" && interactionAudit?.baseline) {
      return {
        key: "post_click_result",
        showSection: true,
        title: "Post-click result captured",
        badge: "Post-click state",
        completeness: "Post-click state",
        copy: buildCompareOutcomeCopy(interactionAudit),
        steps: ["complete", "complete", "complete", "complete"],
      };
    }

    if (analysisMode === "post_interaction") {
      return {
        key: "no_comparable_baseline",
        showSection: true,
        title: "No comparable baseline",
        badge: "No comparable baseline",
        completeness: "No comparable baseline",
        copy: "AECCS measured the current post-click state, but it did not capture a banner baseline first. Start over only if the banner can be shown again and you want a true before/after comparison.",
        steps: ["unavailable", "unavailable", "complete", "current"],
      };
    }

    return {
      key: "unavailable_or_expired",
      showSection: true,
      title: "Compare flow unavailable",
      badge: "Partial evidence",
      completeness: "Partial evidence",
      copy: "AECCS could not preserve a comparable before/after flow for this page. Try Start over while the banner is still visible.",
      steps: ["unavailable", "pending", "pending", "current"],
    };
  }

  function renderAnalysisCompleteness(label) {
    if (!els.analysisCompleteness) return;
    if (!label) {
      els.analysisCompleteness.classList.add("hidden");
      els.analysisCompleteness.textContent = "";
      return;
    }
    els.analysisCompleteness.classList.remove("hidden");
    els.analysisCompleteness.textContent = `Analysis completeness: ${label}`;
  }

  function renderCompareFlow(compareState) {
    if (!els.compareFlow) return;

    const container = createElement("div", { className: "compare-flow" });
    const header = createElement("div", { className: "compare-flow-header" });
    const text = createElement("div");
    text.append(
      createElement("div", { className: "compare-flow-title", text: compareState.title || "Guided compare" }),
      createElement("div", { className: "compare-flow-subtitle", text: compareState.copy || "" })
    );

    const badge = createElement("span", {
      className: `compare-state-badge state-${slugify(compareState.key)} state-${slugify(compareState.badge || "")}`,
      text: compareState.badge || "Partial evidence",
    });
    header.append(text, badge);
    container.appendChild(header);

    if (compareState.steps?.length) {
      const steps = createElement("div", { className: "compare-steps" });
      const labels = [
        "Capture baseline",
        "Click on the page",
        "Re-check in AECCS",
        "Review outcome",
      ];
      compareState.steps.forEach((status, index) => {
        const step = createElement("div", { className: `compare-step is-${status}` });
        step.append(
          createElement("span", { className: "compare-step-dot", text: String(index + 1) }),
          createElement("span", { text: labels[index] || `Step ${index + 1}` })
        );
        steps.appendChild(step);
      });
      container.appendChild(steps);
    }

    els.compareFlow.appendChild(container);
  }

  function buildCompareOutcomeCopy(interactionAudit) {
    const actionText = interactionAudit?.action?.text || readableActionType(interactionAudit?.action?.type);
    const deltaSummary = buildDeltaSummary(interactionAudit?.delta);
    const trustSummary = buildTrustSummary(interactionAudit);
    return `AECCS compared the current page against the earlier banner baseline after "${actionText || "the recorded action"}". ${deltaSummary} ${trustSummary}`;
  }

  function buildDeltaSummary(delta) {
    if (!delta) {
      return "No before/after delta is available yet.";
    }

    const parts = [
      deltaPhrase("cookies", delta.totalCookies),
      deltaPhrase("third-party cookies", delta.thirdPartyCount),
      deltaPhrase("trackers", delta.trackerCount),
    ].filter(Boolean);

    if (parts.length === 0) {
      return "AECCS did not see a meaningful cookie or tracker change after the action.";
    }

    return `It ${parts.join(", ")}.`;
  }

  function deltaPhrase(label, value) {
    if (typeof value !== "number" || Number.isNaN(value)) return null;
    if (value > 0) return `increased ${label} by ${value}`;
    if (value < 0) return `reduced ${label} by ${Math.abs(value)}`;
    return `left ${label} unchanged`;
  }

  function buildTrustSummary(interactionAudit) {
    switch (interactionAudit?.honesty?.verdict) {
      case "honest":
        return "The observed outcome supports the trustworthiness of the claimed banner action.";
      case "mixed":
        return "The observed outcome only partially supports the claimed banner action.";
      case "dishonest":
        return "The observed outcome weakens trust in the claimed banner action.";
      case "not_applicable":
        return "This action is not scored as an honesty check, but the after-state is still useful context.";
      default:
        return "AECCS could not confidently judge the trustworthiness of the claimed banner action from the available evidence.";
    }
  }

  function renderInteractionNarrative(compareState, interactionAudit) {
    if (!els.interactionInfo || !interactionAudit) return;

    const actionCard = createElement("div", { className: "interaction-summary" });
    actionCard.append(
      createElement("div", { className: "interaction-card-title", text: "What AECCS Saw" }),
      buildLabeledValueRow("interaction-kv", "Captured stage", compareState.badge || "Partial evidence"),
      buildLabeledValueRow("interaction-kv", "Recorded action", formatInteractionAction(interactionAudit.action)),
      buildLabeledValueRow("interaction-kv", "Trust signal", trustSignalLabel(interactionAudit.honesty?.verdict)),
      buildLabeledValueRow("interaction-kv", "Evidence mode", readableAnalysisMode(currentAnalysis?.analysisMode))
    );
    els.interactionInfo.appendChild(actionCard);

    if (interactionAudit.delta) {
      const delta = interactionAudit.delta;
      const deltaCard = createElement("div", { className: "interaction-card" });
      deltaCard.append(
        createElement("div", { className: "interaction-card-title", text: "How The Page Changed" }),
        createElement("div", { className: "interaction-narrative", text: buildDeltaSummary(delta) }),
        buildLabeledValueRow("interaction-kv", "Total cookies", signedMetric(delta.totalCookies)),
        buildLabeledValueRow("interaction-kv", "Third-party cookies", signedMetric(delta.thirdPartyCount)),
        buildLabeledValueRow("interaction-kv", "Trackers", signedMetric(delta.trackerCount))
      );

      if (delta.newCookies?.length) {
        deltaCard.appendChild(
          createElement("div", {
            className: "interaction-list",
            text: `New cookies after the action: ${delta.newCookies.map(item => `${item.name} (${item.category})`).join(", ")}`,
          })
        );
      }
      if (delta.newTrackers?.length) {
        deltaCard.appendChild(
          createElement("div", {
            className: "interaction-list interaction-list-bad",
            text: `New trackers after the action: ${delta.newTrackers.map(item => `${item.name} (${item.vendor})`).join(", ")}`,
          })
        );
      }

      els.interactionInfo.appendChild(deltaCard);
    }

    if (interactionAudit.honesty?.findings?.length) {
      const honestyCard = createElement("div", { className: "interaction-card" });
      honestyCard.append(
        createElement("div", { className: "interaction-card-title", text: "How To Read This Outcome" }),
        createElement("div", { className: "interaction-narrative", text: buildTrustSummary(interactionAudit) })
      );
      for (const finding of interactionAudit.honesty.findings) {
        honestyCard.appendChild(createElement("div", { className: "interaction-list", text: finding }));
      }
      els.interactionInfo.appendChild(honestyCard);
    }
  }

  function formatInteractionAction(action) {
    if (!action?.text) return "No observed consent action";
    return `${action.text}${action.observed ? " (observed)" : " (inferred)"}`;
  }

  function readableActionType(type) {
    switch (type) {
      case "accept": return "accept action";
      case "reject": return "reject action";
      case "essential": return "essential-only action";
      case "dismiss": return "dismiss action";
      default: return "recorded action";
    }
  }

  function trustSignalLabel(verdict) {
    switch (verdict) {
      case "honest": return "Supports banner claim";
      case "mixed": return "Partially supports banner claim";
      case "dishonest": return "Weakens banner claim";
      case "not_applicable": return "Not an honesty-scored action";
      default: return "Could not verify";
    }
  }

  function readableAnalysisMode(mode) {
    switch (mode) {
      case "baseline_banner": return "Banner baseline";
      case "post_interaction": return "Current post-click state";
      case "unavailable": return "Unavailable";
      default: return mode || "Unknown";
    }
  }

  function buildConsentRow(type, content) {
    const icons = { ok: "\u2713", warn: "\u25cf", bad: "\u2717" };
    const row = createElement("div", { className: "consent-row" });
    const icon = createElement("span", { className: `consent-icon ${type}`, text: icons[type] || "" });
    const body = createElement("span");
    appendParts(body, content);
    row.append(icon, body);
    return row;
  }

  // ── Accept vs Reject UX Comparison ────────────────────────────────────────

  function renderButtonComparison(comp) {
    clearNode(els.buttonComparison);
    if (!comp || !comp.available) {
      els.buttonCompSection.classList.add("hidden");
      return;
    }

    els.buttonCompSection.classList.remove("hidden");

    const rejectLabel = comp.rejectSource === "settings" ? "Reject via Settings" : "Reject";
    const rejectMetaSuffix =
      comp.reject && comp.rejectSource === "settings" && comp.reject.clicksRequired > 1
        ? ` | ${comp.reject.clicksRequired} clicks via settings`
        : "";

    const compare = createElement("div", { className: "btn-compare" });
    compare.append(
      buildButtonPreview("Accept", comp.accept),
      buildButtonPreview(rejectLabel, comp.reject, rejectMetaSuffix)
    );
    els.buttonComparison.appendChild(compare);

    if (comp.issues && comp.issues.length > 0) {
      const issues = createElement("div", { className: "btn-issues" });
      for (const issue of comp.issues) {
        const item = createElement("div", { className: "btn-issue-item" });
        item.append(createElement("span", { text: "\u26a0" }), document.createTextNode(` ${issue}`));
        issues.appendChild(item);
      }
      els.buttonComparison.appendChild(issues);
    }
  }

  // ── Dark Pattern Details ──────────────────────────────────────────────────

  function renderDarkPatterns(dp) {
    clearNode(els.darkPatternDetails);
    if (!dp || dp.count === 0) {
      els.darkPatternDetails.appendChild(createElement("div", { className: "dp-none", text: "No dark patterns detected" }));
      return;
    }

    for (const name of dp.detected) {
      const info = AECCS.DARK_PATTERN_INFO[name];
      if (!info) {
        const fallbackCard = createElement("div", { className: "dp-card" });
        fallbackCard.appendChild(createElement("div", { className: "dp-card-name", text: name }));
        els.darkPatternDetails.appendChild(fallbackCard);
        continue;
      }

      const card = createElement("div", { className: `dp-card severity-${info.severity}` });
      const header = createElement("div", { className: "dp-card-header" });
      header.append(
        createElement("span", { className: "dp-card-name", text: name }),
        createElement("span", { className: `dp-severity ${info.severity}`, text: info.severity })
      );
      card.append(
        header,
        createElement("div", { className: "dp-description", text: info.description }),
        createElement("div", { className: "dp-gdpr-ref", text: info.gdprArticle })
      );
      els.darkPatternDetails.appendChild(card);
    }
  }

  // ── Criteria Breakdown ────────────────────────────────────────────────────

  function renderCriteria(criteria) {
    clearNode(els.criteriaBody);
    for (const [key, { score, details }] of Object.entries(criteria)) {
      const label = CRITERIA_LABELS[key] || key;
      const hasNumericScore = typeof score === "number";
      const color = hasNumericScore ? scoreColor(score) : "var(--text-dim)";
      const tr = createElement("tr");

      const detailsCell = createElement("td");
      detailsCell.append(
        createElement("div", { className: "criteria-name", text: label }),
        createElement("div", { className: "criteria-details", text: details })
      );

      const scoreCell = createElement("td", { text: hasNumericScore ? score : "n/a" });
      scoreCell.style.color = color;

      const progressCell = createElement("td");
      const progressBar = createElement("div", { className: "progress-bar" });
      const progressFill = createElement("div", { className: "progress-fill" });
      progressFill.style.width = `${hasNumericScore ? score : 0}%`;
      progressFill.style.background = color;
      progressBar.appendChild(progressFill);
      progressCell.appendChild(progressBar);

      tr.append(detailsCell, scoreCell, progressCell);
      els.criteriaBody.appendChild(tr);
    }
  }

  // ── PET Recommendations ───────────────────────────────────────────────────

  function syncPetRecommendations(pets, studyMetadata) {
    closeActivePetTooltip();

    if (!pets || pets.length === 0) {
      els.petSection.classList.add("hidden");
      els.petSection.open = false;
      clearPetRecommendations();
      return;
    }

    els.petSection.classList.remove("hidden");
    if (els.petSection.open) {
      renderPetRecommendations(pets, studyMetadata);
    } else {
      clearPetRecommendations();
    }
  }

  function renderPetRecommendations(pets, studyMetadata) {
    if (!els.petList || !els.petSubtitle) return;

    els.petSubtitle.textContent = buildPetSubtitleText(studyMetadata);
    clearNode(els.petList);

    for (const [index, pet] of pets.entries()) {
      const color = petStudyColor(pet.studyTrackerReductionPct);
      const metricLabel = pet.studyMetricLabel || studyBadgeLabel(pet.studyTrackerReductionPct);
      const tooltipText = pet.studyTooltipText || buildPetStudyTooltipText(pet);
      const tooltipId = `pet-study-tooltip-${index}`;

      const card = createElement("div", { className: "pet-card" });
      const header = createElement("div", { className: "pet-header" });
      const title = createElement("div", { className: "pet-title" });
      title.append(
        createElement("span", { className: "pet-name", text: pet.name }),
        createElement("span", { className: "pet-type", text: pet.type })
      );
      header.appendChild(title);

      if (metricLabel || tooltipText) {
        const study = createElement("div", { className: "pet-study" });
        if (metricLabel) {
          const badge = createElement("span", { className: "pet-effectiveness", text: metricLabel });
          badge.style.color = color;
          badge.style.borderColor = color;
          study.appendChild(badge);
        }
        if (tooltipText) {
          const button = createElement("button", { className: "pet-study-info", text: "i" });
          button.type = "button";
          button.setAttribute("aria-label", `Explain study metric for ${pet.name}`);
          button.setAttribute("aria-expanded", "false");
          button.setAttribute("aria-controls", tooltipId);

          const tooltip = createElement("div", {
            className: "pet-study-tooltip",
            text: tooltipText,
            attrs: { id: tooltipId, role: "tooltip" },
          });
          tooltip.hidden = true;

          study.append(button, tooltip);
        }
        header.appendChild(study);
      }

      card.append(
        header,
        createElement("div", { className: "pet-desc", text: pet.description })
      );

      if (pet.whyRecommended) {
        card.appendChild(createElement("div", { className: "pet-desc", text: `Why recommended: ${pet.whyRecommended}` }));
      }

      els.petList.appendChild(card);
    }
  }

  function clearPetRecommendations() {
    closeActivePetTooltip();
    if (els.petSubtitle) {
      els.petSubtitle.textContent = "";
    }
    if (els.petList) {
      clearNode(els.petList);
    }
  }

  function renderStudyInsights(data) {
    if (!els.studyInsightsContent) return;

    const key = buildInsightsKey(data);
    if (renderedInsightsKey === key) return;
    renderedInsightsKey = key;
    clearNode(els.studyInsightsContent);

    const study = data.studyMetadata || AECCS.STUDY_METADATA || {};
    const petStudy = AECCS.PET_STUDY_RESULTS || [];
    const cmpStudy = AECCS.CMP_STUDY_RESULTS || [];
    const highlights = AECCS.RESEARCH_HIGHLIGHTS || [];
    const guardrails = AECCS.CLAIM_GUARDRAILS || {};
    const fragment = document.createDocumentFragment();

    fragment.append(
      createElement("div", {
        className: "insight-badge",
        text: `${study.label || "AECCS 1000-site combined study snapshot"} · ${study.snapshotDateLabel || "March 6, 2026"}`,
      }),
      createElement("div", {
        className: "insight-intro",
        text: "This popup audits the current page locally and may continue a session-limited consent watch after you open it. The cards below add frozen AECCS study context without introducing clicks or network requests.",
      })
    );

    const positioningCard = buildInsightCard("Why AECCS is Different");
    positioningCard.appendChild(
      createElement("div", {
        className: "insight-card-copy",
        text: guardrails.positioning || "AECCS is a local, user-initiated cookie-consent auditor.",
      })
    );
    if (highlights.length > 0) {
      const highlightList = createElement("div", { className: "insight-list" });
      for (const item of highlights) {
        const listItem = createElement("div", { className: "insight-list-item" });
        listItem.append(
          createElement("strong", { text: item.title }),
          document.createTextNode(` — ${item.summary}`)
        );
        highlightList.appendChild(listItem);
      }
      positioningCard.appendChild(highlightList);
    }
    fragment.appendChild(positioningCard);

    const snapshotCard = buildInsightCard("Snapshot Metrics");
    snapshotCard.append(
      buildLabeledValueRow("insight-kv", "Run ID", study.runId || "combined-1000"),
      buildLabeledValueRow("insight-kv", "Study baseline", `${study.sampleSize || 1000} sites / ${study.successfulCrawls || 861} successful crawls`, "strong"),
      buildLabeledValueRow("insight-kv", "Sites with banners", `${study.bannerSites || 595}`, "strong"),
      buildLabeledValueRow("insight-kv", "Average compliance score", `${study.avgCompliance || 27.4}/100`, "strong"),
      buildLabeledValueRow("insight-kv", "Missing reject rate", formatPercent(study.missingRejectRate), "strong"),
      buildLabeledValueRow("insight-kv", "Multi-layer rejection", formatPercent(study.multiLayerRate), "strong"),
      buildLabeledValueRow("insight-kv", "Reject reduces trackers", formatPercent(study.rejectReducesTrackersRate), "strong"),
      buildLabeledValueRow("insight-kv", "Reject eliminates trackers", formatPercent(study.rejectEliminatesTrackersRate), "strong")
    );
    fragment.appendChild(snapshotCard);

    const guidanceCard = buildInsightCard("PET Guidance For This Page");
    if (data.petRecommendations && data.petRecommendations.length > 0) {
      guidanceCard.appendChild(
        createElement("div", {
          className: "insight-card-copy",
          text: "Recommendations stay local and session-limited: they are tied to the issues found on this page, then grounded in the shared AECCS combined-study snapshot rather than live PET simulation.",
        })
      );
      const list = createElement("div", { className: "insight-list" });
      for (const pet of data.petRecommendations) {
        const rationale = pet.whyRecommended || pet.studyLabel || "Study-backed recommendation";
        const item = createElement("div", { className: "insight-list-item" });
        item.append(createElement("strong", { text: pet.name }), document.createTextNode(` — ${rationale}`));
        list.appendChild(item);
      }
      guidanceCard.appendChild(list);
    } else {
      guidanceCard.appendChild(
        createElement("div", {
          className: "insight-card-copy",
          text: "No PET recommendation was needed for this page, but the extension still uses the same shared AECCS combined-study snapshot for context.",
        })
      );
    }
    fragment.appendChild(guidanceCard);

    const petStudyCard = buildInsightCard("Six PETs, One Study Snapshot");
    petStudyCard.appendChild(
      createElement("div", {
        className: "insight-card-copy",
        text: "AECCS keeps Brave Shields, Firefox ETP Standard, Firefox ETP Strict, uBlock Origin, Privacy Badger, and Consent-O-Matic in one comparable combined-study surface.",
      })
    );
    const petList = createElement("div", { className: "insight-list" });
    for (const pet of petStudy) {
      const item = createElement("div", { className: "insight-list-item" });
      item.append(
        createElement("strong", { text: pet.name }),
        document.createTextNode(` — ${pet.studyLabel}. ${pet.highlight}`)
      );
      petList.appendChild(item);
    }
    petStudyCard.appendChild(petList);
    fragment.appendChild(petStudyCard);

    const cmpCard = buildInsightCard("CMP And Public-Sector Context");
    if (data.consentScan?.cmpDetected && data.cmpStats) {
      const copy = createElement("div", { className: "insight-card-copy" });
      copy.append(
        document.createTextNode("Detected CMP: "),
        createElement("strong", { text: data.consentScan.cmpDetected }),
        document.createTextNode(`. In the shared snapshot it averaged ${data.cmpStats.avgScore}/100 with a reject rate of ${formatPercent(data.cmpStats.rejectRate)}.`)
      );
      cmpCard.appendChild(copy);
    } else {
      cmpCard.appendChild(
        createElement("div", {
          className: "insight-card-copy",
          text: "When a known CMP is detected, AECCS adds shared CMP study context instead of sending data to an external service.",
        })
      );
    }
    cmpCard.append(
      createElement("div", { className: "insight-divider" }),
      buildLabeledValueRow("insight-kv", "Best CMP in study", (cmpStudy[0] && cmpStudy[0].name) || "Didomi", "strong"),
      buildLabeledValueRow("insight-kv", "Current page is public sector", data.isGovDomain ? "Yes" : "No", "strong"),
      createElement("div", {
        className: "insight-card-copy",
        text: `The combined corpus included ${study.publicSector?.successfulSites || 77} successful government/public-sector sites. That subset averaged ${study.publicSector?.avgCompliance || 30.9}/100 compliance, and ${formatPercent(study.publicSector?.preConsentTrackerRate ?? 0.753)} showed pre-consent trackers.`,
      })
    );
    fragment.appendChild(cmpCard);

    const guardrailsCard = buildInsightCard("Methodology And Guardrails");
    guardrailsCard.appendChild(
      createElement("div", {
        className: "insight-card-copy",
        text: "Pipeline: crawl → classify → dark-pattern detect → score → CMP analysis → PET comparison → reporting.",
      })
    );
    if (guardrails.supportedClaims && guardrails.supportedClaims.length > 0) {
      const claimsList = createElement("div", { className: "insight-list" });
      for (const claim of guardrails.supportedClaims) {
        const item = createElement("div", { className: "insight-list-item" });
        item.append(createElement("strong", { text: "Claims:" }), document.createTextNode(` ${claim}`));
        claimsList.appendChild(item);
      }
      guardrailsCard.appendChild(claimsList);
    }
    if (guardrails.notThis && guardrails.notThis.length > 0) {
      guardrailsCard.appendChild(createElement("div", { className: "insight-divider" }));
      for (const item of guardrails.notThis) {
        guardrailsCard.appendChild(createElement("div", { className: "insight-list-item", text: item }));
      }
    }
    fragment.appendChild(guardrailsCard);

    els.studyInsightsContent.appendChild(fragment);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function buildInsightsKey(data) {
    const site = data.site || data.url || "";
    const cmp = data.consentScan?.cmpDetected || "";
    const grade = data.score?.grade || "";
    const openPatterns = (data.consentScan?.darkPatterns?.detected || []).join("|");
    return [site, cmp, grade, openPatterns].join("::");
  }

  function scoreColor(score) {
    if (score >= 90) return "#22c55e";
    if (score >= 75) return "#84cc16";
    if (score >= 60) return "#eab308";
    if (score >= 40) return "#f97316";
    return "#ef4444";
  }

  function petStudyColor(value) {
    if (typeof value !== "number") return "#6b7280";
    if (value > 0) return "#22c55e";
    if (value > -10) return "#f59e0b";
    return "#ef4444";
  }

  function studyBadgeLabel(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
      return null;
    }
    const rounded = Math.round(value * 10) / 10;
    const sign = rounded > 0 ? "+" : "";
    return `${sign}${rounded.toFixed(1)}%`;
  }

  function slugify(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  function buildPetStudyTooltipText(pet) {
    const studyLabel = AECCS?.STUDY_METADATA?.label || "AECCS 1000-site combined study snapshot";
    if (pet.studyMetricLabel && pet.studySitesTested) {
      return `${studyLabel}: ${pet.name} averaged ${pet.studyMetricLabel} tracker reduction across ${pet.studySitesTested} tested sites. This is not a live measurement for the current page.`;
    }
    if (pet.studyLabel) {
      return `${studyLabel}: ${pet.studyLabel}. This is not a live measurement for the current page.`;
    }
    return `${studyLabel}: study-backed context only. This is not a live measurement for the current page.`;
  }

  function buildPetSubtitleText(studyMetadata) {
    const sampleSize = studyMetadata?.sampleSize || 1000;
    const successfulCrawls = studyMetadata?.successfulCrawls || 861;
    const snapshotDateLabel = studyMetadata?.snapshotDateLabel || "March 6, 2026";
    return `Guidance combines this page's live findings with the AECCS ${sampleSize}-site combined study (${successfulCrawls} successful crawls, ${snapshotDateLabel})`;
  }

  function formatPercent(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return "n/a";
    return `${Math.round(value * 1000) / 10}%`;
  }

  function signedMetric(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return "n/a";
    if (value > 0) return `+${value}`;
    return `${value}`;
  }

  function isTransparentBackgroundValue(value) {
    const normalized = String(value || "").trim().toLowerCase();
    if (!normalized) return true;
    return normalized === "transparent" ||
      normalized === "rgba(0, 0, 0, 0)" ||
      normalized === "rgba(0,0,0,0)" ||
      normalized.startsWith("rgba(0, 0, 0, 0) none") ||
      normalized.startsWith("rgba(0,0,0,0) none");
  }

  function resolveButtonBackground(button) {
    const background = String(button.background || "").trim();
    const bgColor = String(button.bgColor || "").trim();

    if (background && !isTransparentBackgroundValue(background)) {
      return background;
    }
    if (bgColor && !isTransparentBackgroundValue(bgColor)) {
      return bgColor;
    }
    return background || bgColor || "transparent";
  }

  function buildButtonPreview(label, button, metaSuffix = "") {
    const preview = createElement("div", { className: "btn-preview" });
    preview.appendChild(createElement("div", { className: "btn-preview-label", text: label }));

    if (!button) {
      preview.appendChild(createElement("div", { className: "btn-missing", text: "Missing" }));
      return preview;
    }

    const mock = createElement("div", { className: "btn-mock", text: button.text || "" });
    applyButtonMockStyles(mock, button);
    preview.append(
      mock,
      createElement(
        "div",
        {
          className: "btn-meta",
          text: `${button.width}x${button.height}px | ${button.fontSize}px | wt ${button.fontWeight}${metaSuffix}`,
        }
      )
    );
    return preview;
  }

  function applyButtonMockStyles(element, button) {
    element.style.background = resolveButtonBackground(button);
    element.style.color = button.color || "inherit";
    if (typeof button.fontSize === "number") {
      element.style.fontSize = `${button.fontSize}px`;
    }
    if (button.fontWeight !== undefined && button.fontWeight !== null) {
      element.style.fontWeight = String(button.fontWeight);
    }
    element.style.borderRadius = button.borderRadius || "4px";
    if (button.border) {
      element.style.border = button.border;
    }
    if (button.boxShadow && button.boxShadow !== "none") {
      element.style.boxShadow = button.boxShadow;
    }
  }

  function buildInsightCard(title) {
    const card = createElement("div", { className: "insight-card" });
    card.appendChild(createElement("div", { className: "insight-card-title", text: title }));
    return card;
  }

  function buildLabeledValueRow(className, label, value, valueTag = "span") {
    const row = createElement("div", { className });
    row.append(
      createElement("span", { text: label }),
      createElement(valueTag, { text: value })
    );
    return row;
  }

  function clearNode(node) {
    if (node) {
      node.replaceChildren();
    }
  }

  function createElement(tagName, options = {}) {
    const element = document.createElement(tagName);
    if (options.className) {
      element.className = options.className;
    }
    if (options.text !== undefined && options.text !== null) {
      element.textContent = String(options.text);
    }
    if (options.attrs) {
      for (const [name, value] of Object.entries(options.attrs)) {
        if (value !== undefined && value !== null) {
          element.setAttribute(name, String(value));
        }
      }
    }
    return element;
  }

  function appendParts(parent, content) {
    const parts = Array.isArray(content) ? content : [content];
    for (const part of parts) {
      if (part === null || part === undefined) continue;
      if (Array.isArray(part)) {
        appendParts(parent, part);
        continue;
      }
      if (part instanceof Node) {
        parent.appendChild(part);
        continue;
      }
      parent.appendChild(document.createTextNode(String(part)));
    }
  }

  // ── Start ─────────────────────────────────────────────────────────────────

  init();
})();
