# Cookie Consent Compliance Analyzer

> Automated GDPR compliance analysis and PETs evaluation for cookie consent systems on popular websites.

## Overview

This project provides an automated pipeline for assessing how well popular websites comply with GDPR cookie consent requirements. It crawls websites, captures cookies and network requests across three consent states (no interaction, accept all, reject all), classifies trackers, detects dark patterns in consent banners, computes per-site compliance scores, and evaluates multiple privacy-enhancing technologies (PETs) as countermeasures.

The analysis covers browser-level PETs (uBlock Origin, Privacy Badger, Firefox ETP, Brave Shields, Consent-O-Matic), differential privacy mechanisms for publishing aggregate statistics, and consent management platform (CMP) effectiveness. The repository currently contains a reproducible synthetic demo dataset plus the full real-study pipeline; final empirical claims remain pending until the real crawl and PET experiments are completed under `data/real/`.

Built as a course project for **CS475 — Privacy-Enhancing Technologies**.

## Data Modes

The pipeline now separates demonstration data from the final study dataset:

- `data/mock/` and `reporting/mock/`: synthetic demo artifacts used for development and rehearsal
- `data/real/` and `reporting/real/`: the final study target for real crawls and report generation
- `data/legacy/` and `reporting/legacy/`: quarantined historical root-level artifacts kept only for traceability

`real` is the default mode for the crawler, analysis stages, PET modules, visualizer, and report generator.

## Team

| Name | Student ID |
|------|-----------|
| Ahmed Hatem Haikal | 22001482 |
| Atakan Keser | 22003865 |
| Deniz Şahin | 22201690 |
| Şeyhmus Eren Özen | 21803591 |
| Moin Khan | 22101287 |

## Features

- **Automated web crawling** with Playwright — captures cookies, HTTP requests, consent banners, and screenshots in three consent states
- **Cookie & tracker classification** using EasyList, EasyPrivacy, Disconnect Services, and a built-in fallback heuristic
- **Dark pattern detection** — identifies 7 deceptive UI patterns in consent banners (asymmetric buttons, preselected checkboxes, hidden reject, confusing language, forced action, color manipulation, multi-layer rejection)
- **GDPR compliance scoring** — 0–100 score based on 6 weighted criteria with letter grades (A–F)
- **Aggregate metrics** — statistics across all sites broken down by category, region, and CMP
- **Browser PET evaluation** — tests 7 configurations (baseline, uBlock Origin, Privacy Badger, Firefox ETP Standard/Strict, Brave Shields, Consent-O-Matic)
- **Differential privacy reporting** — Laplace, Gaussian, and Randomized Response mechanisms at multiple epsilon values
- **CMP effectiveness analysis** — ranks consent management platforms (OneTrust, Cookiebot, Quantcast, TrustArc, Didomi, Usercentrics) as privacy tools
- **Unified PETs comparison** — synthesizes all PET evaluations with combination analysis and user recommendations
- **11 report-ready visualizations** (300 DPI)
- **Self-contained HTML report** with embedded images and auto-generated narrative

## Project Structure

```
AECCS/
├── config.py                          # Central configuration (paths, weights, PET configs)
├── requirements.txt                   # Python dependencies
├── README.md                          # This file
├── Implementation_Roadmap.md          # Development phases documentation
│
├── scraper/
│   ├── __init__.py
│   └── crawler.py                     # Playwright-based website crawler
│
├── analysis/
│   ├── __init__.py
│   ├── classifier.py                  # Cookie/tracker classification
│   ├── scoring.py                     # GDPR compliance scoring (0–100)
│   └── metrics.py                     # Aggregate statistics engine
│
├── dark_patterns/
│   ├── __init__.py
│   └── detector.py                    # 7 dark pattern detectors
│
├── pets_evaluation/
│   ├── __init__.py
│   ├── browser_pets.py                # Browser PET evaluation (7 configs)
│   ├── dp_reporting.py                # Differential privacy analysis
│   ├── cmp_analysis.py                # CMP effectiveness analysis
│   └── comparison.py                  # Unified PETs comparison & synthesis
│
├── scripts/
│   ├── __init__.py
│   └── run_pipeline.py                # Unified mock/real pipeline runner
│
├── reporting/
│   ├── __init__.py
│   ├── visualize.py                   # 11 report-ready figures
│   ├── report_generator.py            # Self-contained HTML report builder
│   └── figures/                       # Generated figures (300 DPI PNGs)
│
├── tests/
│   ├── __init__.py
│   ├── generate_mock_data.py          # Mock crawl data generator (20 sites)
│   └── generate_mock_pets_data.py     # Mock PET evaluation data generator
│
└── data/
    ├── websites.csv                   # Real-study seed list (100 domains)
    ├── legacy/                        # Quarantined historical root-level outputs
    ├── mock/                         # Synthetic demo dataset
    │   ├── raw/
    │   └── processed/
    ├── real/                         # Final study dataset
    │   ├── raw/
    │   └── processed/
    └── tracker_lists/                 # Downloaded filter lists (auto-fetched)
```

