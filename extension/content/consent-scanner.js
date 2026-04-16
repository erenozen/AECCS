/*
 * Consent Scanner — content script that scans the live DOM for:
 *   • CMP platform detection
 *   • Consent banner + accept/reject/settings buttons
 *   • Dark patterns (preselected checkboxes, asymmetric buttons, hidden reject,
 *     confusing language, forced action)
 *   • Transparency indicators (purpose keywords, vendor mentions, privacy link)
 *
 * Ported from:
 *   scraper/crawler.py        — banner selectors, CMP detection, button logic
 *   dark_patterns/detector.py — dark-pattern checks
 *   analysis/scoring.py       — transparency scoring data
 */

(() => {
  "use strict";

  const ROOT = typeof globalThis !== "undefined" ? globalThis : self;
  const SCANNER_INIT_ERROR_KEY = "_AECCSConsentScannerInitError";
  const SCANNER_INIT_STAGE_KEY = "_AECCSConsentScannerInitStage";

  // Guard against duplicate injection (scripting.executeScript re-runs the
  // file even if it was already loaded).  Without this check, each injection
  // would register an additional runtime.onMessage listener.
  if (ROOT.AECCSConsentScanner) {
    ROOT._AECCSConsentScannerLoaded = true;
    ROOT[SCANNER_INIT_STAGE_KEY] = "ready";
    ROOT[SCANNER_INIT_ERROR_KEY] = null;
    return;
  }

  // Older failed loads may have set the flag before initialization completed.
  // Clear the stale flag so reinjection can recover cleanly.
  if (ROOT._AECCSConsentScannerLoaded && !ROOT.AECCSConsentScanner) {
    delete ROOT._AECCSConsentScannerLoaded;
  }

  let scannerInitStage = "boot";
  function setInitStage(stage) {
    scannerInitStage = stage;
    ROOT[SCANNER_INIT_STAGE_KEY] = stage;
  }

  function failInit(err) {
    ROOT[SCANNER_INIT_ERROR_KEY] = err && err.message ? err.message : String(err);
    ROOT[SCANNER_INIT_STAGE_KEY] = scannerInitStage;
    delete ROOT._AECCSConsentScannerLoaded;
    delete ROOT.AECCSConsentScanner;
  }

  function requireRuntimeObject(runtime, key) {
    const value = runtime && runtime[key];
    if (!value || typeof value !== "object") {
      throw new Error(`AECCS runtime missing ${key}`);
    }
    return value;
  }

  function requireRuntimeArray(runtime, key) {
    const value = runtime && runtime[key];
    if (!Array.isArray(value)) {
      throw new Error(`AECCS runtime missing ${key}`);
    }
    return value;
  }

  try {
    setInitStage("runtime");

    const AECCS_RUNTIME = ROOT.AECCS;
    if (!AECCS_RUNTIME || typeof AECCS_RUNTIME !== "object") {
      throw new Error("AECCS runtime unavailable. Load lib/tracker-data.js before content/consent-scanner.js.");
    }

    const CONSENT_VOCABULARY = requireRuntimeObject(AECCS_RUNTIME, "CONSENT_VOCABULARY");
    const CMP_SIGNATURES = requireRuntimeObject(AECCS_RUNTIME, "CMP_SIGNATURES");
    const BANNER_SELECTORS = requireRuntimeArray(AECCS_RUNTIME, "BANNER_SELECTORS");
    const DISMISS_BUTTON_KEYWORDS = requireRuntimeArray(AECCS_RUNTIME, "DISMISS_BUTTON_KEYWORDS");
    const NECESSARY_KEYWORDS = requireRuntimeArray(AECCS_RUNTIME, "NECESSARY_KEYWORDS");
    const BANNER_TEXT_KEYWORDS_RAW = requireRuntimeArray(AECCS_RUNTIME, "BANNER_TEXT_KEYWORDS");
    const BANNER_TEXT_PHRASES_RAW = requireRuntimeArray(AECCS_RUNTIME, "BANNER_TEXT_PHRASES");
    const BANNER_ATTR_HINTS_RAW = requireRuntimeArray(AECCS_RUNTIME, "BANNER_ATTR_HINTS");
    const GUILT_TRIP_PHRASES_RAW = requireRuntimeArray(AECCS_RUNTIME, "GUILT_TRIP_PHRASES");
    const DOUBLE_NEGATIVE_PATTERNS = requireRuntimeArray(AECCS_RUNTIME, "DOUBLE_NEGATIVE_PATTERNS");
    const PURPOSE_KEYWORDS = requireRuntimeArray(AECCS_RUNTIME, "PURPOSE_KEYWORDS");
    const VENDOR_KEYWORDS = requireRuntimeArray(AECCS_RUNTIME, "VENDOR_KEYWORDS");
    const PRIVACY_LINK_KEYWORDS = requireRuntimeArray(AECCS_RUNTIME, "PRIVACY_LINK_KEYWORDS");

    const ACTIONABLE_SELECTOR = [
      "button",
      "a",
      "[role='button']",
      "input[type='submit']",
      "input[type='button']",
      "a.btn",
      "a[class*='btn']",
      "a[class*='button']",
    ].join(", ");
    const CANDIDATE_CONTAINER_SELECTOR = "div, section, aside, form, dialog";
    const MAX_ANCESTOR_DEPTH = 6;
    const DEFAULT_SCAN_ATTEMPTS = 4;
    const DEFAULT_SCAN_DELAY_MS = 160;
    const MAX_PRESENTATION_DESCENDANTS = 32;
    const INTERACTION_SESSION_TIMEOUT_MS = 120000;

    let interactionSession = null;
    let interactionWatcherCleanup = null;
    let interactionTimeoutId = null;

    // ── Helpers ───────────────────────────────────────────────────────────────

    function normalizeText(value) {
      return String(value || "")
        .replace(/[\u2018\u2019]/g, "'")
        .replace(/[\u201C\u201D]/g, "\"")
        .replace(/\s+/g, " ")
        .trim();
    }

    function normalizeForMatch(value) {
      return normalizeText(value)
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase();
    }

    function buildNormalizedMatcher(entries) {
      const exact = new Set((entries?.exact || []).map(normalizeForMatch).filter(Boolean));
      const contains = (entries?.contains || []).map(normalizeForMatch).filter(Boolean);
      return { exact, contains };
    }

    function matchesAction(text, matcher, { exactOnly = false } = {}) {
      if (!text || !matcher) return false;
      if (matcher.exact.has(text)) return true;
      if (exactOnly) return false;
      return matcher.contains.some(term => text.includes(term));
    }

    const ACCEPT_BUTTON_MATCHER = buildNormalizedMatcher(CONSENT_VOCABULARY.accept);
    const REJECT_BUTTON_MATCHER = buildNormalizedMatcher(CONSENT_VOCABULARY.reject);
    const SETTINGS_BUTTON_MATCHER = buildNormalizedMatcher(CONSENT_VOCABULARY.settings);
    const DISMISS_BUTTON_TEXTS = new Set(DISMISS_BUTTON_KEYWORDS.map(normalizeForMatch).filter(Boolean));
    const NECESSARY_LABEL_KEYWORDS = NECESSARY_KEYWORDS.map(normalizeForMatch).filter(Boolean);
    const BANNER_TEXT_KEYWORDS = BANNER_TEXT_KEYWORDS_RAW.map(normalizeForMatch).filter(Boolean);
    const BANNER_TEXT_PHRASES = BANNER_TEXT_PHRASES_RAW.map(normalizeForMatch).filter(Boolean);
    const BANNER_ATTR_HINTS = BANNER_ATTR_HINTS_RAW.map(normalizeForMatch).filter(Boolean);
    const GUILT_TRIP_PHRASES = GUILT_TRIP_PHRASES_RAW.map(normalizeForMatch).filter(Boolean);

  function parsePx(value) {
    if (!value) return 0;
    const n = parseFloat(value);
    return isNaN(n) ? 0 : n;
  }

  function parseRgb(str) {
    if (!str) return null;

    const rgba = str.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?/i);
    if (rgba) {
      return {
        rgb: [+rgba[1], +rgba[2], +rgba[3]],
        alpha: rgba[4] == null ? 1 : parseFloat(rgba[4]),
      };
    }

    const hex = str.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (!hex) return null;

    const raw = hex[1];
    if (raw.length === 3) {
      return {
        rgb: [
          parseInt(raw[0] + raw[0], 16),
          parseInt(raw[1] + raw[1], 16),
          parseInt(raw[2] + raw[2], 16),
        ],
        alpha: 1,
      };
    }

    return {
      rgb: [
        parseInt(raw.slice(0, 2), 16),
        parseInt(raw.slice(2, 4), 16),
        parseInt(raw.slice(4, 6), 16),
      ],
      alpha: 1,
    };
  }

  function luminance(rgb) {
    const [r, g, b] = rgb.map(c => {
      c = c / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function contrastRatio(fg, bg) {
    const l1 = luminance(fg) + 0.05;
    const l2 = luminance(bg) + 0.05;
    return l1 > l2 ? l1 / l2 : l2 / l1;
  }

  function parseFontWeight(val) {
    if (!val) return 400;
    if (val === "bold") return 700;
    if (val === "normal") return 400;
    const n = parseInt(val, 10);
    return isNaN(n) ? 400 : n;
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function isElementVisible(el) {
    if (!el || !el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;

    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }

    return true;
  }

  function isActionableElement(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    try {
      return el.matches(ACTIONABLE_SELECTOR);
    } catch (_) {
      return false;
    }
  }

  function getElementText(el) {
    if (!el) return "";
    return normalizeText(el.innerText || el.textContent || "");
  }

  function getElementLabel(el) {
    const options = [
      el && el.innerText,
      el && el.textContent,
      el && el.value,
      el && el.getAttribute && el.getAttribute("aria-label"),
      el && el.getAttribute && el.getAttribute("title"),
    ]
      .map(normalizeText)
      .filter(Boolean);

    if (options.length === 0) return "";

    options.sort((a, b) => b.length - a.length);
    return options[0];
  }

  function classifyButtonText(text) {
    const normalized = normalizeForMatch(text);
    if (!normalized) return "unknown";

    if (matchesAction(normalized, REJECT_BUTTON_MATCHER, { exactOnly: true })) return "reject";
    if (matchesAction(normalized, ACCEPT_BUTTON_MATCHER, { exactOnly: true })) return "accept";
    if (matchesAction(normalized, SETTINGS_BUTTON_MATCHER, { exactOnly: true })) return "settings";
    if (matchesAction(normalized, REJECT_BUTTON_MATCHER)) return "reject";
    if (matchesAction(normalized, ACCEPT_BUTTON_MATCHER)) return "accept";
    if (matchesAction(normalized, SETTINGS_BUTTON_MATCHER)) return "settings";
    return "unknown";
  }

  function classifyInteractionAction(text) {
    const normalized = normalizeForMatch(text);
    if (!normalized) return "unknown";
    if (DISMISS_BUTTON_TEXTS.has(normalized)) return "dismiss";

    const type = classifyButtonText(text);
    if (type === "reject") {
      if (NECESSARY_LABEL_KEYWORDS.some(term => normalized.includes(term))) {
        return "essential";
      }
      return "reject";
    }
    return type;
  }

  function describeElement(el) {
    if (!el) return null;
    const tag = (el.tagName || "div").toLowerCase();
    if (el.id) return `#${el.id}`;

    const className = normalizeText(el.className || "");
    if (className) {
      const firstClass = className.split(/\s+/)[0];
      if (firstClass) return `${tag}.${firstClass}`;
    }

    return tag;
  }

  function elementAttributeHaystack(el) {
    if (!el) return "";
    return normalizeForMatch([
      el.id || "",
      el.className || "",
      el.getAttribute && el.getAttribute("role"),
      el.getAttribute && el.getAttribute("aria-label"),
      el.getAttribute && el.getAttribute("data-testid"),
      el.getAttribute && el.getAttribute("data-test-id"),
    ].join(" "));
  }

  function hasBannerLikeText(text) {
    const normalized = normalizeForMatch(text);
    if (!normalized) return false;
    if (BANNER_TEXT_KEYWORDS.some(term => normalized.includes(term))) return true;
    if (BANNER_TEXT_PHRASES.some(phrase => normalized.includes(phrase))) return true;
    return false;
  }

  function hasBannerLikeAttributes(attrs) {
    const normalized = normalizeForMatch(attrs);
    if (!normalized) return false;
    return BANNER_ATTR_HINTS.some(hint => normalized.includes(hint));
  }

  function findDismissButton(root, { visibleOnly = false } = {}) {
    if (!root) return null;

    for (const el of collectActionableElements(root, { includeHidden: !visibleOnly })) {
      const text = normalizeForMatch(getElementLabel(el));
      if (!text || !DISMISS_BUTTON_TEXTS.has(text)) continue;
      if (visibleOnly && !isElementVisible(el)) continue;
      return {
        element: el,
        text: getElementLabel(el),
      };
    }

    return null;
  }

  function isStrongBannerSurface(el) {
    if (!el || !isElementVisible(el)) return false;

    const rect = el.getBoundingClientRect();
    const area = getRectArea(rect);
    if (area <= 0) return false;

    const style = getComputedStyle(el);
    const attrs = elementAttributeHaystack(el);
    const flags = getVisualStyleFlags(style);
    const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
    const areaRatio = area / viewportArea;

    const fixedLike = style.position === "fixed" || style.position === "sticky";
    const dialogLike = attrs.includes("dialog") || el.getAttribute("aria-modal") === "true";
    const edgeAnchored = rect.top < 160 || rect.bottom > (window.innerHeight - 160);
    const largeEnough = areaRatio >= 0.015 ||
      rect.height >= 90 ||
      (rect.width >= window.innerWidth * 0.4 && rect.height >= 56);

    return hasMeaningfulPaint(flags) && largeEnough && (fixedLike || dialogLike || edgeAnchored);
  }

  function isActiveBanner(bannerEl, buttonData) {
    if (!bannerEl || !isStrongBannerSurface(bannerEl)) return false;

    const hasVisibleConsentAction = Boolean(
      buttonData && (buttonData.hasAcceptButton || buttonData.hasRejectButton || buttonData.hasSettingsButton)
    );
    const visibleConsentActionCount = [
      Boolean(buttonData && buttonData.hasAcceptButton),
      Boolean(buttonData && buttonData.hasRejectButton),
      Boolean(buttonData && buttonData.hasSettingsButton),
    ].filter(Boolean).length;
    const dismissButton = findDismissButton(bannerEl, { visibleOnly: true });
    const hasBannerEvidence = hasBannerLikeText(getElementText(bannerEl)) ||
      hasBannerLikeAttributes(elementAttributeHaystack(bannerEl)) ||
      Boolean(dismissButton) ||
      visibleConsentActionCount >= 2;
    if (!hasBannerEvidence) return false;

    if (hasVisibleConsentAction) return true;

    return Boolean(dismissButton);
  }

  function collectActionableElements(root, { includeHidden = false } = {}) {
    if (!root || !root.querySelectorAll) return [];

    const seen = new Set();
    const elements = [];

    const maybeAdd = el => {
      if (!el || seen.has(el) || !isActionableElement(el)) return;
      if (!includeHidden && !isElementVisible(el)) return;
      seen.add(el);
      elements.push(el);
    };

    maybeAdd(root);

    for (const el of root.querySelectorAll(ACTIONABLE_SELECTOR)) {
      maybeAdd(el);
    }

    return elements;
  }

  function extractButtonRecords(root, { includeHidden = true } = {}) {
    const buttons = [];

    for (const el of collectActionableElements(root, { includeHidden })) {
      const text = getElementLabel(el);
      if (!text) continue;

      const type = classifyButtonText(text);
      if (type === "unknown") continue;

      buttons.push({
        element: el,
        text,
        type,
        visible: isElementVisible(el),
      });
    }

    return buttons;
  }

  function pickButton(buttons, type, { visibleOnly = false } = {}) {
    const matches = buttons.filter(btn => btn.type === type && (!visibleOnly || btn.visible));
    return matches[0] || null;
  }

  function summarizeButtons(root, { includeHidden = false } = {}) {
    const buttons = extractButtonRecords(root, { includeHidden });

    return {
      buttons,
      acceptCount: buttons.filter(btn => btn.type === "accept" && btn.visible).length,
      rejectCount: buttons.filter(btn => btn.type === "reject" && btn.visible).length,
      settingsCount: buttons.filter(btn => btn.type === "settings" && btn.visible).length,
    };
  }

  function isTransparentColor(value) {
    if (!value) return true;
    const parsed = parseRgb(value);
    if (!parsed) {
      const normalized = String(value).trim().toLowerCase();
      return normalized === "" || normalized === "transparent";
    }
    return parsed.alpha <= 0.05;
  }

  function hasVisibleBorder(style) {
    const widths = [
      parsePx(style.borderTopWidth),
      parsePx(style.borderRightWidth),
      parsePx(style.borderBottomWidth),
      parsePx(style.borderLeftWidth),
    ];
    const styles = [
      style.borderTopStyle,
      style.borderRightStyle,
      style.borderBottomStyle,
      style.borderLeftStyle,
    ].map(value => String(value || "").toLowerCase());

    return widths.some((width, index) => width > 0 && styles[index] !== "none");
  }

  function hasRoundedCorners(style) {
    return [
      style.borderTopLeftRadius,
      style.borderTopRightRadius,
      style.borderBottomRightRadius,
      style.borderBottomLeftRadius,
    ].some(value => parsePx(value) > 0);
  }

  function getVisualStyleFlags(style) {
    const backgroundImage = String(style.backgroundImage || "").toLowerCase();
    const hasBackgroundImage = backgroundImage !== "" && backgroundImage !== "none";
    const hasSolidBackground = !isTransparentColor(style.backgroundColor);
    const visibleBorder = hasVisibleBorder(style);
    const roundedCorners = hasRoundedCorners(style);
    const boxShadow = String(style.boxShadow || "").toLowerCase();
    const hasBoxShadow = boxShadow !== "" && boxShadow !== "none";

    return {
      hasBackgroundImage,
      hasSolidBackground,
      visibleBorder,
      roundedCorners,
      hasBoxShadow,
    };
  }

  function hasMeaningfulPaint(flags) {
    return flags.hasSolidBackground ||
      flags.hasBackgroundImage ||
      flags.visibleBorder ||
      flags.roundedCorners ||
      flags.hasBoxShadow;
  }

  function getRectArea(rect) {
    if (!rect) return 0;
    return Math.max(0, rect.width) * Math.max(0, rect.height);
  }

  function getIntersectionArea(a, b) {
    if (!a || !b) return 0;
    const left = Math.max(a.left, b.left);
    const right = Math.min(a.right, b.right);
    const top = Math.max(a.top, b.top);
    const bottom = Math.min(a.bottom, b.bottom);

    if (right <= left || bottom <= top) return 0;
    return (right - left) * (bottom - top);
  }

  function describeStyleSource(el, pseudo = null) {
    const base = describeElement(el) || "element";
    return pseudo ? `${base}${pseudo}` : base;
  }

  function textMatchesAction(candidateEl, actionLabel) {
    if (!candidateEl || !actionLabel) return false;
    const candidateLabel = normalizeForMatch(getElementLabel(candidateEl) || getElementText(candidateEl));
    if (!candidateLabel) return false;
    return candidateLabel.includes(actionLabel) || actionLabel.includes(candidateLabel);
  }

  function collectActionTextRects(actionEl, actionLabel) {
    if (!actionEl || !actionLabel) return [];

    const rects = [];
    const seen = new Set();

    const maybeAdd = el => {
      if (!el || seen.has(el) || !isElementVisible(el) || !textMatchesAction(el, actionLabel)) return;
      const rect = el.getBoundingClientRect();
      if (getRectArea(rect) === 0) return;
      seen.add(el);
      rects.push(rect);
    };

    maybeAdd(actionEl);

    if (actionEl.querySelectorAll) {
      for (const el of actionEl.querySelectorAll("*")) {
        maybeAdd(el);
      }
    }

    return rects;
  }

  function buildPresentationCandidate(element, pseudo = null) {
    if (!element || !isElementVisible(element)) return null;

    const rect = element.getBoundingClientRect();
    const area = getRectArea(rect);
    if (area <= 0) return null;

    const style = pseudo ? getComputedStyle(element, pseudo) : getComputedStyle(element);
    const flags = getVisualStyleFlags(style);

    if (pseudo) {
      const content = String(style.content || "").trim().toLowerCase();
      if (content === "none" && !hasMeaningfulPaint(flags)) {
        return null;
      }
    }

    return {
      element,
      pseudo,
      rect,
      area,
      style,
      flags,
      styleSource: describeStyleSource(element, pseudo),
    };
  }

  function scorePresentationCandidate(candidate, {
    actionEl,
    actionLabel,
    actionRect,
    actionArea,
    textRects,
  }) {
    if (!candidate) return Number.NEGATIVE_INFINITY;

    const { element, pseudo, rect, area, style, flags } = candidate;
    const areaRatio = area / Math.max(1, actionArea);
    const actionCoverage = getIntersectionArea(rect, actionRect) / Math.max(1, actionArea);
    const labelMatch = textMatchesAction(element, actionLabel);
    const paintedLike = hasMeaningfulPaint(flags);

    let bestTextOverlap = 0;
    for (const textRect of textRects) {
      const overlap = getIntersectionArea(rect, textRect) / Math.max(1, getRectArea(textRect));
      if (overlap > bestTextOverlap) {
        bestTextOverlap = overlap;
      }
    }

    let score = pseudo ? 1 : (element === actionEl ? 2 : 0);
    if (labelMatch) score += 4;
    if (paintedLike) score += 6;
    if (flags.hasSolidBackground) score += 4;
    if (flags.hasBackgroundImage) score += 4;
    if (flags.visibleBorder) score += 2;
    if (flags.roundedCorners) score += 2;
    if (flags.hasBoxShadow) score += 1;
    if (String(style.cursor || "").toLowerCase() === "pointer") score += 1;

    const fg = parseRgb(style.color);
    const bg = parseRgb(style.backgroundColor);
    if (fg && bg && bg.alpha > 0.05) {
      const cr = contrastRatio(fg.rgb, bg.rgb);
      if (cr >= 3.0) score += 1;
    }

    if (actionCoverage >= 0.6) score += 4;
    else if (actionCoverage >= 0.3) score += 2;

    if (bestTextOverlap >= 0.5) score += 4;
    else if (bestTextOverlap >= 0.15) score += 2;

    if (areaRatio >= 0.35 && areaRatio <= 1.25) score += 2;
    if (areaRatio >= 0.55 && areaRatio <= 1.05) score += 2;
    else if (areaRatio < 0.08) score -= 2;
    else if (areaRatio > 1.5) score -= 1;

    if (!paintedLike && !labelMatch) score -= 8;
    if (!labelMatch && bestTextOverlap === 0 && actionCoverage < 0.25) score -= 4;

    return score;
  }

  function resolvePresentationSource(actionEl) {
    if (!actionEl || !isElementVisible(actionEl)) return null;

    const actionLabel = normalizeForMatch(getElementLabel(actionEl) || getElementText(actionEl));
    const actionRect = actionEl.getBoundingClientRect();
    const actionArea = Math.max(1, getRectArea(actionRect));
    const textRects = collectActionTextRects(actionEl, actionLabel);
    const elements = [actionEl];

    if (actionEl.querySelectorAll) {
      const descendants = Array.from(actionEl.querySelectorAll("*")).slice(0, MAX_PRESENTATION_DESCENDANTS);
      for (const el of descendants) {
        if (isElementVisible(el)) {
          elements.push(el);
        }
      }
    }

    const candidates = [];
    for (const el of elements) {
      for (const pseudo of [null, "::before", "::after"]) {
        const candidate = buildPresentationCandidate(el, pseudo);
        if (candidate) {
          candidates.push(candidate);
        }
      }
    }

    let best = buildPresentationCandidate(actionEl);
    let bestScore = scorePresentationCandidate(best, {
      actionEl,
      actionLabel,
      actionRect,
      actionArea,
      textRects,
    });

    for (const candidate of candidates) {
      const score = scorePresentationCandidate(candidate, {
        actionEl,
        actionLabel,
        actionRect,
        actionArea,
        textRects,
      });
      if (score > bestScore) {
        best = candidate;
        bestScore = score;
      }
    }

    return best;
  }

  function buildButtonPreview(buttonEl, clicksRequired) {
    if (!buttonEl) return null;

    const presentation = resolvePresentationSource(buttonEl) || buildPresentationCandidate(buttonEl);
    const style = presentation ? presentation.style : getComputedStyle(buttonEl);
    const rect = presentation ? presentation.rect : buttonEl.getBoundingClientRect();
    const flags = presentation ? presentation.flags : getVisualStyleFlags(style);

    return {
      text: getElementLabel(buttonEl),
      width: Math.round(rect.width || parsePx(style.width)),
      height: Math.round(rect.height || parsePx(style.height)),
      fontSize: Math.round(parsePx(style.fontSize)),
      fontWeight: parseFontWeight(style.fontWeight),
      background: style.background,
      bgColor: style.backgroundColor,
      color: style.color,
      border: style.border,
      borderRadius: style.borderRadius,
      boxShadow: style.boxShadow,
      clicksRequired: typeof clicksRequired === "number" ? clicksRequired : null,
      styleSource: presentation ? presentation.styleSource : describeElement(buttonEl),
      plainLinkLike: !hasMeaningfulPaint(flags),
    };
  }

  // ── CMP Detection ────────────────────────────────────────────────────────

  function detectCMP() {
    // Collect script src values — lightweight and avoids reading large DOM HTML.
    const scripts = document.querySelectorAll("script[src]");
    const scriptSrcs = Array.from(scripts).map(s => s.src.toLowerCase());

    // Check element IDs, class names, and data attributes for CMP signatures
    // (e.g. #onetrust-consent-sdk, .didomi-popup).  This is much cheaper than
    // reading innerHTML of the entire body.
    const idAndClassTokens = [];
    const selectorTargets = document.querySelectorAll("[id], [class]");
    for (const el of selectorTargets) {
      if (el.id) idAndClassTokens.push(el.id.toLowerCase());
      if (el.className && typeof el.className === "string") {
        idAndClassTokens.push(el.className.toLowerCase());
      }
      // Some CMPs attach data- attributes (e.g. data-cmp-vendor)
      for (const attr of el.attributes) {
        if (attr.name.startsWith("data-")) {
          idAndClassTokens.push(attr.value.toLowerCase());
        }
      }
    }

    const searchText = scriptSrcs.join(" ") + " " + idAndClassTokens.join(" ");

    for (const [cmpName, signatures] of Object.entries(CMP_SIGNATURES)) {
      for (const sig of signatures) {
        if (searchText.includes(sig.toLowerCase())) {
          return cmpName;
        }
      }
    }
    return null;
  }

  // ── Banner Detection ─────────────────────────────────────────────────────

  function collectBaseBannerCandidates() {
    const candidates = new Set();

    const maybeAdd = el => {
      if (!el || candidates.has(el) || !isElementVisible(el)) return;
      if (el === document.body || el === document.documentElement) return;
      candidates.add(el);
    };

    for (const selector of BANNER_SELECTORS) {
      try {
        const elements = document.querySelectorAll(selector);
        for (const el of elements) {
          const text = getElementText(el);
          const attrs = elementAttributeHaystack(el);
          if (hasBannerLikeText(text) || hasBannerLikeAttributes(attrs)) {
            maybeAdd(el);
          }
        }
      } catch (_) {
        // Invalid selector, skip
      }
    }

    for (const el of document.querySelectorAll(CANDIDATE_CONTAINER_SELECTOR)) {
      if (!isElementVisible(el)) continue;

      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const attrs = elementAttributeHaystack(el);
      const text = getElementText(el);
      const summary = summarizeButtons(el, { includeHidden: false });

      const fixedLike = style.position === "fixed" || style.position === "sticky";
      const dialogLike = attrs.includes("dialog") || el.getAttribute("aria-modal") === "true";
      const edgeAnchored = rect.top < 160 || rect.bottom > (window.innerHeight - 160);
      const actionable = summary.acceptCount > 0 || summary.rejectCount > 0 || summary.settingsCount > 0;

      if ((fixedLike || dialogLike || edgeAnchored) && (hasBannerLikeText(text) || hasBannerLikeAttributes(attrs) || actionable)) {
        maybeAdd(el);
      }
    }

    const actionButtons = collectActionableElements(document, { includeHidden: false });
    for (const button of actionButtons) {
      const type = classifyButtonText(getElementLabel(button));
      if (type === "unknown") continue;

      let current = button.parentElement;
      let depth = 0;
      while (current && depth < MAX_ANCESTOR_DEPTH) {
        maybeAdd(current);
        current = current.parentElement;
        depth += 1;
      }
    }

    return Array.from(candidates);
  }

  function scoreBannerCandidate(el) {
    if (!el || !isElementVisible(el)) return Number.NEGATIVE_INFINITY;

    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const text = getElementText(el);
    const matchText = normalizeForMatch(text);
    const attrs = elementAttributeHaystack(el);
    const summary = summarizeButtons(el, { includeHidden: false });

    let score = 0;

    if (hasBannerLikeText(text)) score += 5;
    if (BANNER_TEXT_KEYWORDS.some(term => matchText.includes(term))) score += 3;
    if (hasBannerLikeAttributes(attrs)) score += 3;

    if (summary.acceptCount > 0) score += 7;
    if (summary.rejectCount > 0) score += 7;
    if (summary.settingsCount > 0) score += 4;

    if (style.position === "fixed" || style.position === "sticky") score += 4;
    if (attrs.includes("dialog") || el.getAttribute("aria-modal") === "true") score += 3;

    const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
    const areaRatio = (rect.width * rect.height) / viewportArea;
    if (areaRatio >= 0.03 && areaRatio <= 0.95) score += 2;
    if (areaRatio > 0.95) score -= 4;
    if (rect.top < 140 || rect.bottom > (window.innerHeight - 140)) score += 2;

    if (text.length > 80) score += 1;
    if (text.length > 4000) score -= 3;

    if (el.querySelector("a[href*='privacy'], a[href*='cookie']")) score += 1;

    return score;
  }

  function findBanner() {
    const bases = collectBaseBannerCandidates();
    if (bases.length === 0) return null;

    let best = null;
    let bestScore = Number.NEGATIVE_INFINITY;

    for (const base of bases) {
      let current = base;
      let depth = 0;

      while (current && current !== document.body && current !== document.documentElement && depth < MAX_ANCESTOR_DEPTH) {
        const score = scoreBannerCandidate(current);
        if (score > bestScore) {
          bestScore = score;
          best = current;
        }
        current = current.parentElement;
        depth += 1;
      }
    }

    if (!best || bestScore < 6) return null;

    return {
      element: best,
      selector: describeElement(best),
      score: bestScore,
    };
  }

  // ── Button Detection ─────────────────────────────────────────────────────

  function findButtons(bannerEl) {
    const result = {
      acceptButton: null,
      rejectButton: null,
      hiddenRejectButton: null,
      settingsButton: null,
      acceptText: null,
      rejectText: null,
      settingsText: null,
      hasAcceptButton: false,
      hasRejectButton: false,
      hasSettingsButton: false,
      acceptClicksRequired: 999,
      rejectClicksRequired: 999,
      buttons: [],
    };

    if (!bannerEl) return result;

    const buttons = extractButtonRecords(bannerEl, { includeHidden: true });
    result.buttons = buttons;

    const acceptVisible = pickButton(buttons, "accept", { visibleOnly: true });
    const acceptAny = acceptVisible || pickButton(buttons, "accept");
    const rejectVisible = pickButton(buttons, "reject", { visibleOnly: true });
    const rejectAny = rejectVisible || pickButton(buttons, "reject");
    const settingsVisible = pickButton(buttons, "settings", { visibleOnly: true });
    const settingsAny = settingsVisible || pickButton(buttons, "settings");

    if (acceptAny) {
      result.acceptText = acceptAny.text;
    }
    if (acceptVisible) {
      result.acceptButton = acceptVisible.element;
      result.hasAcceptButton = true;
      result.acceptClicksRequired = 1;
    }

    if (rejectVisible) {
      result.rejectButton = rejectVisible.element;
      result.rejectText = rejectVisible.text;
      result.hasRejectButton = true;
      result.rejectClicksRequired = 1;
    }

    if (rejectAny && !rejectVisible) {
      result.hiddenRejectButton = rejectAny.element;
      result.rejectText = rejectAny.text;
    }

    if (settingsAny) {
      result.settingsText = settingsAny.text;
    }
    if (settingsVisible) {
      result.settingsButton = settingsVisible.element;
      result.hasSettingsButton = true;
      if (result.rejectClicksRequired === 999) {
        result.rejectClicksRequired = 2;
      }
    }

    return result;
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

  function clearInteractionTimeout() {
    if (interactionTimeoutId) {
      clearTimeout(interactionTimeoutId);
      interactionTimeoutId = null;
    }
  }

  function stopInteractionWatcher(reason = null) {
    clearInteractionTimeout();
    if (interactionWatcherCleanup) {
      interactionWatcherCleanup();
      interactionWatcherCleanup = null;
    }
    if (interactionSession) {
      interactionSession.watching = false;
      interactionSession.stopReason = reason || interactionSession.stopReason || null;
      interactionSession.updatedAt = new Date().toISOString();
      interactionSession.rootElement = null;
    }
  }

  function clearInteractionAuditSession() {
    stopInteractionWatcher("cleared");
    interactionSession = null;
    return null;
  }

  function getInteractionAuditSession() {
    if (!interactionSession) return null;

    return cloneForTransport({
      status: interactionSession.status,
      watching: Boolean(interactionSession.watching),
      action: interactionSession.action || null,
      baseline: interactionSession.baseline || null,
      current: interactionSession.current || null,
      delta: interactionSession.delta || null,
      honesty: interactionSession.honesty || { verdict: "unknown", findings: [] },
      frameId: interactionSession.frameId ?? null,
      armedAt: interactionSession.armedAt || null,
      observedAt: interactionSession.observedAt || null,
      updatedAt: interactionSession.updatedAt || null,
      stopReason: interactionSession.stopReason || null,
    });
  }

  function scheduleInteractionTimeout() {
    clearInteractionTimeout();
    if (!interactionSession || !interactionSession.watching) return;

    interactionTimeoutId = setTimeout(() => {
      if (!interactionSession) return;
      if (!interactionSession.action) {
        clearInteractionAuditSession();
        return;
      }
      stopInteractionWatcher("timeout");
    }, interactionSession.timeoutMs || INTERACTION_SESSION_TIMEOUT_MS);
  }

  function refreshTrackedBannerRoot() {
    if (!interactionSession) return null;

    const bannerMatch = findBanner();
    if (bannerMatch?.element) {
      interactionSession.rootElement = bannerMatch.element;
      interactionSession.bannerSelector = bannerMatch.selector;
      return bannerMatch.element;
    }

    return interactionSession.rootElement || null;
  }

  function isWithinTrackedConsentFlow(actionable) {
    if (!interactionSession || !actionable) return false;

    const rootElement = interactionSession.rootElement;
    if (rootElement && rootElement.contains(actionable)) {
      return true;
    }

    const refreshedRoot = refreshTrackedBannerRoot();
    if (refreshedRoot && refreshedRoot.contains(actionable)) {
      return true;
    }

    let current = actionable.parentElement;
    let depth = 0;
    while (current && depth < MAX_ANCESTOR_DEPTH) {
      if (
        isStrongBannerSurface(current) &&
        (hasBannerLikeText(getElementText(current)) || hasBannerLikeAttributes(elementAttributeHaystack(current)))
      ) {
        interactionSession.rootElement = current;
        interactionSession.bannerSelector = describeElement(current);
        return true;
      }
      current = current.parentElement;
      depth += 1;
    }

    return false;
  }

  async function notifyBackgroundOfObservedInteraction() {
    if (
      !interactionSession ||
      interactionSession.notified ||
      typeof browser === "undefined" ||
      !browser.runtime ||
      typeof browser.runtime.sendMessage !== "function"
    ) {
      return;
    }

    interactionSession.notified = true;

    try {
      await browser.runtime.sendMessage({
        action: "consentInteractionObserved",
        session: getInteractionAuditSession(),
      });
    } catch (_) {
      interactionSession.notified = false;
    }
  }

  function observeFinalInteractionAction(actionEl, type) {
    if (!interactionSession || !actionEl || !type || type === "unknown" || type === "settings") {
      return;
    }

    const timestamp = new Date().toISOString();
    interactionSession.status = "observed";
    interactionSession.action = {
      type,
      text: getElementLabel(actionEl) || null,
      observed: true,
      observedAt: timestamp,
    };
    interactionSession.observedAt = timestamp;
    interactionSession.updatedAt = timestamp;
    interactionSession.honesty = { verdict: "unknown", findings: [] };
    stopInteractionWatcher("final_action_observed");
    void notifyBackgroundOfObservedInteraction();
  }

  function armInteractionAuditSession(options = {}) {
    if (interactionSession && interactionSession.watching && !interactionSession.action) {
      return getInteractionAuditSession();
    }

    const bannerMatch = findBanner();
    const bannerEl = bannerMatch ? bannerMatch.element : null;
    const buttonData = findButtons(bannerEl);
    if (!isActiveBanner(bannerEl, buttonData)) {
      return getInteractionAuditSession();
    }

    clearInteractionAuditSession();

    interactionSession = {
      status: "armed",
      watching: true,
      action: null,
      baseline: cloneForTransport(options.baseline || null),
      current: null,
      delta: null,
      honesty: { verdict: "unknown", findings: [] },
      frameId: options.frameId ?? null,
      armedAt: new Date().toISOString(),
      observedAt: null,
      updatedAt: new Date().toISOString(),
      timeoutMs: Number(options.inactivityMs) > 0 ? Number(options.inactivityMs) : INTERACTION_SESSION_TIMEOUT_MS,
      rootElement: bannerEl,
      bannerSelector: bannerMatch?.selector || null,
      stopReason: null,
      notified: false,
    };

    const onClick = event => {
      if (!interactionSession || interactionSession.status === "completed") return;

      const actionable = event.target && event.target.closest ? event.target.closest(ACTIONABLE_SELECTOR) : null;
      if (!actionable || !isWithinTrackedConsentFlow(actionable)) return;

      const actionType = classifyInteractionAction(getElementLabel(actionable));
      if (actionType === "unknown") return;

      interactionSession.updatedAt = new Date().toISOString();
      scheduleInteractionTimeout();

      if (actionType === "settings") {
        refreshTrackedBannerRoot();
        return;
      }

      observeFinalInteractionAction(actionable, actionType);
    };

    const onPageHide = () => {
      clearInteractionAuditSession();
    };

    document.addEventListener("click", onClick, true);
    window.addEventListener("pagehide", onPageHide, true);

    interactionWatcherCleanup = () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("pagehide", onPageHide, true);
    };

    scheduleInteractionTimeout();
    return getInteractionAuditSession();
  }

  function storeInteractionOutcome(outcome) {
    const now = new Date().toISOString();
    if (!interactionSession) {
      interactionSession = {
        status: "completed",
        watching: false,
        action: cloneForTransport(outcome?.action || null),
        baseline: cloneForTransport(outcome?.baseline || null),
        current: cloneForTransport(outcome?.current || null),
        delta: cloneForTransport(outcome?.delta || null),
        honesty: cloneForTransport(outcome?.honesty || { verdict: "unknown", findings: [] }),
        frameId: outcome?.frameId ?? null,
        armedAt: null,
        observedAt: outcome?.action?.observedAt || null,
        updatedAt: now,
        timeoutMs: INTERACTION_SESSION_TIMEOUT_MS,
        rootElement: null,
        bannerSelector: null,
        stopReason: "stored_outcome",
        notified: true,
      };
      return getInteractionAuditSession();
    }

    interactionSession.status = outcome?.status || "completed";
    interactionSession.watching = false;
    interactionSession.action = cloneForTransport(outcome?.action || interactionSession.action || null);
    interactionSession.baseline = cloneForTransport(outcome?.baseline || interactionSession.baseline || null);
    interactionSession.current = cloneForTransport(outcome?.current || null);
    interactionSession.delta = cloneForTransport(outcome?.delta || null);
    interactionSession.honesty = cloneForTransport(outcome?.honesty || { verdict: "unknown", findings: [] });
    interactionSession.updatedAt = now;
    interactionSession.stopReason = "stored_outcome";
    interactionSession.notified = true;
    stopInteractionWatcher("stored_outcome");
    return getInteractionAuditSession();
  }

  // ── Dark Pattern: Pre-selected Checkboxes ────────────────────────────────
  // Port of detector.py detect_preselected_checkboxes (lines 333-368)

  function detectPreselectedCheckboxes(bannerEl) {
    const result = { detected: false, checkboxCount: 0, preselectedCount: 0 };
    if (!bannerEl) return result;

    const checkboxes = bannerEl.querySelectorAll('input[type="checkbox"]');
    result.checkboxCount = checkboxes.length;

    let preselected = 0;
    for (const cb of checkboxes) {
      if (!cb.checked) continue;

      let labelText = "";
      if (cb.id) {
        const label = bannerEl.querySelector(`label[for="${CSS.escape(cb.id)}"]`);
        if (label) labelText = label.textContent.trim().toLowerCase();
      }
      if (!labelText && cb.parentElement) {
        labelText = cb.parentElement.textContent.trim().toLowerCase();
      }

      const normalizedLabel = normalizeForMatch(labelText);
      const isNecessary = NECESSARY_LABEL_KEYWORDS.some(kw => normalizedLabel.includes(kw));
      if (!isNecessary) preselected++;
    }

    result.preselectedCount = preselected;
    if (preselected > 0) result.detected = true;
    return result;
  }

  // ── Dark Pattern: Asymmetric Buttons ─────────────────────────────────────
  // Port of detector.py detect_asymmetric_buttons (lines 158-246)

  function detectAsymmetricButtons(acceptPreview, rejectPreview) {
    const result = {
      detected: false,
      sizeRatio: null,
      fontSizeRatio: null,
      contrastIssue: false,
    };

    if (!acceptPreview || !rejectPreview) return result;

    const aW = acceptPreview.width || 0;
    const aH = acceptPreview.height || 0;
    const rW = rejectPreview.width || 0;
    const rH = rejectPreview.height || 0;

    const aFs = acceptPreview.fontSize || 0;
    const rFs = rejectPreview.fontSize || 0;

    const aFw = acceptPreview.fontWeight || 400;
    const rFw = rejectPreview.fontWeight || 400;

    const aArea = aW * aH;
    const rArea = rW * rH;
    const sizeRatio = aArea > 0 ? rArea / aArea : 1.0;
    result.sizeRatio = Math.round(sizeRatio * 1000) / 1000;

    const fsRatio = aFs > 0 ? rFs / aFs : 1.0;
    result.fontSizeRatio = Math.round(fsRatio * 1000) / 1000;

    const fwDiff = aFw - rFw;

    const rFg = parseRgb(rejectPreview.color);
    const rBg = parseRgb(rejectPreview.bgColor);
    if (rFg && rBg) {
      const cr = contrastRatio(rFg.rgb, rBg.rgb);
      if (cr < 3.0) result.contrastIssue = true;
    }

    if (sizeRatio < 0.7 || fsRatio < 0.85 || fwDiff > 200 || result.contrastIssue) {
      result.detected = true;
    }

    return result;
  }

  // ── Dark Pattern: Hidden Reject Button ───────────────────────────────────
  // Port of detector.py detect_hidden_reject (lines 249-307)

  function detectHiddenReject(rejectBtn) {
    const result = { detected: false, reason: null };
    if (!rejectBtn) return result;

    const style = getComputedStyle(rejectBtn);
    const reasons = [];

    if (style.display === "none") reasons.push("display:none");
    if (style.visibility === "hidden") reasons.push("visibility:hidden");

    const w = parsePx(style.width);
    const h = parsePx(style.height);
    if (w === 0 || h === 0) reasons.push("zero dimensions");

    if (style.opacity === "0") reasons.push("opacity:0");

    const hiddenClasses = ["hidden", "sr-only", "visually-hidden", "d-none", "invisible"];
    const classList = Array.from(rejectBtn.classList).map(c => c.toLowerCase());
    for (const hc of hiddenClasses) {
      if (classList.includes(hc)) reasons.push(`class:${hc}`);
    }

    const fg = parseRgb(style.color);
    const bg = parseRgb(style.backgroundColor);
    if (fg && bg && fg.rgb[0] === bg.rgb[0] && fg.rgb[1] === bg.rgb[1] && fg.rgb[2] === bg.rgb[2]) {
      reasons.push("text-blends-with-background");
    }

    if (reasons.length > 0) {
      result.detected = true;
      result.reason = reasons.join(", ");
    }
    return result;
  }

  // ── Dark Pattern: Missing Reject Option ──────────────────────────────────
  // Port of detector.py detect_missing_reject (lines 310-328)

  function detectMissingReject(bannerFound, buttonData) {
    const result = { detected: false, description: null };
    if (!bannerFound) return result;

    if (!buttonData.hasRejectButton) {
      result.detected = true;
      result.description = "No reject button in consent banner";
      return result;
    }

    if (buttonData.rejectClicksRequired === 999) {
      result.detected = true;
      result.description = "Reject path unreachable (999 clicks)";
    }

    return result;
  }

  // ── Dark Pattern: Multi-layer Rejection ──────────────────────────────────
  // Port of detector.py detect_multi_layer_rejection (lines 407-425)

  function detectMultiLayerRejection(bannerFound, acceptClicksRequired, rejectClicksRequired) {
    const result = {
      detected: false,
      acceptClicks: null,
      rejectClicks: null,
      clickRatio: null,
    };
    if (!bannerFound) return result;

    const acceptClicks = typeof acceptClicksRequired === "number" ? acceptClicksRequired : 999;
    const rejectClicks = typeof rejectClicksRequired === "number" ? rejectClicksRequired : 999;

    result.acceptClicks = acceptClicks;
    result.rejectClicks = rejectClicks;

    if (acceptClicks > 0 && rejectClicks > 0 && acceptClicks < 999) {
      result.clickRatio = Math.round((rejectClicks / acceptClicks) * 100) / 100;
    }

    if (rejectClicks > acceptClicks && acceptClicks < 999) {
      result.detected = true;
    }

    return result;
  }

  // ── Dark Pattern: Confusing Language ─────────────────────────────────────
  // Port of detector.py detect_confusing_language (lines 432-460)

  function detectConfusingLanguage(bannerEl) {
    const result = { detected: false, suspiciousPhrases: [] };
    if (!bannerEl) return result;

    const text = normalizeForMatch(bannerEl.innerText || bannerEl.textContent || "");
    const phrases = [];

    for (const phrase of GUILT_TRIP_PHRASES) {
      if (text.includes(phrase)) {
        phrases.push(`guilt-trip: '${phrase}'`);
      }
    }

    for (const pat of DOUBLE_NEGATIVE_PATTERNS) {
      const m = pat.exec(text);
      if (m) phrases.push(`double-negative: '${m[0]}'`);
    }

    const buttons = bannerEl.querySelectorAll("button, a, input");
    for (const btn of buttons) {
      const btnText = getElementLabel(btn);
      if (DISMISS_BUTTON_TEXTS.has(normalizeForMatch(btnText))) {
        phrases.push(`ambiguous-button: '${btnText}'`);
      }
    }

    result.suspiciousPhrases = phrases;
    if (phrases.length > 0) result.detected = true;
    return result;
  }

  // ── Dark Pattern: Forced Action / Cookie Wall ────────────────────────────
  // Port of detector.py detect_forced_action (lines 371-404)

  function detectForcedAction() {
    const result = { detected: false, isCookieWall: false };
    const wallIndicators = ["wall", "blocker", "overlay", "modal", "blocking"];

    const elements = document.querySelectorAll(CANDIDATE_CONTAINER_SELECTOR);
    for (const el of elements) {
      const classes = (el.className || "").toLowerCase();
      const elId = (el.id || "").toLowerCase();

      const hasIndicator = wallIndicators.some(w => classes.includes(w) || elId.includes(w));
      const csStyle = getComputedStyle(el);
      const hasFixed = csStyle.position === "fixed";
      const rect = el.getBoundingClientRect();
      const hasFull = rect.width >= window.innerWidth * 0.9 || rect.height >= window.innerHeight * 0.9;

      if (hasIndicator && (hasFixed || hasFull)) {
        result.detected = true;
        result.isCookieWall = true;
        return result;
      }

      if (classes.includes("blur") || classes.includes("backdrop")) {
        if (!classes.includes("no-blur") && hasFixed) {
          result.detected = true;
          result.isCookieWall = true;
          return result;
        }
      }
    }

    return result;
  }

  // ── Transparency Checks ──────────────────────────────────────────────────
  // Port of scoring.py _score_transparent_information (lines 202-248)

  function checkTransparency(bannerEl) {
    const result = {
      mentionsPurposes: false,
      mentionsVendors: false,
      hasPrivacyPolicyLink: false,
      clearLanguage: false,
    };
    if (!bannerEl) return result;

    const text = (bannerEl.innerText || bannerEl.textContent || "").toLowerCase();

    result.mentionsPurposes = PURPOSE_KEYWORDS.some(kw => text.includes(kw));
    result.mentionsVendors = VENDOR_KEYWORDS.some(kw => text.includes(kw));

    // Check for privacy policy links via DOM traversal rather than innerHTML.
    const links = bannerEl.querySelectorAll("a[href]");
    result.hasPrivacyPolicyLink = Array.from(links).some(a => {
      const href = (a.href || "").toLowerCase();
      const linkText = (a.textContent || "").toLowerCase();
      return PRIVACY_LINK_KEYWORDS.some(kw => href.includes(kw) || linkText.includes(kw));
    });

    if (text.length > 0) {
      const sentences = text.split(/[.!?]+/).filter(s => s.trim().length > 0);
      if (sentences.length > 0) {
        const avgWords = sentences.reduce((sum, s) => sum + s.trim().split(/\s+/).length, 0) / sentences.length;
        result.clearLanguage = avgWords < 30;
      }
    }

    return result;
  }

  // ── Accept vs Reject Button UX Comparison ────────────────────────────────

  function compareButtons(acceptPreview, rejectPreview, settingsPreview) {
    const result = {
      available: false,
      accept: null,
      reject: null,
      settings: null,
      rejectSource: "missing",
      issues: [],
    };

    if (!acceptPreview) return result;
    result.available = true;

    result.accept = acceptPreview;

    if (settingsPreview) {
      result.settings = settingsPreview;
    }

    if (rejectPreview) {
      result.reject = rejectPreview;
      result.rejectSource = "direct";
    } else if (settingsPreview) {
      result.reject = settingsPreview;
      result.rejectSource = "settings";
      const clicks = typeof settingsPreview.clicksRequired === "number" && settingsPreview.clicksRequired < 999
        ? ` (${settingsPreview.clicksRequired} clicks total)`
        : "";
      result.issues.push(`Reject requires opening settings/preferences first${clicks}`);
    } else {
      result.reject = null;
      result.issues.push("No reject button found — users cannot decline cookies");
      return result;
    }

    const aArea = result.accept.width * result.accept.height;
    const rArea = result.reject.width * result.reject.height;
    if (aArea > 0 && rArea > 0 && rArea / aArea < 0.7) {
      result.issues.push("Reject button is significantly smaller than accept button");
    }
    if (result.accept.fontSize > 0 && result.reject.fontSize / result.accept.fontSize < 0.85) {
      result.issues.push("Reject button uses smaller font than accept button");
    }
    if (result.accept.fontWeight - result.reject.fontWeight > 200) {
      result.issues.push("Accept button is bolder than reject button");
    }

    if (result.reject.plainLinkLike) {
      result.issues.push("Reject is styled as a plain link, not a button");
    }

    return result;
  }

  // ── Main scan function ───────────────────────────────────────────────────

  function scanPageOnce() {
    const cmpDetected = detectCMP();
    const candidateBannerMatch = findBanner();
    const candidateBannerEl = candidateBannerMatch ? candidateBannerMatch.element : null;
    const candidateButtonData = findButtons(candidateBannerEl);
    const bannerFound = isActiveBanner(candidateBannerEl, candidateButtonData);
    const bannerMatch = bannerFound ? candidateBannerMatch : null;
    const bannerEl = bannerFound ? candidateBannerEl : null;
    const buttonData = bannerFound ? candidateButtonData : findButtons(null);
    const {
      acceptButton,
      rejectButton,
      hiddenRejectButton,
      settingsButton,
      acceptText,
      rejectText,
      settingsText,
      hasAcceptButton,
      hasRejectButton,
      hasSettingsButton,
      acceptClicksRequired,
      rejectClicksRequired,
    } = buttonData;

    const acceptPreview = buildButtonPreview(acceptButton, acceptClicksRequired);
    const rejectPreview = buildButtonPreview(rejectButton, rejectClicksRequired);
    const settingsPreview = buildButtonPreview(settingsButton, rejectClicksRequired);

    const preselected = detectPreselectedCheckboxes(bannerEl);
    const asymmetric = detectAsymmetricButtons(acceptPreview, rejectPreview);
    const hiddenReject = detectHiddenReject(hiddenRejectButton || rejectButton);
    const missingReject = detectMissingReject(bannerFound, buttonData);
    const confusing = detectConfusingLanguage(bannerEl);
    const forcedAction = bannerFound ? detectForcedAction() : { detected: false, isCookieWall: false };
    const multiLayerRejection = detectMultiLayerRejection(
      bannerFound,
      acceptClicksRequired,
      rejectClicksRequired
    );

    const darkPatterns = [];
    if (bannerFound) {
      if (preselected.detected) darkPatterns.push("Pre-selected checkboxes");
      if (asymmetric.detected) darkPatterns.push("Asymmetric buttons");
      if (hiddenReject.detected) darkPatterns.push("Hidden reject button");
      if (missingReject.detected) darkPatterns.push("Missing reject option");
      if (forcedAction.detected) darkPatterns.push("Forced action / Cookie wall");
      if (multiLayerRejection.detected) darkPatterns.push("Multi-layer rejection");
      if (confusing.detected) darkPatterns.push("Confusing language");
    }

    const transparency = checkTransparency(bannerEl);
    const buttonComparison = compareButtons(acceptPreview, rejectPreview, settingsPreview);
    const bannerText = bannerEl
      ? (bannerEl.innerText || bannerEl.textContent || "").substring(0, 500)
      : "";

    return {
      cmpDetected,
      bannerFound,
      bannerSelector: bannerMatch ? bannerMatch.selector : null,
      hasAcceptButton,
      hasRejectButton,
      hasSettingsButton,
      acceptButtonText: acceptText,
      rejectButtonText: rejectText,
      settingsButtonText: settingsText,
      acceptClicksRequired,
      rejectClicksRequired,
      darkPatterns: {
        count: darkPatterns.length,
        detected: darkPatterns,
        preselectedCheckboxes: preselected,
        asymmetricButtons: asymmetric,
        hiddenReject: hiddenReject,
        missingReject: missingReject,
        confusingLanguage: confusing,
        forcedAction: forcedAction,
        multiLayerRejection: multiLayerRejection,
      },
      transparency,
      buttonComparison,
      bannerText,
    };
  }

  function scanResultQuality(result) {
    if (!result) return -1;

    let score = 0;
    if (result.bannerFound) score += 2;
    if (result.hasAcceptButton) score += 5;
    if (result.hasRejectButton) score += 5;
    if (result.hasSettingsButton) score += 3;
    if (result.acceptClicksRequired < 999) score += 1;
    if (result.rejectClicksRequired < 999) score += 1;
    if (result.bannerText) score += 1;
    return score;
  }

  async function scanPageWithRetries(options = {}) {
    const attempts = Math.max(1, options.attempts || DEFAULT_SCAN_ATTEMPTS);
    const delayMs = Math.max(0, options.delayMs == null ? DEFAULT_SCAN_DELAY_MS : options.delayMs);

    let best = null;

    for (let attempt = 0; attempt < attempts; attempt++) {
      const result = scanPageOnce();

      if (!best || scanResultQuality(result) >= scanResultQuality(best)) {
        best = result;
      }

      if (best.bannerFound && (best.hasAcceptButton || best.hasRejectButton || best.hasSettingsButton)) {
        return best;
      }

      if (attempt < attempts - 1) {
        await sleep(delayMs);
      }
    }

    return best || scanPageOnce();
  }

  // ── Runtime wiring ───────────────────────────────────────────────────────

    setInitStage("wiring");
    ROOT.AECCSConsentScanner = {
      scanPage: scanPageOnce,
      scanPageWithRetries,
      scoreResult: scanResultQuality,
      armInteractionAuditSession,
      getInteractionAuditSession,
      storeInteractionOutcome,
      clearInteractionAuditSession,
    };

    ROOT._AECCSConsentScannerLoaded = true;
    ROOT[SCANNER_INIT_STAGE_KEY] = "ready";
    ROOT[SCANNER_INIT_ERROR_KEY] = null;

    if (typeof browser !== "undefined" && browser.runtime && browser.runtime.onMessage) {
      browser.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg.action === "scanConsent") {
        scanPageWithRetries()
          .then(result => sendResponse(result))
          .catch(err => sendResponse({ error: err.message }));
        return true;
      }
      });
    }
  } catch (err) {
    failInit(err);
    throw err;
  }
})();
