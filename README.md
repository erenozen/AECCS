# AECCS — Assessing the Effectiveness of Cookie Consent Systems

An automated analysis of GDPR compliance and privacy risks on popular EU-targeted websites. This system crawls 100–200 websites using headless browser automation, captures cookies and trackers before and after interacting with cookie consent banners, detects dark patterns, computes GDPR compliance scores, and evaluates the effectiveness of browser-based Privacy-Enhancing Technologies (PETs) at reducing tracking.

## Team Members

- Member 1 (placeholder)
- Member 2 (placeholder)
- Member 3 (placeholder)

## Prerequisites

- **Python 3.10+**
- **Playwright browsers** (Chromium and Firefox)
- **EU VPN or proxy** — Required so that websites serve their GDPR-compliant cookie banners. Configure the proxy URL in `config.py`.

## Installation

```bash
# Clone the repository
git clone <repo-url> && cd AECCS

# Create a virtual environment (recommended)
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium firefox
```

## Project Structure

```
AECCS/
├── scraper/                  # Website crawling and consent banner interaction
│   ├── __init__.py
│   └── crawler.py
├── analysis/                 # Cookie classification, compliance scoring, metrics
│   ├── __init__.py
│   ├── classifier.py
│   ├── scoring.py
│   └── metrics.py
├── dark_patterns/            # Dark pattern detection in consent banners
│   ├── __init__.py
│   └── detector.py
├── pets_evaluation/          # PET effectiveness evaluation
│   ├── __init__.py
│   ├── browser_pets.py       # Browser extension PET testing
│   ├── dp_reporting.py       # Differential privacy reporting
│   ├── cmp_analysis.py       # Consent Management Platform analysis
│   └── comparison.py         # Unified PET comparison
├── reporting/                # Visualization and report generation
│   ├── __init__.py
│   ├── visualize.py
│   └── figures/              # Generated plots
├── data/
│   ├── raw/                  # Raw crawl data
│   │   ├── screenshots/      # Page screenshots
│   │   └── banners/          # Saved consent banner HTML
│   ├── processed/            # Classified and scored data
│   ├── tracker_lists/        # EasyList, EasyPrivacy, Disconnect, WhoTracksMe
│   └── websites.csv          # Target website list
├── docs/                     # Documentation
├── config.py                 # Central configuration
├── requirements.txt          # Python dependencies
├── .gitignore
└── README.md
```

## Usage

Each module can be run independently. The overall pipeline order is:

1. **Crawling** (`scraper/crawler.py`) — See Phase 1 implementation
2. **Classification** (`analysis/classifier.py`) — See Phase 2 implementation
3. **Dark pattern detection** (`dark_patterns/detector.py`) — See Phase 2 implementation
4. **Compliance scoring** (`analysis/scoring.py`) — See Phase 3 implementation
5. **Aggregate metrics** (`analysis/metrics.py`) — See Phase 3 implementation
6. **PET evaluation** (`pets_evaluation/browser_pets.py`) — See Phase 4 implementation
7. **Differential privacy** (`pets_evaluation/dp_reporting.py`) — See Phase 4 implementation
8. **CMP analysis** (`pets_evaluation/cmp_analysis.py`) — See Phase 4 implementation
9. **PET comparison** (`pets_evaluation/comparison.py`) — See Phase 5 implementation
10. **Visualization** (`reporting/visualize.py`) — See Phase 5 implementation

## Website List

The file `data/websites.csv` contains the target websites for crawling. It ships with ~12 example EU-targeted sites across categories (e-commerce, news, social media, government, entertainment, education, tech).

To build the full list of 100–200 sites:

1. Visit the [Tranco List](https://tranco-list.eu/) and download a recent top-sites ranking.
2. Filter for EU-targeted domains (`.de`, `.fr`, `.nl`, `.co.uk`, `.eu`, `.it`, `.es`, etc.) and popular global sites that serve EU users.
3. Categorise each domain and add it to `data/websites.csv` with columns: `domain,category,region,rank`.

## Configuration

All project settings are centralised in `config.py`:

| Setting | Description |
|---|---|
| `PROXY_URL` | EU proxy URL for triggering GDPR banners (set your own) |
| `REQUEST_DELAY_RANGE` | Min/max seconds between requests (default 2–5) |
| `PAGE_LOAD_TIMEOUT` | Playwright timeout in ms (default 30000) |
| `CONSENT_BUTTON_KEYWORDS` | Multilingual accept/reject button keywords |
| `CMP_SIGNATURES` | Detection signatures for known CMPs |
| `COMPLIANCE_WEIGHTS` | Scoring weights for the six compliance criteria |
| `PET_CONFIGURATIONS` | Browser PET configurations to evaluate |
| `USER_AGENTS` | Realistic user-agent strings for rotation |

## License

TBD