Course deliverables are stored under `docs/`. The current report and presentation files are structured submission templates, but they still need to be updated with real-study results before final submission. A living project-status summary is maintained in `docs/project_status.md`.

## Prerequisites

- **Python 3.10+**
- **Playwright** browsers (Chromium and Firefox)
- **EU VPN or proxy** (recommended for triggering GDPR consent banners)
- **(Optional)** Browser extensions for PET evaluation (uBlock Origin, Privacy Badger, Consent-O-Matic)

## Installation

```bash
git clone https://github.com/erenozen/AECCS.git
cd AECCS
pip install -r requirements.txt
playwright install chromium firefox
```

## Quick Start

```bash
# Unified end-to-end runner (recommended)
python -m scripts.run_pipeline --source-mode mock
python -m scripts.run_pipeline --source-mode real --run-id real-study-001

# 1. Generate the synthetic demo dataset
python -m tests.generate_mock_data
python -m analysis.classifier --source-mode mock
python -m dark_patterns.detector --source-mode mock
python -m analysis.scoring --source-mode mock
python -m analysis.metrics --source-mode mock
python -m tests.generate_mock_pets_data
python -m pets_evaluation.dp_reporting --source-mode mock
python -m pets_evaluation.cmp_analysis --source-mode mock
python -m pets_evaluation.comparison --source-mode mock
python -m reporting.visualize --source-mode mock
python -m reporting.report_generator --source-mode mock

# 2. Crawl the real study list (writes into data/real by default)
python -m scraper.crawler --source-mode real

# 3. Classify cookies and trackers
python -m analysis.classifier --source-mode real

# 4. Detect dark patterns in consent banners
python -m dark_patterns.detector --source-mode real

# 5. Compute GDPR compliance scores
python -m analysis.scoring --source-mode real

# 6. Compute aggregate metrics
python -m analysis.metrics --source-mode real

# 7. Evaluate browser PETs (requires real browsers/extensions)
python -m pets_evaluation.browser_pets --source-mode real

# 8. Generate differential privacy report
python -m pets_evaluation.dp_reporting --source-mode real

# 9. Analyze CMP effectiveness
python -m pets_evaluation.cmp_analysis --source-mode real

# 10. Compare all PETs
python -m pets_evaluation.comparison --source-mode real

# 11. Generate all visualizations
python -m reporting.visualize --source-mode real

# 12. Generate HTML report (opens in browser with --open)
python -m reporting.report_generator --source-mode real --open
```

## Pipeline Runner

Use the unified pipeline runner when you want one shared `run_id`, a persisted
manifest, and resumable execution:

```bash
# Full mock/demo run
python -m scripts.run_pipeline --source-mode mock

# Full real run
python -m scripts.run_pipeline --source-mode real --run-id real-study-001

# Resume an interrupted real run
python -m scripts.run_pipeline --source-mode real --resume --run-id real-study-001

# Run only the downstream reporting stages
python -m scripts.run_pipeline --source-mode real --from-step metrics --run-id real-study-001

# Preview commands without executing them
python -m scripts.run_pipeline --source-mode real --dry-run
```

