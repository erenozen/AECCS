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

  let currentAnalysis = null;
  let renderedInsightsKey = null;
  let activePetTooltipTrigger = null;

  // ── DOM refs ──────────────────────────────────────────────────────────────

  const $ = id => document.getElementById(id);

  const els = {
    loading:           $("loading"),
    errorState:        $("errorState"),
    errorMsg:          $("errorMsg"),
    results:           $("results"),
    siteDomain:        $("siteDomain"),
    govAlert:          $("govAlert"),
    govNote:           $("govNote"),
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
    petSubtitle:       $("petSubtitle"),
    petList:           $("petList"),
    studyInsightsSection: $("studyInsightsSection"),
    studyInsightsContent: $("studyInsightsContent"),
    footerNote:        $("footerNote"),
  };

  // ── Init ──────────────────────────────────────────────────────────────────

  async function init() {
    try {
      bindStudyInsights();
      bindPetTooltips();

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
    currentAnalysis = data;
    renderedInsightsKey = null;
    els.loading.classList.add("hidden");
    els.results.classList.remove("hidden");

    // Government domain alert
    if (data.isGovDomain) {
      els.govAlert.classList.remove("hidden");
    }

    renderStudyCopy(data.studyMetadata);
    renderScore(data.score);
    renderCookies(data);
    renderTrackers(data.trackersByVendor);
    renderConsent(data.consentScan, data.cmpStats, data.studyMetadata);
    renderButtonComparison(data.consentScan?.buttonComparison);
    renderDarkPatterns(data.consentScan?.darkPatterns);
    renderCriteria(data.score.criteria);
    renderPetRecommendations(data.petRecommendations);

    if (els.studyInsightsSection) {
      els.studyInsightsSection.classList.remove("hidden");
      if (els.studyInsightsSection.open) {
        renderStudyInsights(data);
      } else if (els.studyInsightsContent) {
        els.studyInsightsContent.innerHTML = "";
      }
    }
  }

  function bindStudyInsights() {
    if (!els.studyInsightsSection) return;
    els.studyInsightsSection.addEventListener("toggle", () => {
      if (els.studyInsightsSection.open && currentAnalysis) {
        renderStudyInsights(currentAnalysis);
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

  function renderStudyCopy(studyMetadata) {
    const snapshotDateLabel = studyMetadata?.snapshotDateLabel || "March 6, 2026";
    const sampleSize = studyMetadata?.sampleSize || 1000;
    const successfulCrawls = studyMetadata?.successfulCrawls || 861;
    const publicSector = studyMetadata?.publicSector || {};

    if (els.govNote) {
      els.govNote.textContent =
        `Public-sector sites were included in the combined corpus. In the successful government/public-sector category (${publicSector.successfulSites || 77} sites), average compliance was ${publicSector.avgCompliance || 30.9}/100 and ${formatPercent(publicSector.preConsentTrackerRate ?? 0.753)} showed pre-consent trackers.`;
    }

    if (els.petSubtitle) {
      els.petSubtitle.textContent =
        `Guidance combines this page's live findings with the AECCS ${sampleSize}-site combined study (${successfulCrawls} successful crawls, ${snapshotDateLabel})`;
    }

    if (els.footerNote) {
      els.footerNote.textContent =
        `AECCS · Passive local audit · ${sampleSize}-site combined study snapshot · ${snapshotDateLabel}`;
    }
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

  function renderConsent(scan, cmpStats, studyMetadata) {
    els.consentInfo.innerHTML = "";
    els.cmpInfo.classList.add("hidden");
    els.cmpInfo.innerHTML = "";

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

    if (cmpStats && scan.cmpDetected) {
      els.cmpInfo.classList.remove("hidden");
      els.cmpInfo.innerHTML = `
        <div class="cmp-stats">
          <div class="cmp-stats-title">${esc(scan.cmpDetected)} in the ${studyMetadata?.sampleSize || 1000}-site AECCS combined snapshot</div>
          <div class="cmp-stat-row"><span>Avg compliance score</span><span>${cmpStats.avgScore}/100</span></div>
          <div class="cmp-stat-row"><span>Sites with reject button</span><span>${Math.round(cmpStats.rejectRate * 100)}%</span></div>
          <div class="cmp-stat-row"><span>Sample size</span><span>${cmpStats.sampleSize} sites</span></div>
          <div class="cmp-stat-row"><span>CMP PET score</span><span>${cmpStats.petScore}</span></div>
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
    closeActivePetTooltip();

    if (!pets || pets.length === 0) {
      els.petSection.classList.add("hidden");
      els.petList.innerHTML = "";
      return;
    }

    els.petSection.classList.remove("hidden");

    let html = "";
    for (const [index, pet] of pets.entries()) {
      const color = petStudyColor(pet.studyTrackerReductionPct);
      const metricLabel = pet.studyMetricLabel || studyBadgeLabel(pet.studyTrackerReductionPct);
      const tooltipText = pet.studyTooltipText || buildPetStudyTooltipText(pet);
      const tooltipId = `pet-study-tooltip-${index}`;
      html += `<div class="pet-card">`;
      html += `<div class="pet-header">`;
      html += `<div class="pet-title"><span class="pet-name">${esc(pet.name)}</span><span class="pet-type">${esc(pet.type)}</span></div>`;
      if (metricLabel || tooltipText) {
        html += `<div class="pet-study">`;
        if (metricLabel) {
          html += `<span class="pet-effectiveness" style="color:${color};border-color:${color}">${esc(metricLabel)}</span>`;
        }
        if (tooltipText) {
          html += `<button type="button" class="pet-study-info" aria-label="${escAttr(`Explain study metric for ${pet.name}`)}" aria-expanded="false" aria-controls="${escAttr(tooltipId)}">i</button>`;
          html += `<div class="pet-study-tooltip" id="${escAttr(tooltipId)}" role="tooltip" hidden>${esc(tooltipText)}</div>`;
        }
        html += `</div>`;
      }
      html += `</div>`;
      html += `<div class="pet-desc">${esc(pet.description)}</div>`;
      if (pet.whyRecommended) {
        html += `<div class="pet-desc">Why recommended: ${esc(pet.whyRecommended)}</div>`;
      }
      html += `</div>`;
    }

    els.petList.innerHTML = html;
  }

  function renderStudyInsights(data) {
    if (!els.studyInsightsContent) return;

    const key = buildInsightsKey(data);
    if (renderedInsightsKey === key) return;
    renderedInsightsKey = key;

    const study = data.studyMetadata || AECCS.STUDY_METADATA || {};
    const petStudy = AECCS.PET_STUDY_RESULTS || [];
    const cmpStudy = AECCS.CMP_STUDY_RESULTS || [];
    const highlights = AECCS.RESEARCH_HIGHLIGHTS || [];
    const guardrails = AECCS.CLAIM_GUARDRAILS || {};

    let html = "";
    html += `<div class="insight-badge">${esc(study.label || "AECCS 1000-site combined study snapshot")} · ${esc(study.snapshotDateLabel || "March 6, 2026")}</div>`;
    html += `<div class="insight-intro">This popup audits the current page locally. The cards below add frozen AECCS study context without introducing extra scans, clicks, or network requests.</div>`;

    html += `<div class="insight-card">`;
    html += `<div class="insight-card-title">Why AECCS is Different</div>`;
    html += `<div class="insight-card-copy">${esc(guardrails.positioning || "AECCS is a passive, research-grounded cookie-consent auditor.")}</div>`;
    if (highlights.length > 0) {
      html += `<div class="insight-list">`;
      for (const item of highlights) {
        html += `<div class="insight-list-item"><strong>${esc(item.title)}</strong> — ${esc(item.summary)}</div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;

    html += `<div class="insight-card">`;
    html += `<div class="insight-card-title">Snapshot Metrics</div>`;
    html += `<div class="insight-kv"><span>Run ID</span><strong>${esc(study.runId || "combined-1000")}</strong></div>`;
    html += `<div class="insight-kv"><span>Study baseline</span><strong>${study.sampleSize || 1000} sites / ${study.successfulCrawls || 861} successful crawls</strong></div>`;
    html += `<div class="insight-kv"><span>Sites with banners</span><strong>${study.bannerSites || 595}</strong></div>`;
    html += `<div class="insight-kv"><span>Average compliance score</span><strong>${study.avgCompliance || 27.4}/100</strong></div>`;
    html += `<div class="insight-kv"><span>Missing reject rate</span><strong>${formatPercent(study.missingRejectRate)}</strong></div>`;
    html += `<div class="insight-kv"><span>Multi-layer rejection</span><strong>${formatPercent(study.multiLayerRate)}</strong></div>`;
    html += `<div class="insight-kv"><span>Reject reduces trackers</span><strong>${formatPercent(study.rejectReducesTrackersRate)}</strong></div>`;
    html += `<div class="insight-kv"><span>Reject eliminates trackers</span><strong>${formatPercent(study.rejectEliminatesTrackersRate)}</strong></div>`;
    html += `</div>`;

    html += `<div class="insight-card">`;
    html += `<div class="insight-card-title">PET Guidance For This Page</div>`;
    if (data.petRecommendations && data.petRecommendations.length > 0) {
      html += `<div class="insight-card-copy">Recommendations stay passive: they are tied to the issues found on this page, then grounded in the shared AECCS combined-study snapshot rather than live PET simulation.</div>`;
      html += `<div class="insight-list">`;
      for (const pet of data.petRecommendations) {
        const rationale = pet.whyRecommended || pet.studyLabel || "Study-backed recommendation";
        html += `<div class="insight-list-item"><strong>${esc(pet.name)}</strong> — ${esc(rationale)}</div>`;
      }
      html += `</div>`;
    } else {
      html += `<div class="insight-card-copy">No PET recommendation was needed for this page, but the extension still uses the same shared AECCS combined-study snapshot for context.</div>`;
    }
    html += `</div>`;

    html += `<div class="insight-card">`;
    html += `<div class="insight-card-title">Six PETs, One Study Snapshot</div>`;
    html += `<div class="insight-card-copy">AECCS keeps Brave Shields, Firefox ETP Standard, Firefox ETP Strict, uBlock Origin, Privacy Badger, and Consent-O-Matic in one comparable combined-study surface.</div>`;
    html += `<div class="insight-list">`;
    for (const pet of petStudy) {
      html += `<div class="insight-list-item"><strong>${esc(pet.name)}</strong> — ${esc(pet.studyLabel)}. ${esc(pet.highlight)}</div>`;
    }
    html += `</div>`;
    html += `</div>`;

    html += `<div class="insight-card">`;
    html += `<div class="insight-card-title">CMP And Public-Sector Context</div>`;
    if (data.consentScan?.cmpDetected && data.cmpStats) {
      html += `<div class="insight-card-copy">Detected CMP: <strong>${esc(data.consentScan.cmpDetected)}</strong>. In the shared snapshot it averaged ${data.cmpStats.avgScore}/100 with a reject rate of ${formatPercent(data.cmpStats.rejectRate)}.</div>`;
    } else {
      html += `<div class="insight-card-copy">When a known CMP is detected, AECCS adds shared CMP study context instead of sending data to an external service.</div>`;
    }
    html += `<div class="insight-divider"></div>`;
    html += `<div class="insight-kv"><span>Best CMP in study</span><strong>${esc((cmpStudy[0] && cmpStudy[0].name) || "Didomi")}</strong></div>`;
    html += `<div class="insight-kv"><span>Current page is public sector</span><strong>${data.isGovDomain ? "Yes" : "No"}</strong></div>`;
    html += `<div class="insight-card-copy">The combined corpus included ${study.publicSector?.successfulSites || 77} successful government/public-sector sites. That subset averaged ${study.publicSector?.avgCompliance || 30.9}/100 compliance, and ${formatPercent(study.publicSector?.preConsentTrackerRate ?? 0.753)} showed pre-consent trackers.</div>`;
    html += `</div>`;

    html += `<div class="insight-card">`;
    html += `<div class="insight-card-title">Methodology And Guardrails</div>`;
    html += `<div class="insight-card-copy">Pipeline: crawl → classify → dark-pattern detect → score → CMP analysis → PET comparison → reporting.</div>`;
    if (guardrails.supportedClaims && guardrails.supportedClaims.length > 0) {
      html += `<div class="insight-list">`;
      for (const claim of guardrails.supportedClaims) {
        html += `<div class="insight-list-item"><strong>Claims:</strong> ${esc(claim)}</div>`;
      }
      html += `</div>`;
    }
    if (guardrails.notThis && guardrails.notThis.length > 0) {
      html += `<div class="insight-divider"></div>`;
      for (const item of guardrails.notThis) {
        html += `<div class="insight-list-item">${esc(item)}</div>`;
      }
    }
    html += `</div>`;

    els.studyInsightsContent.innerHTML = html;
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

  function formatPercent(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return "n/a";
    return `${Math.round(value * 1000) / 10}%`;
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

  function escAttr(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // ── Start ─────────────────────────────────────────────────────────────────

  init();
})();
