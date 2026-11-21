# Extraction spec

What the extraction pipeline reads, what it produces for each review, the rules for hard cases, and how we
decide it works. Build from this file. The analysis that uses the data is in [analysis-plan.md](analysis-plan.md),
and the reasons behind each choice are in [decisions.md](decisions.md).

**Still open:** which models extract and adjudicate, the schema format, batching, and cost. Page selection is
being designed (§1).

**Contents**
1. [Inputs](#1-inputs)
2. [Output: one record per review](#2-output-one-record-per-review)
3. [Rules for hard cases](#3-rules-for-hard-cases)
4. [Computed in code, not by the LLM](#4-computed-in-code-not-by-the-llm)
5. [Checks and the pass bar](#5-checks-and-the-pass-bar)

## 1. Inputs

| | what | status |
|---|---|---|
| Reviews | One record per CDA-AMC project number (one drug × indication). Recommendation dated 2020-01-01 to 2025-12-31, prefix `SR` (non-oncology) or `PC` (oncology): **404 reviews** (407 listing rows; three oncology reviews are listed twice and merged). Other prefixes (PH, PX, PG, SX, SG, ST, SF, TS) are not standard sponsor submissions and are excluded. | Done: `uv run icer cohort` |
| Documents | The Recommendation, and the economic or combined clinical + economic report (for pre-2022 pCODR reviews, the Economic Guidance Report). When the economic report covers economics only (78 reviews, 2020–2021), also the separate clinical report, which is the source of the trial fields. Chosen by `icer_revisions.documents`; see [data-sources.md](data-sources.md). | Done: `uv run icer download` |
| Pages | The pages that hold the fields below, sent to the LLM as PDF pages or images so tables keep their layout. The text layer is kept for checking quotes. | Being designed; replaces the text excerpts from the pilot |

## 2. Output: one record per review

Fields are grouped by what they are for. "Pilot" is how many of the 60 pilot reviews had the field; low counts
mean nulls are expected, not that the extractor failed.

### 2.1 The two ICERs (the outcome)

| field | values | notes |
|---|---|---|
| `sponsor_icer` | number ($/QALY) | The sponsor's base case. Which one: rule 5 |
| `sponsor_icer_status` | `point`, `dominant`, `dominated`, `redacted`, `range_only`, `not_reported` | |
| `agency_icer` | number ($/QALY) | CDA-AMC's base case. Point estimate over range: rule 4 |
| `agency_icer_status` | as above, plus `no_reanalysis`, `lower_bound` | |
| `agency_icer_range_low`, `agency_icer_range_high` | number | Only if the agency gives a range |
| `agency_icer_headline` | number | The figure the Recommendation leads with, only if it differs from `agency_icer` |
| `comparator` | text | The one comparator both ICERs refer to: rule 1 |
| `icer_type` | `probabilistic`, `deterministic` | Rule 2 |
| `icer_type_mismatch` | bool | Rule 3 |
| `icer_basis` | `pairwise`, `sequential` | Rule 7 |
| `sponsor_version` | `original`, `revised` | Rule 5 |
| `analysis_type` | `cost_utility`, `cost_minimization`, `cost_comparison`, `none`, `unclear` | |
| `ratio_status` | `ok`, `sponsor_dominant`, `agency_dominant`, `no_reanalysis`, `range_only`, `comparator_mismatch`, `redacted`, `not_cost_utility`, `not_reported` | Why a review has no usable ratio. Every review gets one; none are dropped silently |

### 2.2 Costs and QALYs (same comparator as the ICERs)

| field | values | notes |
|---|---|---|
| `inc_cost_sponsor`, `inc_qaly_sponsor` | number | Sponsor's incremental cost ($) and QALYs |
| `inc_cost_agency`, `inc_qaly_agency` | number | Agency's incremental cost and QALYs |
| `inc_derived` | bool | True if computed from totals rather than stated |

### 2.3 The agency's stepwise changes

| field | values | notes |
|---|---|---|
| `has_stepwise_table` | bool | The agency reports an ICER after each change |
| `stepwise_type` | `cumulative`, `individual` | Cumulative: each step builds on the last. Individual: each change applied alone |
| `steps` | list of {`order`, `description`, `category`, `icer_after`} | `description` ≤ 15 words. `category` is one of: `extrapolation_survival`, `treatment_effect_waning`, `utilities`, `time_horizon`, `comparator`, `drug_costs_wastage_dosing`, `treatment_duration`, `other_costs`, `population`, `model_structure_error`, `other` |

These describe the agency's critique, so they are used to describe revisions, **never** as model inputs.

### 2.4 Submission features (the model inputs)

**Leakage rule:** a feature must be something the sponsor knew on the day it submitted. Extract descriptions of
the trial and of the sponsor's model, never the agency's judgement of them ("CDA-AMC considered X implausible").
Trial fields come from the clinical section of a combined report, or from the separate clinical report.

| field | values | rule | pilot |
|---|---|---|---|
| `pivotal_design` | `rct_h2h`, `rct_placebo_or_other`, `single_arm`, `observational`, `mixed`, `unclear` | Placebo + backbone vs backbone alone counts as `rct_h2h`. Placebo vs best supportive care or watch-and-wait counts as `rct_h2h` | 60/60 |
| `comparison_method` | `direct`, `itc_nma`, `naive`, `assumption`, `unclear` | For the primary comparator only. If the sponsor ran an NMA but the model uses a naive comparison, code `naive` | 60/60 |
| `primary_endpoint_type` | `os`, `pfs_or_efs`, `response_or_surrogate`, `clinical_scale`, `other`, `unclear` | Co-primary OS + PFS → `os`. Response indices (IGA, HiSCR, SRI) → `clinical_scale`. Lab or biomarker response → `response_or_surrogate`. Composite event endpoints → `other` | 60/60 |
| `comparator_type` | `active_drug`, `bsc_or_no_treatment`, `mixed_basket`, `unclear` | | 60/60 |
| `n_comparators_sponsor` | int | | 58/60 |
| `model_type` | `partitioned_survival`, `markov_or_state_transition`, `decision_tree`, `microsimulation`, `other`, `unclear` | Decision tree followed by Markov → `markov_or_state_transition` | 60/60 |
| `time_horizon_years` | number | "Lifetime" with no years stated: null, and set `lifetime_unspecified = true` | 53/60 |
| `followup_months` | number | Median follow-up only, from the data cut used in the model. Put trial duration in `trial_duration_months` | 32/60 |
| `os_median_reached_trt` | bool | Oncology only; null otherwise | 23/60 |
| `treatment_specific_utilities` | bool | Only if stated explicitly; expect many nulls | 13/60 |
| `resubmission` | bool | True only if the same drug and indication was reviewed before ("previously reviewed: yes", or a resubmission label). Reconsideration of a draft recommendation is false | inconsistent |

**Prevalence (for `rare_disease`).** The LLM copies a number; the rare-disease flag is set in code (§4), so the
definition is the same for every review. Reports flag rarity in no standard way, and a yes/no read from the text
was inconsistent in the pilot ([decisions.md](decisions.md), D15).

| field | values | rule |
|---|---|---|
| `prevalence_value` | number | As stated, before any conversion |
| `prevalence_unit` | `per_100k`, `per_10k`, `per_million`, `percent`, `one_in_n`, `patients` | `one_in_n`: the n in "1 in n". `patients`: a head count |
| `prevalence_kind` | `prevalence`, `incidence`, `eligible_patients` | Prefer prevalence. Use `eligible_patients` only for a count of patients eligible for the drug, and `incidence` only if nothing else is given |
| `prevalence_region` | `canada`, `other`, `not_stated` | Prefer a Canadian figure |

Rules:
- Take it from the description of the disease: the Clinical Review's introduction or disease background, or the
  Recommendation's Background. Never from the committee's deliberation ("the committee considered the rarity of
  the condition").
- It is the prevalence of the population the drug is indicated for (e.g. ROS1-positive NSCLC, not all NSCLC). If
  only the broader disease's figure is given, use it and say so in `notes`.
- A range: record the midpoint and quote the range in `evidence`.
- Nothing stated: leave the fields null.

Not extracted by the LLM (see §4): `stream`, `therapeutic_group`, `year`, `rare_disease`, `log_sponsor_icer`.

### 2.5 Price reduction

| field | values | notes |
|---|---|---|
| `price_reduction_pct` | number | % cut needed to reach the threshold |
| `price_reduction_qualifier` | `exact`, `at_least`, `greater_than`, `approximately`, `range` | For a range, record the lower end |
| `price_reduction_band` | text | The band label, if the review gives one (from November 2025) |
| `price_reduction_status` | `pct`, `band`, `not_needed`, `no_pct_specified`, `not_achievable`, `not_reported` | |
| `wtp_threshold` | number | Usually 50000; record it if different (e.g. 100000 in early 2020) |

### 2.6 On every record

| field | notes |
|---|---|
| `evidence` | Up to 4 verbatim quotes of 30 words or fewer, for the fields that are not obvious |
| `notes` | Judgement calls, and populations or comparators not used (rule 6) |
| `extractor_id` | Model and prompt version |

## 3. Rules for hard cases

Each rule came from a case in the pilot. The numbers are stable; other files refer to them.

**Which figures to take**

1. **Primary comparator.** The one the Recommendation's price condition is based on. Failing that, the most
   relevant Canadian comparator. Failing that, the first one listed. Use the same comparator on both sides.
2. **Probabilistic or deterministic.** Use the probabilistic base case when the agency reports that as its base
   case (usual), and the matching sponsor figure. Record which in `icer_type`.
3. **Types don't match.** If one side reports only one type, use what is reported and set
   `icer_type_mismatch = true`.
4. **Scenarios are never a base case.**
   - Agency reports only exploratory or scenario results: `ratio_status = no_reanalysis`.
   - Agency gives a point estimate **and** a range: use the point estimate, and fill the range fields.
     Example, PC0195: sponsor $157,293; agency point $171,723, range $157,226–$370,710. The point gives a ratio
     of 1.09×; the top of the range would give 2.36×.
   - Agency gives **only** a range: `range_only`. Put the lower end in `agency_icer` and fill both range fields.
   - In every case, fill `agency_icer_headline` if the Recommendation leads with a different figure.
5. **Which sponsor base case.** The last base case the sponsor itself submitted before the agency's reanalysis,
   as the economic report summarises it. If the sponsor revised its model during the review (for example in
   answer to the agency's questions), use the revision and set `sponsor_version = revised`. A model the agency
   corrected is never the sponsor's base case.
6. **Several populations.** Use the reimbursement-request population, or the one the price condition refers to.
   List the others in `notes`.
7. **Sequential or pairwise.** Prefer the pairwise ICER against the primary comparator when both sides report
   one. Otherwise use the sequential (fully incremental) ICER against the next comparator on the frontier, and
   set `icer_basis = sequential`.
8. **Sponsor claims dominance** (cheaper and more effective) and the agency reports a positive ICER:
   `ratio_status = sponsor_dominant`. Still fill every other field; these reviews are used (§4).
9. **Different comparators on the two sides** (e.g. abemaciclib, PC0400/PC0409):
   `ratio_status = comparator_mismatch`.
10. **Several indications or a reconsideration in one project** (e.g. SR0816-000/001): use the indication the
    final Recommendation covers, and the economic report it cites. Still one record per project number.
11. **Units and price.** Cost per QALY only, never per life-year or per responder. Both ICERs at the sponsor's
    submitted price, never at a price the agency proposes.

**Checking the figures**

12. **Stepwise check.** If there is a cumulative stepwise table, its last ICER must match `agency_icer` within
    ±2%. Flag the record if it doesn't.

## 4. Computed in code, not by the LLM

| value | how |
|---|---|
| `ratio`, `log_ratio` | `agency_icer / sponsor_icer`, only when `ratio_status = ok` |
| `large_revision` | ratio ≥ 2. For `sponsor_dominant` reviews: true if the agency ICER is positive |
| `crossed_threshold` | sponsor ICER ≤ T and agency ICER > T, with T = `wtp_threshold`. For `sponsor_dominant` reviews: true if the agency ICER > T |
| Cost vs QALY split | log(ratio) = log(ΔC agency / ΔC sponsor) − log(ΔQ agency / ΔQ sponsor) |
| Price-cut split | sponsor-implied cut = max(0, 1 − T / sponsor ICER); agency-implied cut = max(0, 1 − T / agency ICER); the revision's part is the difference. It treats the drug price as the whole incremental cost, so it is an approximation, reported next to `price_reduction_pct` |
| Contribution of each stepwise category | From `steps` |
| `stream` | `onc` / `non_onc` from the project prefix |
| `year` | From the listing |
| `therapeutic_group` | 4–6 groups, mapped from the listing's free text |
| `rare_disease` | Convert the prevalence fields to cases per 100,000 (a Canadian head count divided by Canada's population in the review year). True if below 50 per 100,000 (1 in 2,000, the threshold usually used in Canada). Null if the only figure is incidence, a head count outside Canada, or none is given. FDA or EMA orphan designation may be used as a cross-check, not as the source |
| `log_sponsor_icer` | From `sponsor_icer` |

## 5. Checks and the pass bar

**Before the full run: the precision check.** Two extractors run independently on about 20 reviews. The bar,
set in advance: **at least 90% agreement** on `sponsor_icer`, `agency_icer`, `comparator` and `ratio_status`.
Below that, the disagreements show which rule is still unclear; fix the rule and run again.

**On the full run**
1. Two independent extraction passes, ideally with different models.
2. A third LLM looks only at the disagreements, with the evidence and source pages. It returns: pick A, pick B, a
   corrected value, or `ambiguous`.
3. Automatic checks; a record that fails one is flagged, not deleted:
   - every extracted number appears verbatim in the source text
   - ΔC ÷ ΔQ reproduces each ICER within ±2%
   - the stepwise table ends at `agency_icer` (rule 12)
   - the Recommendation and the economic report agree
   - the price cut is consistent with the agency ICER and threshold
   - the record passes schema validation
4. Optional: a hand check of `sponsor_icer`, `agency_icer` and `comparator` on 15 random reviews.

There is no full hand-labelled set; agreement and the checks above stand in for it ([decisions.md](decisions.md),
D3). How agreement is reported is in [analysis-plan.md](analysis-plan.md).
