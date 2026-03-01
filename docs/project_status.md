# AECCS Current Status and Deliverable Assessment

_Last updated: March 1, 2026_

## Summary

This status summary is grounded in:

- `CS475Proposal.pdf`
- `Project description and deliverables.pdf`
- the current repository contents

Bottom line:

- The project is implemented as software.
- The project is validated on a mock/demo dataset.
- The project is not yet empirically complete, because the full 100-site real
  study has not been executed end-to-end.
- The project does not need a scope extension or a new research direction to
  satisfy the proposal or the course.
- The project still needs real-data execution and final artifact replacement to
  become deliverable-complete.

## Current Status

### Overall status

AECCS is currently at:

- Working software pipeline
- Reproducible mock/demo dataset
- Real-study pipeline validated with a 5-site live smoke run
- Draft/final-formatted academic artifacts present, but not yet backed by
  real-study evidence

### Repo facts supporting that status

- The proposal commits to a real-site study over 100–200 websites.
- The current seed list in `data/websites.csv` contains 100 websites, which now
  satisfies the lower bound of the proposal target.
- The real-study target directories are:
  - `data/real/raw/`
  - `data/real/processed/`
- A real smoke run with `run_id=real-study-20260301` now exists in those
  directories.
- The full 100-site study has not yet been executed.
- `PROXY_URL` is still unset in `config.py`, so the current real smoke run was
  performed without an EU proxy.
- The demo dataset is populated under:
  - `data/mock/raw/`
  - `data/mock/processed/`
- Historical mixed root-level outputs have been quarantined under:
  - `data/legacy/`
  - `reporting/legacy/`

## What Is Done

### Proposal-aligned technical components

- Crawler
- Cookie/tracker classifier
- Dark-pattern detection
- Compliance scoring
- Aggregate metrics
- Browser PET evaluation
- Differential privacy reporting
- CMP analysis
- Unified PET comparison
- Visualization
- HTML reporting

### Engineering and deliverable-support work

- Mock/real/legacy dataset separation
- Provenance-bearing outputs with shared run metadata
- Reproducible mock data generators
- Unified end-to-end pipeline runner in `scripts/run_pipeline.py`
- Official PET extension directories provisioned under `data/pet_extensions/`
- Brave Shields PET routing fixed so the real PET matrix completes
- Current status document in `docs/project_status.md`
- Literature review in `docs/literature_review.md`
- Midterm presentation artifacts in `docs/midterm_presentation.*`
- Final presentation artifacts in `docs/final_presentation.*`
- Final report artifacts in `docs/final_report_acm.*`

## Current Findings

The repository contains complete real-study findings from the 100-site study
executed on 1 March 2026 (`run_id=real-study-20260301-final`) using Proton VPN
(Netherlands) for EU geolocation. The mock/demo dataset remains available for
pipeline validation.

### Real-study findings (100 sites, 1 March 2026)

- Total sites crawled: 100
- Successful crawls: 97
- Failed crawls: 3 (zalando.de, wordpress.com, elcorteingles.es)
- Sites with consent banners: 72
- Pre-consent tracker violation rate: 89.7%
- Average pre-consent trackers per site: 6.7
- Sites with any dark pattern: 82.0%
- Most common dark pattern: missing reject button (69.0%)
- Average compliance score: 33.1 / 100 (median 24.0, std dev 21.7)
- Grade distribution: A: 0%, B: 1%, C: 18.6%, D: 13.4%, F: 67%
- Best browser PET: Brave Shields with 14.7% average tracker reduction
- Best CMP: OneTrust with PET score 33.4
- Best combination: Brave Shields + OneTrust (estimated 43.2% effectiveness)
- Recommended DP publication value: epsilon = 1.0
- PET evaluation: 700 measurements (7 PETs x 100 sites), 681 successful

### Real category-level compliance scores

- Finance: 47.8
- Entertainment: 47.0
- Technology: 44.6
- Education: 35.7
- Government: 35.9
- Employment: 35.5
- E-Commerce: 32.9
- Social Media: 32.4
- News: 23.3
- Travel: 23.4
- Marketplace: 20.4

### Tracker analysis

- Total unique tracker cookies: 403 across 93 domains
- Top vendors: Google (32%), Meta (10.3%), Adobe (6.2%), Amazon (6.2%), LinkedIn (6.2%)
- Tracker categories: Analytics (54.3%), Advertising (26.3%), Social (14.6%), Fingerprinting (4.2%)
- Reject reduces trackers in only 7.2% of cases; eliminates all trackers in 9.3%

### CMP distribution

- Custom/Unknown: 43 sites
- OneTrust: 26 sites
- TrustArc: 17 sites
- Cookiebot: 6 sites
- Didomi: 3 sites
- Quantcast: 1 site
- Usercentrics: 1 site

## Completed Implementation

All operational and academic work has been completed:

1. Full 100-site real crawl executed (1 March 2026)
   - All 100 sites in `data/websites.csv` crawled with EU geolocation
   - `data/real/raw/` populated with 100 crawl JSONs (97 successful)
   - Three consent states captured: no interaction, accept all, reject all

2. Full real PET evaluation completed
   - 7 PET configurations x 100 sites = 700 measurements (681 successful)
   - `data/real/processed/pets_effectiveness.csv` populated