The default manifest path is `data/{source_mode}/processed/run_manifest.json`.

## Module Documentation

### Scraper (`scraper/crawler.py`)

Automated website crawler using Playwright. Visits each site in three consent states:
1. **No interaction** — captures baseline cookies and trackers
2. **Accept all** — clicks the accept button and re-captures
3. **Reject all** — clicks the reject button and re-captures

Also detects consent banners, CMP providers (OneTrust, Cookiebot, Quantcast, TrustArc, Didomi, Usercentrics), and saves screenshots.

```bash
# Crawl all sites in websites.csv
python -m scraper.crawler

# Crawl a single domain
python -m scraper.crawler --domain example.com

# Crawl with EU proxy
python -m scraper.crawler --proxy socks5://eu-proxy:1080

# Limit to N sites
python -m scraper.crawler --max-sites 10
```

### Cookie Classifier (`analysis/classifier.py`)

Classifies cookies as tracker/non-tracker using multiple filter lists:
- **EasyList** and **EasyPrivacy** — community-maintained ad/tracker block lists
- **Disconnect Services** — categorized tracker database
- **Fallback heuristic** — built-in map of known tracker domains

```bash
# Classify all crawled sites
python -m analysis.classifier

# Classify a single site
python -m analysis.classifier --domain example.com

# Custom data paths
python -m analysis.classifier --raw-dir data/real/raw --output-dir data/real/processed
```

### Dark Pattern Detector (`dark_patterns/detector.py`)

Detects 7 types of dark patterns in cookie consent banners:

| Pattern | Description |
|---------|-------------|
| Asymmetric Buttons | Accept button is more prominent than reject |
| Preselected Checkboxes | Non-essential cookie categories pre-checked |
| Hidden Reject | Reject option is hard to find or absent |
| Confusing Language | Misleading wording in consent dialogs |
| Forced Action | No way to dismiss banner without accepting |
| Color Manipulation | Visual design that steers toward "accept" |
| Multi-Layer Rejection | Rejecting requires multiple clicks/pages |

```bash
# Detect dark patterns for all sites
python -m dark_patterns.detector

# Single site
python -m dark_patterns.detector --domain example.com
```

### Compliance Scorer (`analysis/scoring.py`)

Scores each site from 0 to 100 based on 6 weighted GDPR compliance criteria:

| Criterion | Weight | Description |
|-----------|--------|-------------|
| No pre-consent trackers | 25% | No tracking before user consent |
| Reject option available | 20% | Easy-to-find reject/decline button |
| Equal accept/reject effort | 15% | Same number of clicks to accept or reject |
| No dark patterns | 15% | No deceptive UI elements |
| Post-reject compliance | 15% | Trackers actually stop after rejection |
| Transparent information | 10% | Clear privacy/cookie information |

Grades: A (90–100), B (75–89), C (60–74), D (40–59), F (0–39).

```bash
# Score all classified sites
python -m analysis.scoring

# Custom paths
python -m analysis.scoring --processed-dir data/real/processed --output data/real/processed/compliance_scores.csv
```

### Metrics (`analysis/metrics.py`)

Computes aggregate statistics across all analyzed sites:
- Pre-consent violation rates by category
- Tracker vendor prevalence and categories
- Consent banner analysis (accept/reject click counts)
- Dark pattern prevalence by type
- Compliance score distributions by category
- CMP market share

```bash
python -m analysis.metrics
```

### Browser PET Evaluator (`pets_evaluation/browser_pets.py`)

Tests 7 browser-level privacy configurations:

| PET | Browser | Description |
|-----|---------|-------------|
| Baseline | Chromium | Vanilla browser, no protection |
| uBlock Origin | Chromium | Popular ad/tracker blocker |
| Privacy Badger | Chromium | EFF's learning tracker blocker |
| Firefox ETP Standard | Firefox | Firefox Enhanced Tracking Protection (Standard) |
| Firefox ETP Strict | Firefox | Firefox ETP (Strict mode) |
| Brave Shields | Chromium | Brave's built-in ad/tracker blocker (simulated) |
| Consent-O-Matic | Chromium | Auto-rejects cookie consent dialogs |

