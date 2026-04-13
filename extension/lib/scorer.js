/*
 * GDPR Compliance Scorer — port of analysis/scoring.py.
 *
 * Six criteria, weighted 0-100 each, producing an overall score + letter grade.
 *
 *   1. No pre-consent trackers       (0.25)
 *   2. Reject option available        (0.20)
 *   3. Equal accept/reject effort     (0.15)
 *   4. No dark patterns               (0.15)
 *   5. Post-reject compliance         (0.15)  — simplified for extension
 *   6. Transparent information        (0.10)
 */

const Scorer = (() => {
  "use strict";

  function _grade(score) {
    for (const { threshold, grade } of AECCS.GRADES) {
      if (score >= threshold) return grade;
    }
    return "F";
  }

  // ── Criterion 1: No pre-consent trackers (weight 0.25) ──────────────────
  // Port of scoring.py lines 91-105
  // In the extension context all cookies visible on load are "pre-consent".

  function _scorePreConsentTrackers(classifiedCookies) {
    const n = classifiedCookies.filter(c => c.is_tracker).length;
    let score, details;
    if (n === 0)       { score = 100; details = "No pre-consent trackers found"; }
    else if (n <= 2)   { score = 60;  details = `${n} pre-consent trackers found`; }
    else if (n <= 5)   { score = 30;  details = `${n} pre-consent trackers found`; }
    else if (n <= 10)  { score = 10;  details = `${n} pre-consent trackers found`; }
    else               { score = 0;   details = `${n} pre-consent trackers found`; }
    return { score, details };
  }

  // ── Criterion 2: Reject option available (weight 0.20) ──────────────────
  // Port of scoring.py lines 108-119

  function _scoreRejectOption(consentScan) {
    if (!consentScan || consentScan.error) {
      return { score: 0, details: "Consent scan unavailable" };
    }
    if (!consentScan.bannerFound) {
      return { score: 0, details: "No consent banner found" };
    }
    if (consentScan.hasRejectButton) {
      return { score: 100, details: "Direct reject button available" };
    }
    return { score: 0, details: "No reject option available" };
  }

  // ── Criterion 3: Equal accept/reject effort (weight 0.15) ───────────────
  // Port of scoring.py lines 122-139
  // Simplified: we compare button existence and visual prominence.

  function _scoreEqualEffort(consentScan) {
    if (!consentScan || consentScan.error) {
      return { score: 0, details: "Consent scan unavailable" };
    }
    if (!consentScan.hasAcceptButton && !consentScan.hasRejectButton) {
      return { score: 0, details: "No functional accept/reject buttons" };
    }
    if (!consentScan.hasRejectButton) {
      return { score: 0, details: "No reject option" };
    }
    if (!consentScan.hasAcceptButton) {
      return { score: 100, details: "Reject available, no accept button" };
    }
    // Both buttons exist — check for asymmetry dark pattern
    const asym = consentScan.darkPatterns?.asymmetricButtons;
    if (asym && asym.detected) {
      return { score: 50, details: "Buttons exist but are visually asymmetric" };
    }
    return { score: 100, details: "Both accept and reject buttons available" };
  }

  // ── Criterion 4: No dark patterns (weight 0.15) ─────────────────────────
  // Port of scoring.py lines 142-154

  function _scoreNoDarkPatterns(consentScan) {
    if (!consentScan || consentScan.error) {
      return { score: 0, details: "Consent scan unavailable" };
    }
    const count = consentScan.darkPatterns?.count || 0;
    const names = consentScan.darkPatterns?.detected || [];
    const namesStr = names.join(", ") || "none";

    if (count === 0) return { score: 100, details: "No dark patterns detected" };
    if (count === 1) return { score: 60,  details: `1 dark pattern: ${namesStr}` };
    if (count === 2) return { score: 30,  details: `2 dark patterns: ${namesStr}` };
    return { score: 0, details: `${count} dark patterns: ${namesStr}` };
  }

  // ── Criterion 5: Post-reject compliance (weight 0.15) ───────────────────
  // Simplified for extension: we cannot click reject and re-scan.
  // If reject button exists → 50 (benefit of the doubt).
  // If not → 0.

  function _scorePostRejectCompliance(consentScan) {
    if (!consentScan || consentScan.error) {
      return { score: 0, details: "Consent scan unavailable" };
    }
    if (!consentScan.bannerFound) {
      return { score: 0, details: "No consent banner found" };
    }
    if (consentScan.hasRejectButton) {
      return { score: 50, details: "Reject button available (cannot verify post-reject behavior in extension)" };
    }
    return { score: 0, details: "No reject option available" };
  }

  // ── Criterion 6: Transparent information (weight 0.10) ──────────────────
  // Port of scoring.py lines 202-248

  function _scoreTransparentInformation(consentScan) {
    if (!consentScan || consentScan.error || !consentScan.bannerFound) {
      return { score: 0, details: "No banner text available" };
    }

    const t = consentScan.transparency || {};
    let score = 0;
    const details = [];

    if (t.mentionsPurposes)      { score += 30; details.push("mentions purposes"); }
    if (t.mentionsVendors)       { score += 30; details.push("mentions vendors"); }
    if (t.hasPrivacyPolicyLink)  { score += 20; details.push("privacy policy link"); }
    if (t.clearLanguage)         { score += 20; details.push("clear language"); }

    return {
      score: Math.min(score, 100),
      details: details.length > 0 ? details.join("; ") : "No transparency indicators",
    };
  }

  // ── Public API ──────────────────────────────────────────────────────────

  function computeComplianceScore(classifiedCookies, consentScan) {
    const criteria = {
      no_pre_consent_trackers:    _scorePreConsentTrackers(classifiedCookies),
      reject_option_available:    _scoreRejectOption(consentScan),
      equal_accept_reject_effort: _scoreEqualEffort(consentScan),
      no_dark_patterns:           _scoreNoDarkPatterns(consentScan),
      post_reject_compliance:     _scorePostRejectCompliance(consentScan),
      transparent_information:    _scoreTransparentInformation(consentScan),
    };

    let overall = 0;
    for (const [key, { score }] of Object.entries(criteria)) {
      const weight = AECCS.COMPLIANCE_WEIGHTS[key] || 0;
      overall += score * weight;
    }

    overall = Math.round(overall * 10) / 10;

    return {
      overall_score: overall,
      grade: _grade(overall),
      criteria,
    };
  }

  return { computeComplianceScore };
})();

if (typeof globalThis !== "undefined") {
  globalThis.Scorer = Scorer;
}
