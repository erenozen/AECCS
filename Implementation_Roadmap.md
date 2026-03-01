# Implementation Roadmap

## Assessing the Effectiveness of Cookie Consent Systems: An Automated Analysis of GDPR Compliance and Privacy Risks on Popular Websites

---

## How This Roadmap Works

Each phase has:
- **Inputs**: What must exist before starting the phase.
- **Steps**: What to build or do.
- **Outputs**: What the phase produces (files, data, modules).

This structure is designed so that each phase can be turned into a self-contained Claude Code prompt.

---

## Phase 0: Foundation & Setup (Weeks 1–3)

> **Inputs**: Nothing — this is the starting point.

### Step 0.1 — Team Role Assignment
- Assign clear roles to each of the 5 team members:
  - **Web Scraping Lead**: Owns the browser automation pipeline (Playwright).
  - **Network & Cookie Analysis Lead**: Handles cookie/tracker capture, HTTP request logging, and classification.
  - **Dark Pattern Detection Lead**: Builds the HTML/CSS analysis module for UI manipulation detection.
  - **PETs Evaluation Lead**: Designs and runs experiments on browser-based PETs and differential privacy integration.
  - **Data Analysis & Reporting Lead**: Owns metrics computation, visualizations, and report generation.
- Note: Roles overlap — everyone contributes to the final report and presentations.

### Step 0.2 — Environment Setup
- Set up a shared GitHub repository with this folder structure:
  ```
  project-root/
  ├── scraper/            # Browser automation scripts
  ├── analysis/           # Cookie classification and metrics
  ├── dark_patterns/      # Banner UI analysis
  ├── pets_evaluation/    # PETs testing module
  ├── reporting/          # Visualization and report generation
  ├── data/
  │   ├── raw/            # Per-site JSON captures
  │   ├── processed/      # Classified cookies, scores
  │   └── websites.csv    # Target website list
  ├── docs/               # Literature, notes, meeting logs
  ├── requirements.txt
  └── README.md
  ```
- Install core dependencies:
  - Python 3.10+
  - Playwright (preferred over Selenium for speed, stealth, and built-in request interception)
  - Pandas, Matplotlib, Seaborn, Jupyter
  - BeautifulSoup4, lxml (for HTML parsing)
  - diffprivlib (IBM) or dp-accounting (Google) for differential privacy
- Set up a VPN or EU-based proxy to simulate EU-based browsing sessions.

### Step 0.3 — Website List Compilation
- Compile a list of **100–200 websites** from:
  - Tranco List (preferred — Alexa was retired) or SimilarWeb rankings.
  - Categorize by sector: e-commerce, news, social media, government, education, healthcare, entertainment.
  - Focus on EU-targeted sites (`.eu`, `.de`, `.fr`, `.nl` TLDs, or sites with known EU audiences).
- Store as `data/websites.csv` with columns: `domain, category, region, rank`.

### Step 0.4 — Literature Deep Dive
- Each team member reads and summarizes **2–3 papers** from top venues:
  - **USENIX Security**: Matte et al., "Do Cookie Banners Respect my Choice?" (2020)
  - **ACM CCS / CHI**: Nouwens et al., "Dark Patterns after the GDPR" (2020)
  - **PETS**: Studies on browser fingerprinting and tracking measurement
  - **IEEE S&P / NDSS**: Papers on web privacy measurement at scale
  - **Additional**: Bollinger et al., "Automating Cookie Consent and GDPR Violation Detection" (USENIX 2022)
- Create a shared literature review document with key findings, methods, and gaps.

> **Outputs**:
> - GitHub repo with folder structure
> - `data/websites.csv` — target website list
> - `requirements.txt` — all dependencies
> - `docs/literature_review.md` — summarized papers
> - Working development environment on each team member's machine

---

## Phase 1: Data Collection Pipeline (Weeks 3–7)

> **Inputs**: `data/websites.csv`, working Playwright environment, EU VPN/proxy.

### Step 1.1 — Basic Browser Automation Script
- Build a headless browser script (`scraper/crawler.py`) that:
  1. Reads a domain from `websites.csv`.
  2. Navigates to the URL via an EU-based proxy.
  3. Waits for the page (and consent banner) to fully load.
  4. Takes a screenshot of the initial page state.
  5. Does **not** interact with the consent banner.
- Handle common issues: timeouts, redirects, captchas, cookie walls.
- Add randomized delays and user-agent rotation to avoid bot detection.
- Use Playwright stealth mode (`playwright-stealth` plugin) for anti-bot evasion.

