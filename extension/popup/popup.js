/*
 * Popup script — requests analysis from the service worker and renders all
 * results including the AECCS-unique features: dark pattern detail cards with
 * GDPR article references, accept/reject UX comparison, PET recommendations,
 * CMP statistics, and government domain alerts.
 */

(() => {
  "use strict";

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
    Social:         "#a855f7",
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
  };

  // ── DOM refs ──────────────────────────────────────────────────────────────

  const $ = id => document.getElementById(id);

  const els = {
    loading:           $("loading"),
    errorState:        $("errorState"),
    errorMsg:          $("errorMsg"),
    results:           $("results"),
    siteDomain:        $("siteDomain"),
    govAlert:          $("govAlert"),
    gradeBadge:        $("gradeBadge"),
    gradeLetter:       $("gradeLetter"),
    scoreValue:        $("scoreValue"),
    cookieBar:         $("cookieBar"),
    cookieCounts:      $("cookieCounts"),
    cookieMeta:        $("cookieMeta"),
    trackerSection:    $("trackerSection"),
    trackerList:       $("trackerList"),
    consentInfo:       $("consentInfo"),
    cmpInfo:           $("cmpInfo"),
    buttonCompSection: $("buttonCompSection"),
    buttonComparison:  $("buttonComparison"),
    darkPatternSection: $("darkPatternSection"),
    darkPatternDetails: $("darkPatternDetails"),
    criteriaBody:      $("criteriaBody"),
    petSection:        $("petSection"),
    petList:           $("petList"),
  };

  // ── Init ──────────────────────────────────────────────────────────────────

  async function init() {
    try {
      const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
      if (!tab) return showError("No active tab found.");

      els.siteDomain.textContent = new URL(tab.url).hostname;

      const result = await browser.runtime.sendMessage({ action: "analyze", tabId: tab.id });

      if (result.error) return showError(result.error);

      render(result);
    } catch (err) {
      showError(err.message);
    }
  }

  function showError(msg) {
    els.loading.classList.add("hidden");
    els.errorState.classList.remove("hidden");
    els.errorMsg.textContent = msg;
  }

  // ── Render ────────────────────────────────────────────────────────────────

  function render(data) {
    els.loading.classList.add("hidden");
    els.results.classList.remove("hidden");

    // Government domain alert
    if (data.isGovDomain) {
      els.govAlert.classList.remove("hidden");
    }

    renderScore(data.score);
    renderCookies(data);
    renderTrackers(data.trackersByVendor);
    renderConsent(data.consentScan, data.cmpStats);
    renderButtonComparison(data.consentScan?.buttonComparison);
    renderDarkPatterns(data.consentScan?.darkPatterns);
    renderCriteria(data.score.criteria);
    renderPetRecommendations(data.petRecommendations);
  }

  // ── Score Badge ───────────────────────────────────────────────────────────

  function renderScore(score) {
    const color = GRADE_COLORS[score.grade] || GRADE_COLORS.F;
    els.gradeBadge.style.color = color;
    els.gradeBadge.style.borderColor = color;
    els.gradeLetter.textContent = score.grade;
    els.scoreValue.textContent = score.overall_score;
  }

  // ── Cookie Breakdown ──────────────────────────────────────────────────────

  function renderCookies(data) {
    const counts = data.categoryCounts || {};
    const total = data.totalCookies || 0;

    const order = ["Analytics", "Advertising", "Social", "Fingerprinting", "Functional", "Unknown"];
    els.cookieBar.innerHTML = "";

    if (total === 0) {
      els.cookieBar.innerHTML = '<div style="flex:1;background:var(--bg);border-radius:5px;"></div>';
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

    els.cookieCounts.innerHTML = "";
    for (const cat of order) {
      const n = counts[cat] || 0;
      if (n === 0) continue;
      const item = document.createElement("div");
      item.className = "cookie-count-item";
      item.innerHTML = `<span class="cookie-dot" style="background:${CATEGORY_COLORS[cat]}"></span>${cat}: ${n}`;
      els.cookieCounts.appendChild(item);
    }

    els.cookieMeta.textContent =
      `${total} cookies total | ${data.thirdPartyCount || 0} third-party | ${data.trackerCount || 0} trackers`;
  }

  // ── Tracker List ──────────────────────────────────────────────────────────

  function renderTrackers(trackersByVendor) {
    els.trackerList.innerHTML = "";
    const vendors = Object.keys(trackersByVendor || {});
    if (vendors.length === 0) {
      els.trackerList.innerHTML = '<div class="no-trackers">No trackers detected</div>';
      return;
    }
    for (const vendor of vendors) {
      const cookies = trackersByVendor[vendor];
      const group = document.createElement("div");
      group.className = "tracker-group";
      group.innerHTML =
        `<div class="tracker-vendor">${esc(vendor)} (${cookies.length})</div>` +
        `<div class="tracker-cookies">${cookies.map(esc).join(", ")}</div>`;
      els.trackerList.appendChild(group);
    }
  }

  // ── Consent Banner + CMP Stats ────────────────────────────────────────────

  function renderConsent(scan, cmpStats) {
    els.consentInfo.innerHTML = "";

    if (!scan || scan.error) {
      els.consentInfo.innerHTML = row("warn", "Consent scan unavailable");
      return;
    }

    if (scan.cmpDetected) {
      els.consentInfo.innerHTML += row("ok", `CMP detected: <b>${esc(scan.cmpDetected)}</b>`);
    } else {
      els.consentInfo.innerHTML += row("warn", "No known CMP detected");
    }

    if (!scan.bannerFound) {
      els.consentInfo.innerHTML += row("warn", "No consent banner found");
    } else {
      els.consentInfo.innerHTML += row("ok", "Consent banner found");
    }

    if (scan.hasAcceptButton) {
      els.consentInfo.innerHTML += row("ok", `Accept button: "${esc(scan.acceptButtonText)}"`);
    } else {
      els.consentInfo.innerHTML += row("warn", "No accept button found");
    }

    if (scan.hasRejectButton) {
      els.consentInfo.innerHTML += row("ok", `Reject button: "${esc(scan.rejectButtonText)}"`);
    } else if (scan.hasSettingsButton && scan.rejectClicksRequired < 999) {
      const clickLabel = scan.rejectClicksRequired === 2 ? "2 clicks" : `${scan.rejectClicksRequired} clicks`;
      const settingsLabel = scan.settingsButtonText || "Settings";
      els.consentInfo.innerHTML += row(
        "warn",
        `Reject available via settings: "${esc(settingsLabel)}" (${clickLabel})`
      );
    } else {
      els.consentInfo.innerHTML += row("bad", "No reject button found");
    }

    // CMP statistics from our 1000-site study
    if (cmpStats && scan.cmpDetected) {
      els.cmpInfo.classList.remove("hidden");
      els.cmpInfo.innerHTML = `
        <div class="cmp-stats">
          <div class="cmp-stats-title">AECCS Study: ${esc(scan.cmpDetected)} across ${cmpStats.sampleSize} sites</div>
          <div class="cmp-stat-row"><span>Avg compliance score</span><span>${cmpStats.avgScore}/100</span></div>
          <div class="cmp-stat-row"><span>Sites with reject button</span><span>${Math.round(cmpStats.rejectRate * 100)}%</span></div>
        </div>
      `;
    }
  }

  function row(type, html) {
    const icons = { ok: "&#10003;", warn: "&#9679;", bad: "&#10007;" };
    return `<div class="consent-row"><span class="consent-icon ${type}">${icons[type]}</span><span>${html}</span></div>`;
  }

  // ── Accept vs Reject UX Comparison ────────────────────────────────────────

  function renderButtonComparison(comp) {
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

    let html = '<div class="btn-compare">';

    // Accept button preview
    html += '<div class="btn-preview">';
    html += '<div class="btn-preview-label">Accept</div>';
    if (comp.accept) {
      html += `<div class="btn-mock" style="${buttonMockStyle(comp.accept)}">${esc(comp.accept.text)}</div>`;
      html += `<div class="btn-meta">${comp.accept.width}x${comp.accept.height}px | ${comp.accept.fontSize}px | wt ${comp.accept.fontWeight}</div>`;
    }
    html += '</div>';

    // Reject button preview
    html += '<div class="btn-preview">';
    html += `<div class="btn-preview-label">${esc(rejectLabel)}</div>`;
    if (comp.reject) {
      html += `<div class="btn-mock" style="${buttonMockStyle(comp.reject)}">${esc(comp.reject.text)}</div>`;
      html += `<div class="btn-meta">${comp.reject.width}x${comp.reject.height}px | ${comp.reject.fontSize}px | wt ${comp.reject.fontWeight}${esc(rejectMetaSuffix)}</div>`;
    } else {
      html += '<div class="btn-missing">Missing</div>';
    }
    html += '</div>';
    html += '</div>';

    // UX issues
    if (comp.issues && comp.issues.length > 0) {
      html += '<div class="btn-issues">';
      for (const issue of comp.issues) {
        html += `<div class="btn-issue-item"><span>&#9888;</span> ${esc(issue)}</div>`;
      }
      html += '</div>';
    }

    els.buttonComparison.innerHTML = html;
  }

  // ── Dark Pattern Details ──────────────────────────────────────────────────

  function renderDarkPatterns(dp) {
    if (!dp || dp.count === 0) {
      els.darkPatternDetails.innerHTML = '<div class="dp-none">No dark patterns detected</div>';
      return;
    }

    let html = "";
    for (const name of dp.detected) {
      const info = AECCS.DARK_PATTERN_INFO[name];
      if (!info) {
        html += `<div class="dp-card"><div class="dp-card-name">${esc(name)}</div></div>`;
        continue;
      }

      html += `<div class="dp-card severity-${info.severity}">`;
      html += `<div class="dp-card-header">`;
      html += `<span class="dp-card-name">${esc(name)}</span>`;
      html += `<span class="dp-severity ${info.severity}">${info.severity}</span>`;
      html += `</div>`;
      html += `<div class="dp-description">${esc(info.description)}</div>`;
      html += `<div class="dp-gdpr-ref">${esc(info.gdprArticle)}</div>`;
      html += `</div>`;
    }

    els.darkPatternDetails.innerHTML = html;
  }

  // ── Criteria Breakdown ────────────────────────────────────────────────────

  function renderCriteria(criteria) {
    els.criteriaBody.innerHTML = "";
    for (const [key, { score, details }] of Object.entries(criteria)) {
      const label = CRITERIA_LABELS[key] || key;
      const color = scoreColor(score);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <div class="criteria-name">${label}</div>
          <div class="criteria-details">${esc(details)}</div>
        </td>
        <td style="color:${color}">${score}</td>
        <td>
          <div class="progress-bar">
            <div class="progress-fill" style="width:${score}%;background:${color}"></div>
          </div>
        </td>
      `;
      els.criteriaBody.appendChild(tr);
    }
  }

  // ── PET Recommendations ───────────────────────────────────────────────────

  function renderPetRecommendations(pets) {
    if (!pets || pets.length === 0) {
      els.petSection.classList.add("hidden");
      return;
    }

    let html = "";
    for (const pet of pets) {
      const pct = Math.round(pet.effectiveness * 100);
      const color = scoreColor(pct);
      html += `<div class="pet-card">`;
      html += `<div class="pet-effectiveness" style="color:${color};border-color:${color}">${pct}%</div>`;
      html += `<div class="pet-info">`;
      html += `<div><span class="pet-name">${esc(pet.name)}</span><span class="pet-type">${pet.type}</span></div>`;
      html += `<div class="pet-desc">${esc(pet.description)}</div>`;
      html += `</div>`;
      html += `</div>`;
    }

    els.petList.innerHTML = html;
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function scoreColor(score) {
    if (score >= 90) return "#22c55e";
    if (score >= 75) return "#84cc16";
    if (score >= 60) return "#eab308";
    if (score >= 40) return "#f97316";
    return "#ef4444";
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

  function buttonMockStyle(button) {
    const style = [
      `background:${esc(resolveButtonBackground(button))}`,
      `color:${esc(button.color || "inherit")}`,
      `font-size:${button.fontSize}px`,
      `font-weight:${button.fontWeight}`,
      `border-radius:${esc(button.borderRadius || "4px")}`,
    ];

    if (button.border) {
      style.push(`border:${esc(button.border)}`);
    }
    if (button.boxShadow && button.boxShadow !== "none") {
      style.push(`box-shadow:${esc(button.boxShadow)}`);
    }

    return style.join(";");
  }

  function esc(str) {
    const d = document.createElement("div");
    d.textContent = str || "";
    return d.innerHTML;
  }

  // ── Start ─────────────────────────────────────────────────────────────────

  init();
})();
