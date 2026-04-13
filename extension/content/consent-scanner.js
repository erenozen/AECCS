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

  // ── Dark-pattern keyword lists (from detector.py lines 38-80) ────────────

  const GUILT_TRIP_PHRASES = [
    "keep the site free", "support our journalist", "help us improve",
    "you'll miss out", "you will miss out", "miss personalized",
    "enjoy a better experience", "support free journalism",
    "we need your support", "without your support",
    "fund our work", "keep this site running",
    "best experience", "optimal experience",
    "unterstützen sie uns", "helfen sie uns", "kostenlos halten",
    "bessere erfahrung", "optimale erfahrung",
  ];

  const DOUBLE_NEGATIVE_PATTERNS = [
    /don'?t\s+(not|reject|refuse|decline)/i,
    /nicht\s+(ablehnen|verweigern)/i,
    /ne\s+pas\s+(refuser|rejeter)/i,
    /I\s+do\s+not\s+want\s+to\s+not/i,
  ];

  const AMBIGUOUS_BUTTON_TEXTS = new Set([
    "ok", "okay", "continue", "got it", "i understand", "understood",
    "close", "dismiss", "later", "not now", "remind me later",
    "weiter", "verstanden", "schliessen", "schließen",
    "continuer", "compris", "j'ai compris", "fermer",
    "doorgaan", "begrepen", "sluiten",
  ]);

  const NECESSARY_KEYWORDS = [
    "necessary", "essential", "required", "strictly necessary",
    "erforderlich", "notwendig", "unbedingt erforderlich",
    "nécessaire", "strictement nécessaire",
    "noodzakelijk", "strikt noodzakelijk",
    "necesario", "estrictamente necesario",
    "necessario", "strettamente necessario",
    "gerekli", "zorunlu",
  ];

  // Port of scraper/crawler.py _SETTINGS_KEYWORDS
  const SETTINGS_KEYWORDS = [
    "settings",
    "preferences",
    "manage",
    "customize",
    "customise",
    "more options",
    "cookie settings",
    "cookie preferences",
    "einstellungen",
    "paramètres",
    "parametres",
    "gérer",
    "gerer",
    "instellingen",
    "opciones",
    "configurar",
    "impostazioni",
    "ayarlar",
  ];

  const CONSENT_TEXT_RE = /cookie|consent|gdpr|privacy|data protection|datenschutz/i;
  const ATTR_HINT_RE = /cookie|consent|gdpr|privacy|cmp|tcf|onetrust|didomi|trustarc|cookiebot/i;
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

  // ── Helpers ───────────────────────────────────────────────────────────────

  function normalizeText(value) {
    return String(value || "")
      .replace(/[\u2018\u2019]/g, "'")
      .replace(/[\u201C\u201D]/g, "\"")
      .replace(/\s+/g, " ")
      .trim();
  }

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
    const normalized = normalizeText(text).toLowerCase();
    if (!normalized) return "unknown";

    for (const kw of AECCS.CONSENT_BUTTON_KEYWORDS.accept) {
      if (kw.toLowerCase() === normalized) return "accept";
    }
    for (const kw of AECCS.CONSENT_BUTTON_KEYWORDS.reject) {
      if (kw.toLowerCase() === normalized) return "reject";
    }
    for (const kw of AECCS.CONSENT_BUTTON_KEYWORDS.reject) {
      if (normalized.includes(kw.toLowerCase())) return "reject";
    }
    for (const kw of AECCS.CONSENT_BUTTON_KEYWORDS.accept) {
      if (normalized.includes(kw.toLowerCase())) return "accept";
    }
    for (const kw of SETTINGS_KEYWORDS) {
      if (normalized.includes(kw)) return "settings";
    }
    return "unknown";
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
    return [
      el.id || "",
      el.className || "",
      el.getAttribute && el.getAttribute("role"),
      el.getAttribute && el.getAttribute("aria-label"),
      el.getAttribute && el.getAttribute("data-testid"),
      el.getAttribute && el.getAttribute("data-test-id"),
    ].join(" ").toLowerCase();
  }

  function hasConsentLikeText(text) {
    if (!text) return false;
    if (CONSENT_TEXT_RE.test(text)) return true;

    const lower = text.toLowerCase();
    const allKeywords = [
      ...AECCS.CONSENT_BUTTON_KEYWORDS.accept,
      ...AECCS.CONSENT_BUTTON_KEYWORDS.reject,
      ...SETTINGS_KEYWORDS,
    ];
    return allKeywords.some(kw => lower.includes(kw.toLowerCase()));
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

  // ── CMP Detection ────────────────────────────────────────────────────────

  function detectCMP() {
    const scripts = document.querySelectorAll("script[src]");
    const scriptSrcs = Array.from(scripts).map(s => s.src.toLowerCase());
    const bodySnippet = (document.body ? document.body.innerHTML.substring(0, 50000) : "").toLowerCase();
    const headHtml = (document.head ? document.head.innerHTML : "").toLowerCase();
    const searchText = headHtml + " " + bodySnippet + " " + scriptSrcs.join(" ");

    for (const [cmpName, signatures] of Object.entries(AECCS.CMP_SIGNATURES)) {
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

    for (const selector of AECCS.BANNER_SELECTORS) {
      try {
        const elements = document.querySelectorAll(selector);
        for (const el of elements) {
          const text = getElementText(el).toLowerCase();
          const attrs = elementAttributeHaystack(el);
          if (hasConsentLikeText(text) || ATTR_HINT_RE.test(attrs)) {
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
      const text = getElementText(el).toLowerCase();
      const summary = summarizeButtons(el, { includeHidden: false });

      const fixedLike = style.position === "fixed" || style.position === "sticky";
      const dialogLike = attrs.includes("dialog") || el.getAttribute("aria-modal") === "true";
      const edgeAnchored = rect.top < 160 || rect.bottom > (window.innerHeight - 160);
      const actionable = summary.acceptCount > 0 || summary.rejectCount > 0 || summary.settingsCount > 0;

      if ((fixedLike || dialogLike || edgeAnchored) && (hasConsentLikeText(text) || ATTR_HINT_RE.test(attrs) || actionable)) {
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
    const textLower = text.toLowerCase();
    const attrs = elementAttributeHaystack(el);
    const summary = summarizeButtons(el, { includeHidden: false });

    let score = 0;

    if (hasConsentLikeText(textLower)) score += 5;
    if (CONSENT_TEXT_RE.test(textLower)) score += 3;
    if (ATTR_HINT_RE.test(attrs)) score += 3;

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

      const isNecessary = NECESSARY_KEYWORDS.some(kw => labelText.includes(kw));
      if (!isNecessary) preselected++;
    }

    result.preselectedCount = preselected;
    if (preselected > 0) result.detected = true;
    return result;
  }

  // ── Dark Pattern: Asymmetric Buttons ─────────────────────────────────────
  // Port of detector.py detect_asymmetric_buttons (lines 158-246)

  function detectAsymmetricButtons(acceptBtn, rejectBtn) {
    const result = {
      detected: false,
      sizeRatio: null,
      fontSizeRatio: null,
      contrastIssue: false,
    };

    if (!acceptBtn || !rejectBtn) return result;

    const aStyle = getComputedStyle(acceptBtn);
    const rStyle = getComputedStyle(rejectBtn);

    const aW = parsePx(aStyle.width);
    const aH = parsePx(aStyle.height);
    const rW = parsePx(rStyle.width);
    const rH = parsePx(rStyle.height);

    const aFs = parsePx(aStyle.fontSize);
    const rFs = parsePx(rStyle.fontSize);

    const aFw = parseFontWeight(aStyle.fontWeight);
    const rFw = parseFontWeight(rStyle.fontWeight);

    const aArea = aW * aH;
    const rArea = rW * rH;
    const sizeRatio = aArea > 0 ? rArea / aArea : 1.0;
    result.sizeRatio = Math.round(sizeRatio * 1000) / 1000;

    const fsRatio = aFs > 0 ? rFs / aFs : 1.0;
    result.fontSizeRatio = Math.round(fsRatio * 1000) / 1000;

    const fwDiff = aFw - rFw;

    const rFg = parseRgb(rStyle.color);
    const rBg = parseRgb(rStyle.backgroundColor);
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

  // ── Dark Pattern: Confusing Language ─────────────────────────────────────
  // Port of detector.py detect_confusing_language (lines 432-460)

  function detectConfusingLanguage(bannerEl) {
    const result = { detected: false, suspiciousPhrases: [] };
    if (!bannerEl) return result;

    const text = (bannerEl.innerText || bannerEl.textContent || "").toLowerCase();
    const phrases = [];

    for (const phrase of GUILT_TRIP_PHRASES) {
      if (text.includes(phrase.toLowerCase())) {
        phrases.push(`guilt-trip: '${phrase}'`);
      }
    }

    for (const pat of DOUBLE_NEGATIVE_PATTERNS) {
      const m = pat.exec(text);
      if (m) phrases.push(`double-negative: '${m[0]}'`);
    }

    const buttons = bannerEl.querySelectorAll("button, a, input");
    for (const btn of buttons) {
      const btnText = getElementLabel(btn).toLowerCase();
      if (AMBIGUOUS_BUTTON_TEXTS.has(btnText)) {
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
    const html = bannerEl.innerHTML.toLowerCase();

    result.mentionsPurposes = AECCS.PURPOSE_KEYWORDS.some(kw => text.includes(kw));
    result.mentionsVendors = AECCS.VENDOR_KEYWORDS.some(kw => text.includes(kw));
    result.hasPrivacyPolicyLink = AECCS.PRIVACY_LINK_KEYWORDS.some(kw => html.includes(kw));

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

  function compareButtons(acceptBtn, rejectBtn, settingsBtn) {
    const result = {
      available: false,
      accept: null,
      reject: null,
      settings: null,
      issues: [],
    };

    if (!acceptBtn) return result;
    result.available = true;

    const aStyle = getComputedStyle(acceptBtn);
    result.accept = {
      text: getElementLabel(acceptBtn),
      width: Math.round(parsePx(aStyle.width)),
      height: Math.round(parsePx(aStyle.height)),
      fontSize: Math.round(parsePx(aStyle.fontSize)),
      fontWeight: parseFontWeight(aStyle.fontWeight),
      bgColor: aStyle.backgroundColor,
      color: aStyle.color,
      borderRadius: aStyle.borderRadius,
    };

    if (settingsBtn) {
      result.settings = {
        text: getElementLabel(settingsBtn),
      };
    }

    if (!rejectBtn) {
      result.reject = null;
      if (settingsBtn) {
        result.issues.push("Reject requires opening settings/preferences first");
      } else {
        result.issues.push("No reject button found — users cannot decline cookies");
      }
      return result;
    }

    const rStyle = getComputedStyle(rejectBtn);
    result.reject = {
      text: getElementLabel(rejectBtn),
      width: Math.round(parsePx(rStyle.width)),
      height: Math.round(parsePx(rStyle.height)),
      fontSize: Math.round(parsePx(rStyle.fontSize)),
      fontWeight: parseFontWeight(rStyle.fontWeight),
      bgColor: rStyle.backgroundColor,
      color: rStyle.color,
      borderRadius: rStyle.borderRadius,
    };

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

    const bgColor = (rStyle.backgroundColor || "").toLowerCase();
    if (bgColor === "transparent" || bgColor === "rgba(0, 0, 0, 0)") {
      result.issues.push("Reject is styled as a plain link, not a button");
    }

    return result;
  }

  // ── Main scan function ───────────────────────────────────────────────────

  function scanPageOnce() {
    const cmpDetected = detectCMP();
    const bannerMatch = findBanner();
    const bannerEl = bannerMatch ? bannerMatch.element : null;
    const bannerFound = bannerEl !== null;
    const buttonData = findButtons(bannerEl);
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

    const preselected = detectPreselectedCheckboxes(bannerEl);
    const asymmetric = detectAsymmetricButtons(acceptButton, rejectButton);
    const hiddenReject = detectHiddenReject(hiddenRejectButton || rejectButton);
    const confusing = detectConfusingLanguage(bannerEl);
    const forcedAction = detectForcedAction();

    const darkPatterns = [];
    if (preselected.detected) darkPatterns.push("Pre-selected checkboxes");
    if (asymmetric.detected) darkPatterns.push("Asymmetric buttons");
    if (hiddenReject.detected) darkPatterns.push("Hidden reject button");
    if (confusing.detected) darkPatterns.push("Confusing language");
    if (forcedAction.detected) darkPatterns.push("Forced action / Cookie wall");

    const transparency = checkTransparency(bannerEl);
    const buttonComparison = compareButtons(acceptButton, rejectButton, settingsButton);
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
        confusingLanguage: confusing,
        forcedAction: forcedAction,
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

  if (typeof globalThis !== "undefined") {
    globalThis.AECCSConsentScanner = {
      scanPage: scanPageOnce,
      scanPageWithRetries,
    };
  }

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
})();
