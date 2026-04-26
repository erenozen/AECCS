# AECCS

AECCS (Automated Cookie Consent Compliance Scanner) is a Python research pipeline and browser extension for auditing cookie-consent behavior, tracker activity, GDPR-oriented compliance signals, and privacy-enhancing technology (PET) effectiveness.

Built for CS475 - Privacy-Enhancing Technologies.

## What It Does

- Crawls websites with Playwright in three consent states: no interaction, accept all, and reject all.
- Classifies cookies and tracker domains using public filter lists plus local heuristics.
- Detects consent-banner dark patterns and common consent management platforms.
- Scores GDPR-oriented compliance from observable technical and UI evidence.
- Evaluates browser PETs, CMP behavior, and differential privacy reporting options.
- Generates CSV/JSON outputs, figures, self-contained HTML reports, and a local Chrome/Firefox extension.

## Repository Layout

```text
analysis/              Cookie classification, scoring, and aggregate metrics
dark_patterns/         Consent-banner dark-pattern detection
scraper/               Playwright crawler
pets_evaluation/       Browser PET, CMP, DP, and comparison modules
reporting/             Figure and HTML report generation
scripts/               Pipeline, batch, merge, and extension packaging tools
extension/             MV3 browser extension
data/                  Website lists, crawl data, processed outputs, tracker lists
docs/                  Reports, extension release notes, privacy policy, reviews
tests/                 Mock data generators and regression tests
```

## Data Modes

- `mock`: synthetic data for fast local validation.
- `real`: default real-study dataset.
- `real_0` through `real_9`: 100-site batch outputs.
- `real_combined`: merged 1000-site study snapshot used by the extension.

Outputs are written under `data/{mode}/` and `reporting/{mode}/`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium firefox
```

For EU-facing consent behavior, run from an EU network or configure an EU proxy in `config.py`.

## Run The Pipeline

Fast validation:

```bash
python -m scripts.run_pipeline --source-mode mock
```

Single real-study run:

```bash
python -m scripts.run_pipeline \
  --source-mode real \
  --websites-csv data/websites.csv \
  --run-id real-study-001
```

Resume an interrupted run:

```bash
python -m scripts.run_pipeline --source-mode real --resume --run-id real-study-001
```

Batch workflow for the 1000-site study:

```bash
./scripts/run_batches.sh 0        # run one batch
./scripts/run_batches.sh 0 9      # run all batches
./scripts/run_batches.sh merge    # merge and generate combined outputs
```

Regenerate combined reports from existing processed data:

```bash
python -m scripts.run_pipeline \
  --source-mode real_combined \
  --websites-csv data/websites_combined.csv \
  --steps metrics,dp,cmp,comparison,visualize,report \
  --run-id combined-1000
```

## Browser Extension

The `extension/` directory contains a local, user-initiated Chrome/Firefox audit tool. It analyzes the active tab, does not crawl in the background, does not auto-click banners, and does not transmit browsing data.

Build release packages:

```bash
python -m scripts.package_extension_release
```

Release archives are written to `dist/extension-release/`.

## Key Outputs

- `data/{mode}/processed/compliance_scores.csv`
- `data/{mode}/processed/aggregate_metrics.json`
- `data/{mode}/processed/pets_effectiveness.csv`
- `data/{mode}/processed/dp_aggregate_metrics.json`
- `data/{mode}/processed/cmp_comparison.csv`
- `data/{mode}/processed/pets_summary.json`
- `reporting/{mode}/figures/*.png`
- `reporting/{mode}/compliance_report.html`

## Tests

```bash
pytest
```

## Notes

- Detailed methodology and deliverable material live in `docs/`.
- Generated study artifacts are intentionally kept separate by source mode.
- The extension uses the frozen `real_combined` study context as local reference data.
