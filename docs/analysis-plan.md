# Analysis plan

Fixed before the outcomes are seen. After extraction starts, any change is added to [decisions.md](decisions.md)
with its date and reason, and anything not listed here is reported as exploratory. Field names refer to
[extraction-spec.md](extraction-spec.md).

The analysis is statistical: the aim is to explain which kinds of submission get larger revisions, with effect
sizes and uncertainty. Prediction is used only to check how much those features explain. Results are
associations, not causal effects.

**Contents**
1. [Questions and outcomes](#1-questions-and-outcomes)
2. [Hypotheses](#2-hypotheses)
3. [Features in the model](#3-features-in-the-model)
4. [Q1 and Q2: description](#4-q1-and-q2-description)
5. [Q1: models](#5-q1-models)
6. [Q3: extraction reliability](#6-q3-extraction-reliability)
7. [Sensitivity analyses](#7-sensitivity-analyses)

## 1. Questions and outcomes

| question | asks | outcome |
|---|---|---|
| Q1 Revision | How large is the revision, what kind of submission gets a larger one, and how much of the price cut does it account for? | Main: `log_ratio`. Secondary: `large_revision`, `crossed_threshold`. Price-cut split |
| Q2 Mechanism | How much comes from costs vs QALYs, and from each type of agency change? | Cost vs QALY split; stepwise category contributions |
| Q3 Method | How reliable is LLM extraction from HTA reports? | Agreement between extractors; automatic check results |

The secondary outcomes are coarser than the ratio, so they are less sensitive to noise in its exact size, and they
keep the `sponsor_dominant` reviews the ratio loses. If all three point the same way, the findings hold up.

## 2. Hypotheses

Stated before extraction. **Weaker evidence goes with larger revisions.** In the main model, each is a ratio
exp(β) > 1 against the reference level:

| | feature | comparison | pilot median ratio (39 reviews) |
|---|---|---|---|
| H1 | `primary_endpoint_type` | `response_or_surrogate` vs `os` | 2.82× vs 1.51× |
| H2 | `comparator_type` | `bsc_or_no_treatment` vs `active_drug` | 2.48× vs 1.60× |
| H3 | `pivotal_design` | `single_arm` or `observational` vs `rct_h2h` | coded but not split in the pilot; from the literature |

- Each is tested with a two-sided 95% CI. With three hypotheses, p-values are also reported with a Holm correction.
- H1 and H2 came from the pilot, whose reviews are part of the full cohort, so they are not independent tests. A
  sensitivity analysis refits the model without the 60 pilot reviews.
- In the pilot these features overlap with stream (oncology vs not). Stream stays in the model, so each effect is
  estimated within stream; wide intervals are expected and reported as such.
- Every other feature effect is exploratory.

## 3. Features in the model

Where each one comes from: **[P]** a published paper ([literature.md](literature.md)), **[D]** seen in CDA-AMC
documents, **[K]** domain knowledge. Reference levels and merges of sparse levels are set after the precision
check, before the full run.

| feature | why | pilot |
|---|---|---|
| `stream` | [P] | 60/60 |
| `therapeutic_group` | [P] | 60/60 |
| `rare_disease` | [P], one descriptive study (Balijepalli 2024). Mainly a control: rare diseases tend to have the weaker evidence behind H1–H3, so including it separates rarity from weak evidence | coded inconsistently; now set from prevalence |
| `pivotal_design` | [P][K] (H3) | 60/60 |
| `comparison_method` | [P] | 60/60 |
| `primary_endpoint_type` | [P] (H1) | 60/60 |
| `comparator_type` | [P] (H2) | 60/60 |
| `n_comparators_sponsor` | [K] | 58/60 |
| `model_type` | [K] | 60/60 |
| `time_horizon_years` | [P] | 53/60 |
| `followup_months` | [K] | 32/60 |
| `os_median_reached_trt` | [P][K], oncology only | 23/60 |
| `treatment_specific_utilities` | [K] | 13/60 |
| `resubmission` | [P] | inconsistent |
| `year` | [K] | 60/60 |
| `log_sponsor_icer` | [K]; tied to the outcome by construction (regression to the mean), so models are fitted with and without it | from the outcome |

## 4. Q1 and Q2: description

- Median revision ratio with IQR and a bootstrap 95% CI, overall and by stream and year.
- Counts for every `ratio_status`, so excluded reviews stay visible.
- How excluding the `sponsor_dominant` reviews shifts the median.
- Price-cut split, as medians and distributions. Cuts grouped as <50 / 50–75 / ≥75%, matching CDA-AMC's bands.
- Cost vs QALY split, as medians and distributions.
- Stepwise category contributions.

## 5. Q1: models

**Main model.** Linear regression of `log_ratio` on the features in §3.
- Each coefficient reported as exp(β), the ratio of typical revisions with and without the feature, with a 95% CI.
- About one parameter per 10 reviews: categories with fewer than 10 reviews are merged before fitting.
- Year as a covariate. Standard errors clustered by drug, since one molecule can appear in several reviews.
- Fitted with and without `log_sponsor_icer`.

**Secondary models.** Logistic regression for `large_revision` and `crossed_threshold`, reported as odds ratios
with 95% CIs. These include the `sponsor_dominant` reviews.

**Missing data.** Multiple imputation by chained equations, 20 imputations, with the outcome in the imputation
model. `unclear` codes are treated as missing. Complete-case analysis as a sensitivity check.

**How much is explained.**
- Repeated 10-fold cross-validation (20 repeats) of the main model: out-of-sample R² and median absolute error on
  the log scale, against a baseline that always predicts the median.
- A random forest or gradient-boosting model in the same cross-validation, as a check for nonlinearity and
  interactions. If it clearly beats the regression, the interactions it uses are explored; it does not replace
  the main model.

## 6. Q3: extraction reliability

- Agreement between the two extraction passes, per field: Cohen's κ for categorical fields, exact match within
  ±1% for numbers.
- What the adjudicator decided: pick A, pick B, corrected value, `ambiguous`.
- How many records fail each automatic check.
- If done, the hand check of the outcome fields on 15 random reviews.

## 7. Sensitivity analyses

- Drop records with `icer_type_mismatch`, `icer_basis = sequential` (the agency's frontier can include cheap,
  rarely used comparators; Lachaine 2025), `range_only`, or any failed automatic check.
- Use `agency_icer_headline` in place of `agency_icer` where they differ.
- Refit without the 60 pilot reviews (§2).
- Complete-case analysis (§5).