```bash
# Evaluate all PETs on all sites
python -m pets_evaluation.browser_pets

# Specific PETs only
python -m pets_evaluation.browser_pets --pets ublock_origin brave_shields

# Single domain
python -m pets_evaluation.browser_pets --domain example.com --max-sites 1
```

**Extension setup**: For uBlock Origin, Privacy Badger, and Consent-O-Matic, download the unpacked extension directories and place them in the project root (e.g., `extensions/ublock-origin/`). The module will print instructions if extensions are not found.

### Differential Privacy (`pets_evaluation/dp_reporting.py`)

Applies differential privacy mechanisms to aggregate metrics:
- **Laplace mechanism** — for counting queries (e.g., percentage of sites with trackers)
- **Gaussian mechanism** — for mean queries (e.g., average compliance score)
- **Randomized response** — for binary attributes (e.g., "has pre-consent trackers?")

Tests multiple epsilon values (0.1, 0.5, 1.0, 2.0, 5.0, 10.0) and recommends the optimal privacy budget.

```bash
# Run DP analysis with default settings
python -m pets_evaluation.dp_reporting

# Custom epsilons and trial count
python -m pets_evaluation.dp_reporting --epsilons 0.5 1.0 2.0 --trials 200
```

### CMP Analyzer (`pets_evaluation/cmp_analysis.py`)

Groups sites by detected CMP and evaluates each CMP's effectiveness as a privacy tool:
- Average compliance score
- Reject button availability and effectiveness
- Post-reject tracker reduction
- Dark pattern prevalence
- TCF (Transparency & Consent Framework) support

CMPs are ranked using a weighted composite score (30% compliance + 25% reject works + 20% reject available + 15% inverse dark patterns + 10% tracker reduction).

```bash
python -m pets_evaluation.cmp_analysis
```

### PETs Comparison (`pets_evaluation/comparison.py`)

Synthesizes results from all PET evaluation modules into a unified comparison:
- Browser PET rankings by tracker reduction
- CMP rankings as privacy tools
- Combination analysis (browser PET + CMP estimated combined effectiveness)
- DP privacy cost summary
- Overall findings and user recommendations

```bash
python -m pets_evaluation.comparison
```

### Visualization (`reporting/visualize.py`)

Generates 11 report-ready figures (300 DPI):

| Figure | Filename | Description |
|--------|----------|-------------|
| 1 | `violation_rates_by_category.png` | Pre-consent violations by category |
| 2 | `tracker_vendor_share.png` | Tracker vendor market share (donut) |
| 3 | `cookie_comparison_by_category.png` | Tracker count before/after consent |
| 4 | `compliance_score_distribution.png` | Score distribution (histogram + KDE) |
| 5 | `compliance_heatmap.png` | Scores by category × region/CMP |
| 6 | `dark_pattern_prevalence.png` | Dark pattern type prevalence |
| 7 | `pet_effectiveness_comparison.png` | PET tracker reduction comparison |
| 8 | `pet_effectiveness_heatmap.png` | PET × category tracker heatmap |
| 9 | `dp_privacy_utility_tradeoff.png` | DP epsilon vs. MAE tradeoff |
| 10 | `cmp_comparison.png` | CMP effectiveness comparison |
| 11 | `summary_dashboard.png` | 2×2 key findings dashboard |

```bash
# Generate all figures
python -m reporting.visualize

# Generate specific figures
python -m reporting.visualize --figures violation_rates pet_effectiveness dp_tradeoff

# List available figures
python -m reporting.visualize --list

# Output as PDF
python -m reporting.visualize --format pdf

# Custom directories
python -m reporting.visualize --processed-dir data/real/processed --output-dir reporting/real/figures
```

### Report Generator (`reporting/report_generator.py`)

Generates a self-contained HTML report with:
- All figures embedded as base64 images (no external dependencies)
- Executive summary with auto-generated narrative
- Data tables for compliance scores, dark patterns, PET rankings, CMP comparison
- Clean, print-friendly CSS styling
- Interactive table of contents

