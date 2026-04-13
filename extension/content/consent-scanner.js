/*
 * Consent Scanner — content script that scans the live DOM for:
 *   • CMP platform detection
 *   • Consent banner + accept/reject buttons
 *   • Dark patterns (preselected checkboxes, asymmetric buttons, hidden reject,
 *     confusing language, forced action)
 *   • Transparency indicators (purpose keywords, vendor mentions, privacy link)
 *
 * Ported from:
 *   scraper/crawler.py        — banner selectors, CMP detection
 *   dark_patterns/detector.py — all dark-pattern checks
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

  // ── Helpers ───────────────────────────────────────────────────────────────

  function parsePx(value) {
    if (!value) return 0;
    const n = parseFloat(value);
    return isNaN(n) ? 0 : n;
  }

  function parseRgb(str) {
    if (!str) return null;
    const m = str.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    return m ? [+m[1], +m[2], +m[3]] : null;
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

  // ── CMP Detection ────────────────────────────────────────────────────────

  function detectCMP() {
    // Check script tags for CMP signatures
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

  function findBanner() {
    for (const selector of AECCS.BANNER_SELECTORS) {
      try {
        const elements = document.querySelectorAll(selector);
        for (const el of elements) {
          // Check visibility
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 && rect.height === 0) continue;
          const style = getComputedStyle(el);
          if (style.display === "none" || style.visibility === "hidden") continue;

          // Verify it contains consent-related text
          const text = (el.innerText || el.textContent || "").toLowerCase();
          const allKeywords = [
            ...AECCS.CONSENT_BUTTON_KEYWORDS.accept,
            ...AECCS.CONSENT_BUTTON_KEYWORDS.reject,
          ];
          const hasConsentText = allKeywords.some(kw => text.includes(kw.toLowerCase()));
          // Also check for generic cookie/consent words
          const hasGenericText = /cookie|consent|gdpr|privacy|data protection|datenschutz/i.test(text);

          if (hasConsentText || hasGenericText) {
            return el;
          }
        }
      } catch (_) {
        // Invalid selector, skip
      }
    }
    return null;
  }

  // ── Button Detection ─────────────────────────────────────────────────────

  function findButtons(bannerEl) {
    const result = {
      acceptButton: null,
      rejectButton: null,
      acceptText: null,
      rejectText: null,
    };

    if (!bannerEl) return result;

    const candidates = bannerEl.querySelectorAll('button, a, [role="button"], input[type="submit"], input[type="button"]');

    for (const btn of candidates) {
      const text = (btn.innerText || btn.textContent || btn.value || "").trim();
      const textLower = text.toLowerCase();

      if (!result.acceptButton) {
        const isAccept = AECCS.CONSENT_BUTTON_KEYWORDS.accept.some(
          kw => textLower === kw.toLowerCase() || textLower.includes(kw.toLowerCase())
        );
        if (isAccept) {
          result.acceptButton = btn;
          result.acceptText = text;
        }
      }

      if (!result.rejectButton) {
        const isReject = AECCS.CONSENT_BUTTON_KEYWORDS.reject.some(
          kw => textLower === kw.toLowerCase() || textLower.includes(kw.toLowerCase())
        );
        if (isReject) {
          result.rejectButton = btn;
          result.rejectText = text;
        }
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

      // Find label text
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

    // Size ratio
    const aArea = aW * aH;
    const rArea = rW * rH;
    const sizeRatio = aArea > 0 ? rArea / aArea : 1.0;
    result.sizeRatio = Math.round(sizeRatio * 1000) / 1000;

    // Font size ratio
    const fsRatio = aFs > 0 ? rFs / aFs : 1.0;
    result.fontSizeRatio = Math.round(fsRatio * 1000) / 1000;

    // Font weight diff
    const fwDiff = aFw - rFw;

    // Contrast check on reject button
    const rFg = parseRgb(rStyle.color);
    const rBg = parseRgb(rStyle.backgroundColor);
    if (rFg && rBg) {
      const cr = contrastRatio(rFg, rBg);
      if (cr < 3.0) result.contrastIssue = true;
    }

    // Thresholds from detector.py line 243
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

    // Check for hidden CSS classes
    const hiddenClasses = ["hidden", "sr-only", "visually-hidden", "d-none", "invisible"];
    const classList = Array.from(rejectBtn.classList).map(c => c.toLowerCase());
    for (const hc of hiddenClasses) {
      if (classList.includes(hc)) reasons.push(`class:${hc}`);
    }

    // Text blending with background
    const fg = parseRgb(style.color);
    const bg = parseRgb(style.backgroundColor);
    if (fg && bg && fg[0] === bg[0] && fg[1] === bg[1] && fg[2] === bg[2]) {
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

    // Guilt-tripping
    for (const phrase of GUILT_TRIP_PHRASES) {
      if (text.includes(phrase.toLowerCase())) {
        phrases.push(`guilt-trip: '${phrase}'`);
      }
    }

    // Double negatives
    for (const pat of DOUBLE_NEGATIVE_PATTERNS) {
      const m = pat.exec(text);
      if (m) phrases.push(`double-negative: '${m[0]}'`);
    }

    // Ambiguous button texts
    const buttons = bannerEl.querySelectorAll("button, a, input");
    for (const btn of buttons) {
      const btnText = (btn.innerText || btn.textContent || btn.value || "").trim().toLowerCase();
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

    const elements = document.querySelectorAll("div, section, aside");
    for (const el of elements) {
      const classes = (el.className || "").toLowerCase();
      const elId = (el.id || "").toLowerCase();
      const style = (el.getAttribute("style") || "").toLowerCase();

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

      // Blur/backdrop check
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

    // Purpose keywords
    result.mentionsPurposes = AECCS.PURPOSE_KEYWORDS.some(kw => text.includes(kw));

    // Vendor keywords
    result.mentionsVendors = AECCS.VENDOR_KEYWORDS.some(kw => text.includes(kw));

    // Privacy policy link
    result.hasPrivacyPolicyLink = AECCS.PRIVACY_LINK_KEYWORDS.some(kw => html.includes(kw));

    // Clear language (average sentence length < 30 words)
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
  // Unique AECCS feature: side-by-side visual comparison of accept/reject
  // button styling to surface consent UX asymmetry.

  function compareButtons(acceptBtn, rejectBtn) {
    const result = {
      available: false,
      accept: null,
      reject: null,
      issues: [],
    };

    if (!acceptBtn) return result;
    result.available = true;

    const aStyle = getComputedStyle(acceptBtn);
    result.accept = {
      text: (acceptBtn.innerText || acceptBtn.textContent || "").trim(),
      width: Math.round(parsePx(aStyle.width)),
      height: Math.round(parsePx(aStyle.height)),
      fontSize: Math.round(parsePx(aStyle.fontSize)),
      fontWeight: parseFontWeight(aStyle.fontWeight),
      bgColor: aStyle.backgroundColor,
      color: aStyle.color,
      borderRadius: aStyle.borderRadius,
    };

    if (!rejectBtn) {
      result.reject = null;
      result.issues.push("No reject button found — users cannot decline cookies");
      return result;
    }

    const rStyle = getComputedStyle(rejectBtn);
    result.reject = {
      text: (rejectBtn.innerText || rejectBtn.textContent || "").trim(),
      width: Math.round(parsePx(rStyle.width)),
      height: Math.round(parsePx(rStyle.height)),
      fontSize: Math.round(parsePx(rStyle.fontSize)),
      fontWeight: parseFontWeight(rStyle.fontWeight),
      bgColor: rStyle.backgroundColor,
      color: rStyle.color,
      borderRadius: rStyle.borderRadius,
    };

    // Detect specific UX issues
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

    // Check if reject has a transparent/no background (link-styled)
    const rBg = parseRgb(rStyle.backgroundColor);
    if (rBg && rBg[3] === 0 || rStyle.backgroundColor === "transparent" || rStyle.backgroundColor === "rgba(0, 0, 0, 0)") {
      result.issues.push("Reject is styled as a plain link, not a button");
    }

    return result;
  }

  // ── Main scan function ───────────────────────────────────────────────────

  function scanPage() {
    const cmpDetected = detectCMP();
    const bannerEl = findBanner();
    const bannerFound = bannerEl !== null;
    const { acceptButton, rejectButton, acceptText, rejectText } = findButtons(bannerEl);

    // Dark patterns
    const preselected = detectPreselectedCheckboxes(bannerEl);
    const asymmetric = detectAsymmetricButtons(acceptButton, rejectButton);
    const hiddenReject = detectHiddenReject(rejectButton);
    const confusing = detectConfusingLanguage(bannerEl);
    const forcedAction = detectForcedAction();

    // Count total dark patterns
    const darkPatterns = [];
    if (preselected.detected) darkPatterns.push("Pre-selected checkboxes");
    if (asymmetric.detected) darkPatterns.push("Asymmetric buttons");
    if (hiddenReject.detected) darkPatterns.push("Hidden reject button");
    if (confusing.detected) darkPatterns.push("Confusing language");
    if (forcedAction.detected) darkPatterns.push("Forced action / Cookie wall");

    // Transparency
    const transparency = checkTransparency(bannerEl);

    // Accept vs Reject UX comparison (unique to AECCS)
    const buttonComparison = compareButtons(acceptButton, rejectButton);

    // Banner text (truncated for payload size)
    const bannerText = bannerEl
      ? (bannerEl.innerText || bannerEl.textContent || "").substring(0, 500)
      : "";

    return {
      cmpDetected,
      bannerFound,
      hasAcceptButton: acceptButton !== null,
      hasRejectButton: rejectButton !== null,
      acceptButtonText: acceptText,
      rejectButtonText: rejectText,
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

  // ── Message listener (service worker requests a scan) ────────────────────

  browser.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.action === "scanConsent") {
      try {
        const result = scanPage();
        sendResponse(result);
      } catch (err) {
        sendResponse({ error: err.message });
      }
      return true; // keep channel open for async (Chrome compat)
    }
  });
})();
