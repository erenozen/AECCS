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
    disabledState:     $("disabledState"),
    disabledTitle:     $("disabledTitle"),
    disabledMsg:       $("disabledMsg"),
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
      "AECCS works with active visible cookie banners. No cookie banner was detected, so this website was not evaluated.";
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

    if (data.evaluationDisabled?.active) {
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
        clearNode(els.studyInsightsContent);
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
      const color = scoreColor(score);
      const tr = createElement("tr");

      const detailsCell = createElement("td");
      detailsCell.append(
        createElement("div", { className: "criteria-name", text: label }),
        createElement("div", { className: "criteria-details", text: details })
      );

      const scoreCell = createElement("td", { text: score });
      scoreCell.style.color = color;

      const progressCell = createElement("td");
      const progressBar = createElement("div", { className: "progress-bar" });
      const progressFill = createElement("div", { className: "progress-fill" });
      progressFill.style.width = `${score}%`;
      progressFill.style.background = color;
      progressBar.appendChild(progressFill);
      progressCell.appendChild(progressBar);

      tr.append(detailsCell, scoreCell, progressCell);
      els.criteriaBody.appendChild(tr);
    }
  }

  // ── PET Recommendations ───────────────────────────────────────────────────

  function renderPetRecommendations(pets) {
    closeActivePetTooltip();

    if (!pets || pets.length === 0) {
      els.petSection.classList.add("hidden");
      clearNode(els.petList);
      return;
    }

    els.petSection.classList.remove("hidden");
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
        text: "This popup audits the current page locally. The cards below add frozen AECCS study context without introducing extra scans, clicks, or network requests.",
      })
    );

    const positioningCard = buildInsightCard("Why AECCS is Different");
    positioningCard.appendChild(
      createElement("div", {
        className: "insight-card-copy",
        text: guardrails.positioning || "AECCS is a passive, research-grounded cookie-consent auditor.",
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
          text: "Recommendations stay passive: they are tied to the issues found on this page, then grounded in the shared AECCS combined-study snapshot rather than live PET simulation.",
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