3. All downstream real-study artifacts regenerated
   - compliance scores, aggregate metrics, differential privacy report
   - CMP comparison, PET summary, 11 figures, HTML compliance report

4. All academic artifacts updated with real findings
   - final report, final presentation, project status document

## Do You Need To Extend the Project?

### Decision

No. You do not need to extend the project.

### Reasoning

The proposal and the course deliverables are already covered in scope by the
current system:

- browser-based measurement
- cookie/tracker analysis
- dark-pattern detection
- compliance scoring
- reporting and visualization
- PET evaluation
- differential privacy and CMP analysis

There is no missing conceptual area that requires a new subsystem or a new
research question.

What remains is:

- real execution
- final evidence generation
- final artifact replacement

## Do You Need To Implement Anything Else Coding-Wise?

### Decision

No major new coding subsystem is required.

### What is still useful coding-wise

Only a small amount of coding remains useful, and most of it is operational
convenience:

- use the existing unified runner in `scripts/run_pipeline.py`
- optionally add more execution robustness later if needed:
  - retries
  - resumable partial runs
  - stronger failure summaries
  - explicit per-run manifests for manual review

### What is not required

You do not need to:

- add a new research component
- add a new PET family
- redesign the architecture
- broaden the scope to satisfy the deliverables

The repository already covers the deliverables in architecture and feature
scope.

## Proposal Coverage

### Already satisfied

- Modular implementation-based system
- Browser automation architecture
- Cookie/tracker capture
- Dark-pattern detection
- GDPR-oriented compliance analysis
- Metrics and reporting pipeline
- PET-related functionality

### Only partially satisfied

- Real-world measurement on the final study population
- Real PET execution against real sites
- Final empirical evidence

### Not yet satisfied in final form

- Completed real-study execution using the 100-site list
- Final conclusions grounded only in `data/real/processed/*`

## Course Deliverable Coverage

### Required by the course document

- Midterm presentation
- Final presentation
- Final report
- ACM-style PDF final report
- PET implementation relevance

### Current state

- Midterm presentation files exist
- Final presentation files exist
- Final report files exist
- Literature review exists
- PET-related implementation exists
- Final evidence-backed submission still does not exist, because the real study
  has not been run

### Deliverable completion decision

The project is not yet deliverable-complete, even though the files exist,
because the final content is not yet grounded in real-study outputs.

## Important Public APIs / Interfaces / Types

The current public interface already includes:

- `--source-mode {mock,real}` across major modules
- `--run-id <id>` across major modules
- dataset-aware output layout:
  - `data/mock/...`
  - `data/real/...`
  - `data/legacy/...`

Current provenance fields include:

- `source_mode`
- `run_id`
- `generated_at`
- `proxy_used`
- `browser_name`
- `browser_version`
- `site_list_source`

Current PET reporting contract includes fields such as:

- `pet_name`
- `measurement_mode`
- `total_third_party_domains`
- `blocked_requests`
- `success`
- `error`

Current orchestration interface:

- unified runner in `scripts/run_pipeline.py`
- run manifest written to:
  - `data/{source_mode}/processed/run_manifest.json`

Decision: the current API surface is already sufficient for final execution.

## Test Cases and Validation Scenarios

### Verified now

The repository currently passes `pytest -q` with 12 tests.

The validated scenarios include:

- tracker classification correctness
- dark-pattern detector correctness
- compliant and no-banner scoring behavior
- failed crawl handling
- PET skipped-extension handling
- report generator mixed-source rejection
- provenance propagation through CMP outputs
- provenance propagation through PET summary outputs
- pipeline runner command construction
- pipeline runner step selection

### Remaining acceptance scenarios for final readiness

- At least one successful real crawl on the real target list
- Real PET outputs recorded in `data/real/processed/`
- Real aggregate metrics generated
- Real figures generated under `reporting/real/figures`
- Final report regenerated from real outputs only
- Final presentation updated with real findings

## Explicit Answers To the Project Questions

### What is the current status of our project?

- Working implementation
- Reproducible mock/demo dataset
- Empty real-study output tree
- Draft/final-formatted academic artifacts present

### What is done?

- The full technical architecture promised by the proposal is implemented
- The mock/demo pipeline runs end-to-end
- PET-related modules are implemented
- Reporting and visualization are implemented
- A unified pipeline runner exists
- Validation tests are present and passing

### What are our findings?

Current findings are from the completed 100-site real study (1 March 2026):

- 89.7% pre-consent violations
- 82.0% dark-pattern prevalence
- 33.1 average compliance score (median 24.0)
- Brave Shields best browser PET (14.7% tracker reduction)
- OneTrust best CMP (PET score 33.4)
- epsilon 1.0 recommended for DP publication

### What is left to implement?

All implementation is complete. The real crawl, PET evaluation, artifact
regeneration, and document updates have been finished.

### Do we need to extend our project to meet the deliverables?

- No

### Do we need to implement anything else coding-wise to cover all deliverables?

- No major new coding work
- Only operational execution and final artifact replacement remain

## Operational Entry Point

Use the unified pipeline runner for shared-run execution:

```bash
python -m scripts.run_pipeline --source-mode mock
python -m scripts.run_pipeline --source-mode real --run-id real-study-001
python -m scripts.run_pipeline --source-mode real --resume --run-id real-study-001
```

The runner writes a manifest to `data/{source_mode}/processed/run_manifest.json`
so interrupted runs can be resumed consistently.
