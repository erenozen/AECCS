# AECCS Literature Review

## Problem Area

This project studies whether cookie consent systems actually protect privacy under GDPR-style requirements. The implementation focus is web measurement, consent-banner analysis, and PET evaluation.

## Core References

### 1. Nouwens et al., "Dark Patterns after the GDPR" (2020)

- Main contribution:
  Shows that many cookie banners steer users toward accepting tracking through interface asymmetry and deceptive choice architecture.
- Relevance to AECCS:
  Directly motivates the dark-pattern detection module and the need to compare accept vs reject effort.
- Gap AECCS addresses:
  We automate the banner-side measurements and connect them to tracker behavior after the interaction, not just UI design.

### 2. Matte et al., "Do Cookie Banners Respect My Choice?" (2020)

- Main contribution:
  Demonstrates that many websites do not enforce the choice expressed through consent banners.
- Relevance to AECCS:
  Motivates the pre-consent and post-reject tracking checks in the crawler and scoring modules.
- Gap AECCS addresses:
  We integrate this measurement into a unified end-to-end pipeline that also scores compliance and evaluates PET countermeasures.

### 3. Bollinger et al., "Automating Cookie Consent and GDPR Violation Detection" (2022)

- Main contribution:
  Focuses on automating banner interaction and large-scale GDPR-related measurements.
- Relevance to AECCS:
  Supports the design choice of using browser automation plus structured heuristics.
- Gap AECCS addresses:
  AECCS extends beyond violation detection by adding CMP comparison, browser PET comparison, and DP-protected reporting.

### 4. GDPR Regulation (EU) 2016/679

- Main contribution:
  Provides the regulatory baseline for lawful consent, transparency, and purpose limitation.
- Relevance to AECCS:
  The compliance scoring model maps technical observations to concrete consent properties such as reject availability, symmetry of effort, and absence of pre-consent tracking.

### 5. CNIL Cookie and Tracker Guidance

- Main contribution:
  Clarifies practical expectations around consent, rejection, and non-essential trackers.
- Relevance to AECCS:
  Supports the use of "Reject All" visibility and post-reject enforcement as scoring criteria.

## Key Themes From Prior Work

### Consent banners frequently manipulate choice

Prior studies consistently show that banners often bias users toward accepting tracking. This validates the need for an explicit dark-pattern detector rather than treating the presence of a banner as evidence of compliance.

### Stated consent is often not technically enforced

The core problem is not just UI unfairness. Even when a reject path exists, sites may still contact third-party domains or set trackers. This is why AECCS measures baseline, accept, and reject states separately.

### Scalable web measurement is necessary

Manual review is too slow and too subjective for a meaningful study. Prior work motivates automation, but production-quality pipelines still need strong provenance, reproducibility, and dataset hygiene. That is the main implementation focus of the current project phase.

### PETs matter as a second line of defense

Course context matters here. The project is not only about measuring non-compliance; it is also about testing privacy-enhancing technologies that can reduce exposure when consent systems fail.

## How AECCS Differs

- It combines crawler, classifier, dark-pattern detector, compliance scorer, CMP analysis, browser PET evaluation, and DP reporting in one pipeline.
- It treats PETs as first-class evaluation targets rather than only discussing ethical scraping or anonymization.
- It now separates mock and real outputs to prevent synthetic demonstration data from being confused with final empirical evidence.

## Practical Takeaways For The Final Report

- The report should position AECCS as a measurement-and-evaluation system, not only a banner detector.
- Dark-pattern results should always be paired with technical enforcement results.
- Final claims must be derived only from `data/real/processed/*`.
- Mock findings remain useful only as pipeline validation and report-structure rehearsal.

## References To Include In The Final Report

1. Nouwens, M., et al. "Dark Patterns after the GDPR."
2. Matte, C., et al. "Do Cookie Banners Respect My Choice?"
3. Bollinger, J., et al. "Automating Cookie Consent and GDPR Violation Detection."
4. Regulation (EU) 2016/679 (GDPR).
5. CNIL guidance on cookies and trackers.