```bash
# Generate report
python -m reporting.report_generator

# Generate and open in browser
python -m reporting.report_generator --open

# Custom output path
python -m reporting.report_generator --source-mode real --output reporting/real/my_report.html
```

## Configuration

All configuration is centralized in `config.py`. Key settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `PROXY_URL` | EU proxy for triggering GDPR banners | `None` (set your own) |
| `REQUEST_DELAY_RANGE` | Delay between requests (seconds) | `(2, 5)` |
| `PAGE_LOAD_TIMEOUT` | Page load timeout (ms) | `30000` |
| `CONSENT_WAIT_TIME` | Wait after consent interaction (ms) | `3000` |
| `COMPLIANCE_WEIGHTS` | Scoring criteria weights (sum to 1.0) | See `config.py` |
| `PET_CONFIGURATIONS` | Browser PETs to evaluate | 7 configurations |
| `CMP_SIGNATURES` | CMP detection patterns | 6 CMPs |

## Website List

The `data/websites.csv` file contains the current real-study seed list. Expand or refine it from Tranco-like sources as needed:
- [Tranco List](https://tranco-list.eu/) (recommended)
- Focus on diverse categories: E-Commerce, News, Social Media, Government, Education, Healthcare, Entertainment, Finance, Technology
- **Current repo target**: 100 websites
- **Proposal target**: 100–200 websites

CSV format:
```csv
domain,category,region,rank
bbc.co.uk,News,UK,1
lemonde.fr,News,FR,2
```

## Testing with Mock Data

Mock data generators create realistic test data without requiring actual web crawls:

```bash
# Generate mock crawl data (20 diverse sites)
python -m tests.generate_mock_data

# Generate mock PET evaluation data (19 successful mock sites × 7 PETs)
python -m tests.generate_mock_pets_data

# Run the full analysis pipeline on mock data
python -m analysis.classifier --source-mode mock
python -m dark_patterns.detector --source-mode mock
python -m analysis.scoring --source-mode mock
python -m analysis.metrics --source-mode mock
python -m pets_evaluation.dp_reporting --source-mode mock
python -m pets_evaluation.cmp_analysis --source-mode mock
python -m pets_evaluation.comparison --source-mode mock
python -m reporting.visualize --source-mode mock
python -m reporting.report_generator --source-mode mock --open
```

## Output Files

| File | Description |
|------|-------------|
| `data/{mode}/raw/{domain}.json` | Per-site crawl data (cookies, requests, banner) |
| `data/{mode}/raw/banners/{domain}.html` | Saved consent banner HTML |
| `data/{mode}/raw/screenshots/{domain}.png` | Page screenshots |
| `data/{mode}/processed/{domain}_classified.json` | Classified cookies with tracker/category |
| `data/{mode}/processed/{domain}_dark_patterns.json` | Dark pattern detection results |
| `data/{mode}/processed/{domain}_score.json` | Detailed compliance score breakdown |
| `data/{mode}/processed/compliance_scores.csv` | All sites' compliance scores and grades |
| `data/{mode}/processed/aggregate_metrics.json` | Aggregate statistics across all sites |
| `data/{mode}/processed/pets_effectiveness.csv` | Browser PET evaluation results |
| `data/{mode}/processed/dp_aggregate_metrics.json` | Differential privacy analysis |
| `data/{mode}/processed/cmp_comparison.csv` | CMP effectiveness rankings |
| `data/{mode}/processed/cmp_comparison_detailed.json` | Detailed CMP analysis |
| `data/{mode}/processed/pets_summary.json` | Unified PETs comparison |
| `reporting/{mode}/figures/*.png` | All visualizations (300 DPI) |
| `reporting/{mode}/compliance_report.html` | Self-contained HTML report |

## References

- GDPR Regulation (EU) 2016/679
- CNIL Guidelines on Cookies and Trackers
- Nouwens et al., "Dark Patterns after the GDPR" (CHI 2020)
- Matte et al., "Do Cookie Banners Respect my Choice?" (USENIX Security 2020)
- Bollinger et al., "Automating Cookie Consent and GDPR Violation Detection" (USENIX 2022)

## License

MIT
