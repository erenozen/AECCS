# AECCS Project Status

_Last updated: March 1, 2026_

## Status Summary

AECCS is currently a working implementation with a fully reproducible mock/demo
dataset and a prepared real-study pipeline. The project is not yet empirically
complete because the real-study outputs under `data/real/` have not been
generated.

## What Is Done

- Modular crawler, classifier, dark-pattern detector, scorer, metrics engine,
  PET evaluator, CMP analysis, DP reporting, visualization, and HTML reporting
  are implemented.
- Dataset separation exists for `mock`, `real`, and `legacy` outputs.
- Provenance fields are carried through the active processed artifacts.
- Draft academic deliverables exist in `docs/`.
- Automated validation tests are present and passing.

## Current Demo Findings

These findings come from `data/mock/processed/` and are not final study claims:

- 20 mock sites total
- 19 successful crawls
- 1 failed crawl
- 84.2% pre-consent tracker violation rate
- 75.0% of sites show at least one dark pattern
- 50.8 / 100 average compliance score
- Brave Shields is the strongest browser PET in the mock data
- Didomi is the strongest CMP in the mock data
- Differential privacy recommendation: epsilon 2.0

## What Is Still Missing

- Real crawl execution into `data/real/raw/`
- Real PET execution into `data/real/processed/`
- Regeneration of all final real-study artifacts from `data/real/processed/`
- Replacement of draft report/presentation content with real findings

## Deliverable Decision

The project does not need a scope extension. It already covers the proposal and
course deliverables in architecture and feature scope. The remaining gap is
execution quality and final artifact replacement with real-study outputs.

## Operational Entry Point

Use the unified pipeline runner to execute a shared-run workflow:

```bash
python -m scripts.run_pipeline --source-mode mock
python -m scripts.run_pipeline --source-mode real --run-id real-study-001
```

The runner writes a manifest to `data/{source_mode}/processed/run_manifest.json`
so interrupted runs can be resumed consistently.