### Step 1.2 — Pre-Consent Cookie & Tracker Capture
- Before any banner interaction, capture and save:
  - All cookies set in the browser (via Playwright's `context.cookies()`).
  - All HTTP requests made (via Playwright's `page.on('request')` / `page.on('response')` interception).
  - Any local storage or session storage entries.
  - Third-party domains contacted.
- Store per-site data in `data/raw/{domain}.json`:
  ```json
  {
    "domain": "example.com",
    "timestamp": "2026-...",
    "screenshot_path": "data/raw/screenshots/example.com.png",
    "pre_consent": {
      "cookies": [...],
      "http_requests": [...],
      "third_party_domains": [...],
      "local_storage": [...]
    }
  }
  ```

### Step 1.3 — Post-Consent Capture (Accept & Reject Scenarios)
- For each site, run **three separate browser sessions**:
  1. **No interaction**: Baseline (already captured in Step 1.2).
  2. **Accept All**: Click the accept button, then capture cookies/trackers.
  3. **Reject All**: Click the reject button (if available), then capture cookies/trackers.
- For button detection:
  - Use CSS selectors and common patterns (buttons containing text like "Accept", "Reject", "Allow", "Decline", "Manage preferences") — support multiple languages for EU sites.
  - Fall back to XPath or text content matching for non-standard banners.
- Record: whether a "Reject All" button exists, how many clicks required to reject, and how many clicks to accept.
- Append `post_consent_accept` and `post_consent_reject` objects to each site's JSON file.

### Step 1.4 — Consent Banner HTML Extraction
- For each site, extract and save:
  - Full HTML of the consent banner element (`data/raw/banners/{domain}.html`).
  - Banner screenshot cropped separately if possible.
  - Detected CMP provider (OneTrust, Cookiebot, Quantcast, TrustArc, etc.) via known HTML signatures or script URLs.

### Step 1.5 — Flash Talk Preparation (Week 5)
- Prepare a **3-minute verbal description** of the project idea.
- No slides required (unless you want them).
- Goal: get initial feedback from the instructor.
- This is **ungraded** but valuable for course-correcting early.

### Step 1.6 — Midterm Presentation (Week 7)
- Prepare slides covering (as required by the deliverables document):
  - **Problem statement** and motivation.
  - **Literature search** summary.
  - **Planned methods** — system architecture diagram + pipeline description.
  - **Next steps** — what remains to be built.
  - **Expected output** — what the project will produce (tool, dataset, compliance report, PETs comparison).
- Show preliminary data collection results if available (e.g., "we've scanned X sites so far, Y% had pre-consent trackers").
- Email slides in **PDF** to instructor and TA by **9 AM (EST)** on presentation morning.
- Note: Midterm presentation is **10% of course grade**.

> **Outputs**:
> - `scraper/crawler.py` — full automation pipeline
> - `data/raw/{domain}.json` — per-site capture data (pre-consent, post-accept, post-reject)
> - `data/raw/screenshots/` — page screenshots
> - `data/raw/banners/` — extracted banner HTML files
> - Flash talk delivered (Week 5)
> - Midterm presentation slides delivered (Week 7)

---

## Phase 2: Analysis Modules (Weeks 7–10)

> **Inputs**: `data/raw/{domain}.json` files for all crawled sites, `data/raw/banners/` HTML files.

### Step 2.1 — Cookie & Tracker Classification
- Build `analysis/classifier.py` that classifies each captured cookie using:
  - **EasyList / EasyPrivacy filter lists**: For known tracker domains (download and parse locally).
  - **WhoTracksMe database**: For tracker vendor identification (e.g., Google Analytics, Meta Pixel, Amazon Ad System).
  - **Disconnect list**: Additional tracker classification source.
  - **Cookiepedia** or **Open Cookie Database**: For known cookie name/purpose mapping.
- For each cookie, determine and store:
  - First-party vs. third-party.
  - Purpose: necessary, functional, analytics, advertising, unknown.
  - Expiration duration.
  - Vendor/owner.
- Output: `data/processed/{domain}_classified.json` with enriched cookie data.

### Step 2.2 — Dark Pattern Detection Module
- Build `dark_patterns/detector.py` that analyzes banner HTML to detect:
  - **Asymmetric buttons**: "Accept" is prominent, "Reject" is hidden or smaller (compare computed CSS: size, color, contrast, font weight).
  - **Missing reject option**: No "Reject All" button at the first layer.
  - **Forced action**: Cookie walls that block content until consent is given.
  - **Pre-checked boxes**: Consent categories toggled on by default.
  - **Confusing language**: Ambiguous or misleading button labels.
  - **Multi-layer rejection**: Requiring 2+ clicks to reject vs. 1 click to accept.
- Implementation:
  - Parse banner HTML with BeautifulSoup.
  - Extract all button/link elements, compare CSS properties programmatically.
  - Use click counts recorded in Phase 1 (accept clicks vs. reject clicks).
  - Flag patterns based on predefined heuristic rules.
- Output: `data/processed/{domain}_dark_patterns.json` with detected patterns per site.

### Step 2.3 — Compliance Scoring System
- Build `analysis/scoring.py` that computes a **GDPR compliance score (0–100)** per site:
  | Criterion | Weight | Description |
  |---|---|---|
  | No pre-consent trackers | 25% | No tracking cookies set before user interaction |
  | Reject option available | 20% | A clear "Reject All" button exists at the first layer |
  | Equal accept/reject effort | 15% | Same number of clicks for accept and reject |
  | No dark patterns | 15% | No asymmetric buttons, forced action, or pre-checked boxes |
  | Post-reject compliance | 15% | Trackers actually stop after user rejects |
  | Transparent information | 10% | Clear purpose descriptions and vendor lists |
- Output: `data/processed/compliance_scores.csv` with columns: `domain, category, score, criterion_breakdown`.

### Step 2.4 — Metrics Computation
- Build `analysis/metrics.py` that aggregates across all sites:
  - Percentage of sites with pre-consent trackers (overall and by category).
  - Average number of trackers per site (before consent, after accept, after reject).
  - Most common tracker vendors and their prevalence.
  - Dark pattern prevalence by type.
  - Compliance score distribution and statistics.
  - Comparison across website categories.
  - Key finding: does rejecting consent actually reduce trackers?
- Output: `data/processed/aggregate_metrics.json` — all computed statistics.

> **Outputs**:
> - `analysis/classifier.py` — cookie/tracker classification module
> - `dark_patterns/detector.py` — dark pattern detection module
> - `analysis/scoring.py` — compliance scoring system
> - `analysis/metrics.py` — aggregate metrics computation
> - `data/processed/{domain}_classified.json` — enriched cookie data per site
> - `data/processed/{domain}_dark_patterns.json` — dark patterns per site
> - `data/processed/compliance_scores.csv` — scores for all sites
> - `data/processed/aggregate_metrics.json` — aggregated statistics

---

## Phase 3: PETs Evaluation (Weeks 10–13)

> **This is the critical differentiator for the course.** The PETs evaluation must go beyond ethical scraping and demonstrate real engagement with privacy-enhancing technologies as taught in a PETs course.

> **Inputs**: Working `scraper/crawler.py` pipeline, `data/websites.csv`, `analysis/` modules from Phase 2.

### Step 3.1 — Evaluate Browser-Based PETs as Defenses
- Build `pets_evaluation/browser_pets.py` that re-runs the data collection pipeline under different **browser PET configurations**:
  1. **Baseline**: Vanilla Chromium, no extensions, no protection.
  2. **uBlock Origin**: Popular content/tracker blocker.
  3. **Privacy Badger (EFF)**: Heuristic-based tracker blocker.
  4. **Firefox Enhanced Tracking Protection (ETP)**: Standard and Strict modes.
  5. **Brave Shields**: Built-in tracker and ad blocking.
  6. **Consent-O-Matic**: Auto-consent manager that automatically rejects cookies.
- For each configuration, measure:
  - How many pre-consent trackers are blocked vs. baseline?
  - How many post-accept trackers are blocked?
  - Does the PET effectively enforce the user's rejection choice?
  - Does the PET break site functionality (e.g., cookie wall still blocks content)?
- Output: `data/processed/pets_effectiveness.csv` — a PET effectiveness matrix comparing tools across websites and categories.
- Note: For Playwright, Chromium extensions can be loaded via `chromium.launch_persistent_context(user_data_dir, args=['--load-extension=...'])`. For Firefox ETP and Brave, launch those browsers directly if available, or simulate via equivalent filter lists.

### Step 3.2 — Differential Privacy in Aggregated Reporting
- Build `pets_evaluation/dp_reporting.py` that applies **differential privacy** to aggregated statistics:
  - Use the **Laplace mechanism** to add calibrated noise to category-level metrics (e.g., "X% of news sites have pre-consent trackers").
  - Use **randomized response** for binary per-site attributes (e.g., "site has pre-consent trackers: yes/no").
  - Show the privacy-utility tradeoff: how aggregate accuracy degrades as the privacy budget (epsilon) decreases.
  - Justification: publicly reporting per-site compliance data could have legal implications — DP provides plausible deniability at the individual site level while preserving aggregate trends.
- Implementation: Use IBM's `diffprivlib` library.
- Output: `data/processed/dp_aggregate_metrics.json` — differentially private versions of aggregate statistics at multiple epsilon values.

### Step 3.3 — Analyze Consent Management Platforms (CMPs) as PETs
- Build `pets_evaluation/cmp_analysis.py` that:
  - Identifies which **Consent Management Platform** each site uses (from Phase 1 CMP detection).
  - Groups sites by CMP provider (OneTrust, Cookiebot, Quantcast, TrustArc, custom, etc.).
  - Evaluates whether each CMP functions as an effective PET:
    - Does it faithfully block trackers when the user rejects consent?
    - Does it support IAB Transparency & Consent Framework (TCF) signals?
    - What is the average compliance score per CMP?
  - Ranks CMPs by real-world privacy protection effectiveness.
- Output: `data/processed/cmp_comparison.csv` — CMP effectiveness rankings and per-CMP compliance statistics.

### Step 3.4 — PETs Comparison Summary
- Build `pets_evaluation/comparison.py` that synthesizes all PETs evaluation results:
  - Which PETs are most effective at reducing tracking?
  - Do combinations work better (e.g., Consent-O-Matic + uBlock Origin)?
  - How do browser-level PETs compare to CMP-level PETs?
  - Recommendations for users: what PET combination best protects privacy?
- Output: `data/processed/pets_summary.json` — structured comparison data for the report.

> **Outputs**:
> - `pets_evaluation/browser_pets.py` — browser PET testing module
> - `pets_evaluation/dp_reporting.py` — differential privacy module
> - `pets_evaluation/cmp_analysis.py` — CMP analysis module
> - `pets_evaluation/comparison.py` — PETs comparison synthesis
> - `data/processed/pets_effectiveness.csv` — browser PET effectiveness matrix
> - `data/processed/dp_aggregate_metrics.json` — DP-protected statistics
> - `data/processed/cmp_comparison.csv` — CMP effectiveness data
> - `data/processed/pets_summary.json` — overall PETs comparison

---

## Phase 4: Visualization & Report Drafting (Weeks 12–15)

> **Inputs**: All `data/processed/` files from Phases 2 and 3.

### Step 4.1 — Generate Visualizations
- Build `reporting/visualize.py` using Matplotlib, Seaborn, or Plotly to create:
  - **Bar charts**: Violation rates by website category.
  - **Pie charts**: Tracker vendor market share.
  - **Heatmaps**: Compliance score by category and region.
  - **Box plots**: Tracker count distributions (before consent, after accept, after reject).
  - **Grouped bar charts**: PET effectiveness comparison across browser configurations.
  - **Scatter plots**: Compliance score vs. number of trackers.
  - **Line charts**: Privacy-utility tradeoff for differential privacy (accuracy vs. epsilon).
  - **Stacked bar charts**: CMP comparison — compliance score breakdown by criterion.
- Save all figures to `reporting/figures/` as high-resolution PNGs for the report.

### Step 4.2 — Final Report Drafting
- Use **ACM 2-column proceedings template** (https://www.acm.org/publications/proceedings-template).
- Filename: `CookieConsent.pdf` (or your chosen project acronym).
- **No page limitation** (per deliverables document).
- Report outline:
  1. **Abstract**
  2. **Introduction**: Problem statement, motivation, contributions, novelty statement.
  3. **Related Work**: Literature survey from top venues (NDSS, CCS, USENIX, PETS, S&P).
  4. **System Design**: Architecture diagram, pipeline description, pseudocode for key modules (scraper, classifier, dark pattern detector, scoring system).
  5. **Methodology**: Website selection criteria, data collection process, classification approach.
  6. **PETs Evaluation**: Browser-based PETs experiments, differential privacy integration, CMP analysis.
  7. **Results**: All metrics, visualizations, compliance findings, PETs comparison.
  8. **Discussion**: Key insights, limitations, threats to validity.
  9. **Future Work**: Longitudinal tracking, more regions/languages, ML-based dark pattern detection, real-time monitoring tool, etc.
  10. **Conclusion**
  11. **References**
- Grading criteria to keep in mind: Organization, grammar, readability, novelty/difficulty, **publishability**.

### Step 4.3 — Code Cleanup & Documentation
- Clean up all source code in the repository.
- Add a comprehensive `README.md` with:
  - Project description and abstract.
  - Installation and setup instructions.
  - How to run each module (scraper, analysis, PETs evaluation, reporting).
  - Sample output.
- Add inline comments and docstrings to all key functions.
- Finalize `requirements.txt` with pinned versions.

> **Outputs**:
> - `reporting/visualize.py` — visualization generation script
> - `reporting/figures/` — all charts and graphs as PNGs
> - Final report draft in ACM format (`CookieConsent.pdf`)
> - Clean, documented codebase with README

---

## Phase 5: Final Presentations & Submission (Weeks 15–16)

> **Inputs**: Completed report draft, all visualizations, clean codebase.

### Step 5.1 — Final Presentation Preparation
- Prepare slides for a **20-minute presentation + 5-minute Q&A**.
- Suggested structure:
  - Introduction and motivation (2 min)
  - Related work and novelty positioning (2 min)
  - System design and architecture diagram (3 min)
  - Methodology and data collection (3 min)
  - PETs evaluation results (4 min)
  - Key findings and metrics (3 min)
  - Demo or live walkthrough (2 min — optional but impressive)
  - Future work and conclusion (1 min)
- Practice timing — **grading includes timing adherence**.
- Email slides in **PDF** to instructor and TA by **9 AM (EST)** on presentation morning.
- Note: Final presentation is **25% of course grade**.

### Step 5.2 — Final Report Submission
- Finalize and proofread the ACM-formatted report.
- Ensure all figures, tables, and citations are properly formatted.
- Submit `CookieConsent.pdf` + all source code to **Moodle** by end of Week 16.
- Note: Final report is **25% of course grade**.

### Step 5.3 — Peer Review
- **Peer review affects 30% of the final report + presentation grades.**
- Attend all other groups' presentations.
- Provide thoughtful, constructive peer feedback.
- Prepare your team to answer tough questions during your own Q&A — anticipate questions about:
  - Limitations of automated banner detection.
  - Why certain PETs configurations were chosen.
  - How differential privacy parameters (epsilon) were selected.
  - Generalizability of results beyond the tested websites.

> **Outputs**:
> - Final presentation slides (PDF)
> - `CookieConsent.pdf` — final report in ACM format
> - Source code package submitted to Moodle
> - Peer review forms completed

---

## Timeline Summary

| Week | Milestone |
|---|---|
| 1–2 | Team formation, role assignment |
| 3 | Topic finalized, environment setup, website list compiled, literature review started |
| 3–5 | Build scraper, begin data collection |
| **5** | **Flash talk (3 min, ungraded — get instructor feedback)** |
| 5–7 | Complete data collection pipeline, prepare midterm slides |
| **7** | **Midterm Presentation (10% of grade)** |
| 7–10 | Cookie classification, dark pattern detection, compliance scoring |
| 10–13 | PETs evaluation (browser PETs, DP, CMP analysis) |
| 12–15 | Visualizations, final report drafting, code cleanup |
| 15 | Final presentation rehearsals |
| **15–16** | **Final Presentations (25% of grade)** |
| **16** | **Final report + source code submission (25% of grade)** |

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| Websites block automated scraping | User-agent rotation, randomized delays, Playwright stealth mode, residential proxies |
| Consent banners are too diverse to detect programmatically | Flexible pattern-matching with multilingual support; manually label a sample and iterate |
| Anti-bot measures (CAPTCHAs, Cloudflare) | Skip blocked sites and document failure rate; use stealth plugins |
| VPN/proxy gets blocked | Rotate EU-based proxy providers; have fallback options ready |
| Some PET browser extensions hard to automate | Use Playwright persistent context for Chromium extensions; for Firefox/Brave, launch natively or simulate via filter lists |
| Scope creep (too many websites, too many PETs) | Start with 100 sites and 3 PET configs; expand only if time permits |
| Uneven team contribution | Weekly stand-ups, shared task tracker (GitHub Issues), clear role ownership |
| Differential privacy implementation complexity | Start with simple Laplace mechanism on 2–3 key metrics; expand if time permits |
