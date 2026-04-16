# AECCS Grading System Review (April 2026)

## Scope

This review covers both extension-facing scores:

1. `GDPR Compliance Score`
2. `Post-Interaction State Score`

The review optimized for legal fidelity first and kept the `A/B/C/D/F` cutoffs fixed unless they proved clearly indefensible. The cutoffs were not changed.

## Sources Reviewed

Primary legal and regulatory guidance:

- GDPR Article 7 (conditions for consent): https://eur-lex.europa.eu/eli/reg/2016/679/oj
- EDPB Guidelines 05/2020 on consent: https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-052020-consent-under-regulation-2016679_en
- EDPB cookie banner taskforce report: https://www.edpb.europa.eu/our-work-tools/our-documents/report/report-work-undertaken-cookie-banner-taskforce_en
- ICO guidance on managing consent in practice: https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-the-use-of-storage-and-access-technologies-1/how-do-we-manage-consent-in-practice/
- CNIL guidance on cookies and trackers: https://www.cnil.fr/en/cookies-and-other-tracking-devices-cnil-publishes-new-guidelines-and-recommendations

Primary research already referenced by AECCS:

- Nouwens et al., *Dark Patterns after the GDPR*: https://dl.acm.org/doi/10.1145/3313831.3376321
- Matte et al., *Do Cookie Banners Respect My Choice?*: https://hal.inria.fr/hal-03121467
- Bollinger et al., *Automating Cookie Consent and GDPR Violation Detection*: https://www.usenix.org/conference/usenixsecurity21/presentation/bollinger

AECCS local evidence:

- `shared_constants.py`
- `extension/lib/scorer.js`
- `analysis/scoring.py`
- `data/real_combined/processed/compliance_scores.csv`
- `data/real_combined/processed/*_score.json`

## Current Model Assessment

### What already makes sense

- The system is directionally sound. It emphasizes the right families of risk:
  - tracking before consent
  - reject-path availability and friction
  - dark patterns
  - post-reject enforcement
  - transparency
- The post-interaction score is also directionally sound because it separates current technical state from the baseline banner audit.

### What was unfair

Two fairness issues were strong enough to justify an update:

1. The baseline score treated missing post-reject evidence as a hard zero.
   - In the live extension baseline audit, AECCS usually has banner evidence but not verified post-reject evidence yet.
   - That meant `post_reject_compliance` could consume 15% of the score even when the audit had not observed a reject flow at all.
   - In practice, this made the baseline score partly reflect missing evidence rather than proven non-compliance.

2. The post-interaction score underweighted honesty relative to raw load.
   - `claimed_action_honesty` was only `0.15`, while `low_tracker_load` alone was `0.45`.
   - That could make restrictive outcomes look overly strong just because the page was technically quiet, even when honesty evidence was only partial.

### Local evidence from `data/real_combined`

- Scored sites: `861`
- Mean baseline score: `27.44`
- Median baseline score: `21.5`
- Grade distribution:
  - `A: 1`
  - `B: 7`
  - `C: 83`
  - `D: 75`
  - `F: 695`

Criterion means in the combined real dataset:

- `no_pre_consent_trackers`: `31.8`
- `reject_option_available`: `18.58`
- `equal_accept_reject_effort`: `22.76`
- `no_dark_patterns`: `58.58`
- `post_reject_compliance`: `6.79`
- `transparent_information`: `25.48`

Average weighted contributions under the old baseline model:

- `no_pre_consent_trackers`: `7.95`
- `reject_option_available`: `3.72`
- `equal_accept_reject_effort`: `3.41`
- `no_dark_patterns`: `8.79`
- `post_reject_compliance`: `1.02`
- `transparent_information`: `2.55`

This supports two conclusions:

- `post_reject_compliance` was contributing very little on average because it was usually scored as zero.
- `no_pre_consent_trackers` is the most important technical-consent signal, but it was not the strongest contributor in practice.

## Candidate Models Tested

Three candidate baseline recalibrations were checked against `data/real_combined`:

1. **Evidence-only fix**
   - Keep old weights.
   - Make unverified `post_reject_compliance` become `n/a` with weight redistribution.
2. **Legal reweight**
   - Increase `no_pre_consent_trackers`.
   - Reduce `equal_accept_reject_effort`.
   - Keep `post_reject_compliance` important when verified.
3. **Strong enforcement**
   - Heavier shift toward pre-consent enforcement and away from UI factors.

Result:

- Evidence-only fix improved fairness but did not correct the underweighting of pre-consent enforcement.
- Strong enforcement overcorrected and collapsed too many sites into `D`/`F`.
- The legal reweight was the best fit: it improved the model without making the distribution unstable.

## Adopted Policy

### Baseline `GDPR Compliance Score`

Updated weights:

- `no_pre_consent_trackers`: `0.30`
- `reject_option_available`: `0.20`
- `equal_accept_reject_effort`: `0.10`
- `no_dark_patterns`: `0.15`
- `post_reject_compliance`: `0.15`
- `transparent_information`: `0.10`

Semantic change:

- `post_reject_compliance` is now `n/a` when no verified post-reject evidence exists.
- Its weight is redistributed across the remaining scored criteria.
- It still scores `0` when AECCS can prove there is no reject path or that a verified reject failed.

Rationale:

- Pre-consent tracking is the clearest technical violation and now carries more weight.
- Equal-effort still matters, but it overlaps partly with reject availability and dark-pattern analysis.
- Post-reject enforcement remains important, but missing evidence should not count as failure.

### `Post-Interaction State Score`

Updated weights:

- `low_tracker_load`: `0.35`
- `low_third_party_load`: `0.20`
- `low_total_cookie_load`: `0.10`
- `claimed_action_honesty`: `0.35`

Rationale:

- For restrictive actions like reject or essential-only, honesty should matter at least as much as raw tracker load.
- Total cookie count is a weak legal signal compared with trackers, third-party load, and honesty.
- The score still renormalizes when honesty is `n/a` for `accept` and `unknown` actions.

## Bottom Line

### Does the grading system make sense?

Yes. The AECCS model is conceptually sound and targets the right failure modes.

### Are the old weights fair?

Partly. They were directionally reasonable, but not fully fair:

- the baseline model over-penalized missing post-reject evidence
- the post-interaction model underweighted honesty for restrictive outcomes

### Should AECCS update the grading model?

Yes.

Recommended action:

- keep the grade cutoffs
- update both weight sets
- treat unverified post-reject compliance as `n/a` rather than automatic zero

That is the policy adopted in this revision.
