/*
 * GDPR Compliance Scorer — port of analysis/scoring.py.
 *
 * Six criteria, weighted 0-100 each, producing an overall score + letter grade.
 *
 *   1. No pre-consent trackers       (0.25)
 *   2. Reject option available        (0.20)
 *   3. Equal accept/reject effort     (0.15)
 *   4. No dark patterns               (0.15)
 *   5. Post-reject compliance         (0.15)
 *   6. Transparent information        (0.10)
 */

const Scorer = (() => {
  "use strict";

  const STATE_OUTCOME_WEIGHTS = AECCS.STATE_OUTCOME_WEIGHTS || {
    low_tracker_load: 0.45,
    low_third_party_load: 0.25,
    low_total_cookie_load: 0.15,
    claimed_action_honesty: 0.15,
  };

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
    if (consentScan.hasSettingsButton && consentScan.rejectClicksRequired < 999) {
      return {
        score: 50,
        details: `Reject available via ${consentScan.rejectClicksRequired} clicks (through settings)`,
      };
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
    const acceptClicks = typeof consentScan.acceptClicksRequired === "number"
      ? consentScan.acceptClicksRequired
      : (consentScan.hasAcceptButton ? 1 : 999);
    const rejectClicks = typeof consentScan.rejectClicksRequired === "number"
      ? consentScan.rejectClicksRequired
      : (consentScan.hasRejectButton ? 1 : 999);

    if (acceptClicks === 999 && rejectClicks === 999) {
      return { score: 0, details: "No functional accept/reject buttons" };
    }
    if (rejectClicks === 999) {
      return { score: 0, details: "No reject option" };
    }
    if (acceptClicks === 999) {
      return { score: 100, details: "Reject available, no accept button" };
    }

    const diff = rejectClicks - acceptClicks;
    if (diff <= 0) {
      return { score: 100, details: `Equal clicks: ${acceptClicks} vs ${rejectClicks}` };
    }
    if (diff === 1) {
      return { score: 50, details: `Reject requires 1 extra click (${acceptClicks} vs ${rejectClicks})` };
    }
    return { score: 20, details: `Reject requires ${diff} extra clicks (${acceptClicks} vs ${rejectClicks})` };
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
    if (count === 1) return { score: 60,  details: `1 dark pattern detected: ${namesStr}` };
    if (count === 2) return { score: 30,  details: `2 dark patterns detected: ${namesStr}` };
    return { score: 0, details: `${count} dark patterns detected: ${namesStr}` };
  }

  // ── Criterion 5: Post-reject compliance (weight 0.15) ───────────────────
  // The baseline banner audit does not auto-click banners, so this criterion
  // stays at zero unless a future verified post-reject dataset is explicitly attached.

  function _scoreVerifiedPostRejectCompliance(postRejectData) {
    if (!postRejectData || postRejectData.verified !== true) {
      return null;
    }

    if (postRejectData.rejectAvailable === false) {
      return { score: 0, details: "No reject option available" };
    }
    if (postRejectData.rejectSuccessful === false) {
      return { score: 0, details: "Reject was not successful" };
    }

    const rejectSignals = Number(postRejectData.rejectTrackerSignals || 0);
    const acceptSignals = Number(postRejectData.acceptTrackerSignals || 0);

    if (rejectSignals === 0) {
      return { score: 100, details: "No new trackers after rejection" };
    }
    if (acceptSignals > 0 && rejectSignals < acceptSignals) {
      return { score: 50, details: "Some new trackers after reject, but fewer than accept" };
    }

    return { score: 30, details: `${rejectSignals} new tracker signals after rejection` };
  }

  function _scorePostRejectCompliance(consentScan) {
    if (!consentScan || consentScan.error) {
      return { score: 0, details: "Consent scan unavailable" };
    }

    const verifiedScore = _scoreVerifiedPostRejectCompliance(consentScan.postRejectData);
    if (verifiedScore) {
      return verifiedScore;
    }

    return { score: 0, details: "No post-reject data available" };
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
      kind: "gdpr_compliance",
      label: "GDPR Compliance Score",
      overall_score: overall,
      grade: _grade(overall),
      criteria,
    };
  }

  function _scoreTrackerLoad(trackerCount) {
    const count = Number(trackerCount || 0);
    if (count === 0) return { score: 100, details: "No trackers detected" };
    if (count <= 2) return { score: 60, details: `${count} trackers detected` };
    if (count <= 5) return { score: 30, details: `${count} trackers detected` };
    if (count <= 10) return { score: 10, details: `${count} trackers detected` };
    return { score: 0, details: `${count} trackers detected` };
  }

  function _scoreThirdPartyLoad(thirdPartyCount) {
    const count = Number(thirdPartyCount || 0);
    if (count === 0) return { score: 100, details: "No third-party cookies detected" };
    if (count <= 2) return { score: 60, details: `${count} third-party cookies detected` };
    if (count <= 5) return { score: 30, details: `${count} third-party cookies detected` };
    if (count <= 10) return { score: 10, details: `${count} third-party cookies detected` };
    return { score: 0, details: `${count} third-party cookies detected` };
  }

  function _scoreTotalCookieLoad(totalCookies) {
    const count = Number(totalCookies || 0);
    if (count <= 2) return { score: 100, details: `${count} cookies currently loaded` };
    if (count <= 5) return { score: 80, details: `${count} cookies currently loaded` };
    if (count <= 10) return { score: 50, details: `${count} cookies currently loaded` };
    if (count <= 20) return { score: 20, details: `${count} cookies currently loaded` };
    return { score: 0, details: `${count} cookies currently loaded` };
  }

  function getInteractionActionType(interactionAudit) {
    return interactionAudit?.action?.type || "unknown";
  }

  function _scoreClaimedActionHonesty(siteSnapshot, interactionAudit) {
    const actionType = getInteractionActionType(interactionAudit);
    if (actionType === "accept") {
      return { score: null, details: "Not applicable for accept actions" };
    }
    if (actionType === "unknown" || actionType === "dismiss" || !interactionAudit?.action) {
      return { score: null, details: "No observed reject/essential action" };
    }

    const trackerCount = Number(siteSnapshot?.trackerCount || 0);
    const totalCookies = Number(siteSnapshot?.totalCookies || 0);
    const categoryCounts = siteSnapshot?.categoryCounts || {};
    const baseline = interactionAudit?.baseline || null;
    const delta = interactionAudit?.delta || null;
    const nonEssentialCount = (
      Number(categoryCounts.Analytics || 0) +
      Number(categoryCounts.Advertising || 0) +
      Number(categoryCounts.Social || 0) +
      Number(categoryCounts.Fingerprinting || 0)
    );

    if (trackerCount > 0) {
      return { score: 0, details: "Trackers remained after reject/essential action" };
    }

    if (delta && Array.isArray(delta.newTrackers) && delta.newTrackers.length > 0) {
      return { score: 0, details: "New trackers appeared after reject/essential action" };
    }

    if (
      baseline &&
      Number(siteSnapshot?.thirdPartyCount || 0) > Number(baseline.thirdPartyCount || 0)
    ) {
      return { score: 0, details: "Third-party cookie load increased after reject/essential action" };
    }

    if (nonEssentialCount === 0 && totalCookies === 0) {
      return { score: 100, details: "No non-essential cookies remained after reject/essential action" };
    }

    if (
      nonEssentialCount === 0 &&
      trackerCount === 0 &&
      (Number(categoryCounts.Functional || 0) > 0 || Number(categoryCounts.Unknown || 0) > 0)
    ) {
      return { score: 60, details: "Only functional or unknown cookies remained after reject/essential action" };
    }

    return { score: 20, details: "Non-essential cookies remained after reject/essential action" };
  }

  function computeStateOutcomeScore(siteSnapshot, interactionAudit = null) {
    const criteria = {
      low_tracker_load: _scoreTrackerLoad(siteSnapshot?.trackerCount || 0),
      low_third_party_load: _scoreThirdPartyLoad(siteSnapshot?.thirdPartyCount || 0),
      low_total_cookie_load: _scoreTotalCookieLoad(siteSnapshot?.totalCookies || 0),
      claimed_action_honesty: _scoreClaimedActionHonesty(siteSnapshot, interactionAudit),
    };

    let totalWeight = 0;
    let overall = 0;

    for (const [key, value] of Object.entries(criteria)) {
      if (typeof value.score !== "number") {
        continue;
      }
      const weight = STATE_OUTCOME_WEIGHTS[key] || 0;
      totalWeight += weight;
      overall += value.score * weight;
    }

    if (totalWeight > 0 && totalWeight !== 1) {
      overall = overall / totalWeight;
    }

    overall = Math.round(overall * 10) / 10;

    return {
      kind: "state_outcome",
      label: "Post-Interaction State Score",
      overall_score: overall,
      grade: _grade(overall),
      criteria,
    };
  }

  return { computeComplianceScore, computeStateOutcomeScore };
})();

if (typeof globalThis !== "undefined") {
  globalThis.Scorer = Scorer;
}
