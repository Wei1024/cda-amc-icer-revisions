# Codebook v1: CDA-AMC ICER revision project

Consolidates the pilot's two extraction prompts and the decision rules that came out of the 60-review pilot ([pilot-findings.md](pilot-findings.md)). Each feature lists where its hypothesis comes from: **[P]** a published paper ([literature.md](literature.md)), **[D]** observed in CDA-AMC documents, **[K]** domain knowledge.

## 1. Unit of analysis and inclusion
- **Unit:** one CDA-AMC reimbursement review, i.e. one project number (one drug × indication).
- **Include:** recommendation dated 2020-01-01 to 2025-12-31 and project prefix `SR` (non-oncology, CDEC) or `PC` (oncology, pERC). That is 407 listing rows and 404 unique reviews (three oncology reviews are listed twice; the listing step merges them).
- **Exclude:** PH (provisional funding algorithms), PX, PG, SX, SG, ST, SF, TS. They are not standard sponsor submissions.
- **Documents:** the Recommendation, plus the economic or combined clinical+economic report. Choose them with `icer_revisions.documents.pick_docs`; for pre-2022 pCODR reviews this is the "EGR" (Economic Guidance Report).

## 2. Target

**Revision ratio = agency base-case ICER ÷ sponsor base-case ICER. The model uses log(ratio).**

Defined only when both ICERs are positive point estimates for the **same comparator**. Otherwise the review gets a `ratio_status` and is reported descriptively, not dropped silently.

| field | definition |
|---|---|
| sponsor_icer, sponsor_icer_status | Sponsor's submitted base case. Status: `point`, `dominant`, `dominated`, `redacted`, `range_only`, `not_reported` |
| agency_icer, agency_icer_status | CADTH/CDA-AMC base case. Same codes, plus `no_reanalysis` and `lower_bound` |
| comparator | The comparator both ICERs refer to |
| analysis_type | `cost_utility`, `cost_minimization`, `cost_comparison`, `none`, `unclear` |

**Decision rules (from the pilot):**
1. **Primary comparator** = the one the Recommendation's price condition is based on. Failing that, the most relevant Canadian comparator. Failing that, the first one listed. Use the same comparator for the sponsor and agency values.
2. **Deterministic vs probabilistic:** use the **probabilistic** base case when the agency reports it as its base case (usually), and the matching sponsor figure. Record which one in `icer_type`.
3. **Scenarios never count as a base case.** If the agency has only exploratory or scenario results, set `no_reanalysis`. If it gives a range, set `range_only` and put the lower end in the number field. In both cases also record the headline figure in `agency_icer_headline`, for a sensitivity analysis.
4. **Sponsor-corrected models** (the agency fixing errors in the sponsor's model) are not the sponsor base case.
5. **Multiple populations:** use the reimbursement-request population, or the one the price condition refers to. Note the others.
6. **Sequential or fully incremental ICERs:** use the ICER against the next relevant comparator. Note this in `notes`.
7. **Different comparators for sponsor and agency** (e.g. abemaciclib, PC0400/PC0409): `ratio_status = comparator_mismatch`. Exclude from the model.

## 3. Decomposition fields (same comparator as the target)

| field | definition |
|---|---|
| inc_cost_sponsor, inc_qaly_sponsor | Sponsor base-case incremental cost ($) and QALYs |
| inc_cost_agency, inc_qaly_agency | Agency base-case incremental cost and QALYs |
| inc_derived | True if computed from total costs/QALYs rather than stated directly |

log(ratio) = log(ΔC_agency / ΔC_sponsor) − log(ΔQ_agency / ΔQ_sponsor). **Check:** ΔC ÷ ΔQ must reproduce each ICER within ±2% (rounding); flag the row if it doesn't.

## 4. Stepwise reanalysis

| field | definition |
|---|---|
| has_stepwise_table | True if the agency reports per-change or cumulative ICERs |
| stepwise_type | `cumulative` (each step builds on the last) or `individual` (each change applied alone) |
| steps | A list of {`order`, `description` (≤ 15 words), `category`, `icer_after`}. Category is one of: `extrapolation_survival`, `treatment_effect_waning`, `utilities`, `time_horizon`, `comparator`, `drug_costs_wastage_dosing`, `treatment_duration`, `other_costs`, `population`, `model_structure_error`, `other` |

The contribution of each category is computed afterwards in code, never by the LLM. These are agency-side fields, used **only** for the descriptive analysis, never as model features.

## 5. Features (sponsor-side, known before the decision)

**Leakage rule:** a feature must be something the sponsor could have known on the day it submitted. Extract descriptions of the trial and the sponsor's model. Never the agency's judgement ("CDA-AMC considered X implausible").

| feature | type / codes | source | pilot availability | rules |
|---|---|---|---|---|
| stream | `onc` / `non_onc` from the project prefix | [P] | 60/60 | From the listing, no extraction needed |
| therapeutic_group | coarse 4–6 groups | [P] | 60/60 | Map from the listing's free text, in code |
| rare_disease | bool | [P] HTA67 | inconsistent | Take from an external source (CDA-AMC rare-disease designation or the listing), not from the text |
| pivotal_design | `rct_h2h`, `rct_placebo_or_other`, `single_arm`, `observational`, `mixed`, `unclear` | [P][K] | 60/60 | **A placebo-plus-backbone trial vs a backbone-only comparator counts as `rct_h2h`.** Placebo vs BSC/watch-and-wait counts as `rct_h2h` |
| comparison_method | `direct`, `itc_nma`, `naive`, `assumption`, `unclear` | [P] | 60/60 | Code it for the primary comparator only. If the sponsor ran an NMA but the model uses a naive comparison, code `naive` |
| primary_endpoint_type | `os`, `pfs_or_efs`, `response_or_surrogate`, `clinical_scale`, `other`, `unclear` | [P] | 60/60 | **Co-primary OS + PFS → `os`.** Response indices (IGA, HiSCR, SRI) → `clinical_scale`. Lab or biomarker response → `response_or_surrogate`. Composite event endpoints → `other` |
| followup_months | number | [K] | 32/60 | **Median follow-up only**, from the data cut used in the model. Record trial duration separately in `trial_duration_months` |
| os_median_reached_trt | bool | [P][K] | 23/60 | Oncology only; null otherwise |
| time_horizon_years | number | [P] | 53/60 | "Lifetime" with no stated years: null, with `lifetime_unspecified = true` |
| model_type | `partitioned_survival`, `markov_or_state_transition`, `decision_tree`, `microsimulation`, `other`, `unclear` | [K] | 60/60 | Decision tree followed by Markov → `markov_or_state_transition` |
| comparator_type | `active_drug`, `bsc_or_no_treatment`, `mixed_basket`, `unclear` | [P] | 60/60 | |
| n_comparators_sponsor | int | [K] | 58/60 | |
| treatment_specific_utilities | bool | [K] | 13/60 | Code only if stated explicitly; expect many nulls |
| resubmission | bool | [P] | inconsistent | **True only if the same drug and indication was reviewed before** (a "previously reviewed: yes" line or a resubmission label). Reconsideration of a draft recommendation is false |
| log_sponsor_icer | number | [K] | from the target | Caution: mechanically linked to the target (regression to the mean). Report models with and without it |
| year | int | [K] | 60/60 | From the listing |
| ~~pct_qaly_after_trial~~ | — | [D] | 27/60, mostly agency-side | **Dropped as a feature** because of leakage and missingness. It may be kept as a descriptive variable if taken from the sponsor's own table |
| ~~perspective_societal_base~~ | — | [D] | 0 variation | **Dropped** |

## 6. Price reduction (part of the revision question)

The price cut is not a separate prediction target. It translates the revision into price terms: how much of
the recommended cut the sponsor's own ICER already implied, and how much the agency's revision added.

| field | definition |
|---|---|
| price_reduction_pct, qualifier | % reduction to reach the threshold. Qualifier: `exact`, `at_least`, `greater_than`, `approximately`, `range` (record the lower end) |
| price_reduction_band | The band label, if the review reports a band (from Nov 2025) |
| price_reduction_status | `pct`, `band`, `not_needed`, `no_pct_specified`, `not_achievable`, `not_reported` |
| wtp_threshold | Usually 50000; record it if different (e.g. 100000 in early 2020) |

**Price-cut split (computed in code, never by the LLM).** With threshold *T*:
- cut implied by the sponsor's ICER = max(0, 1 − *T* / sponsor_icer)
- cut implied by the agency's ICER = max(0, 1 − *T* / agency_icer)
- revision's part = agency-implied cut − sponsor-implied cut

This treats the drug price as the whole incremental cost, so it is an approximation. Report it next to
`price_reduction_pct`, and use the gap between the two as a check (see §8). For descriptive tables, group cuts
as <50 / 50–75 / ≥75%, which matches CDA-AMC's band cut-points.

## 7. Every extracted record also carries
- `evidence`: up to 4 verbatim quotes of 30 words or fewer, for the non-obvious fields.
- `notes`: judgement calls.
- `extractor_id`: the model and prompt version.

## 8. Validation (no full hand-labelled set; see the limitations)
1. Two independent extraction passes, ideally with different models. Report agreement per field: Cohen's κ for categorical fields, exact match within ±1% for numbers.
2. A third LLM adjudicates only the disagreements, with the evidence and source passages. Outcome: pick A, pick B, corrected value, or `ambiguous`.
3. Automatic checks:
   - every number appears verbatim in the source
   - ΔC ÷ ΔQ reproduces the ICER
   - the Recommendation and the economic report agree
   - the price reduction is consistent with the agency ICER and threshold
   - schema validation
4. Optional: hand-check the target fields only (sponsor ICER, agency ICER, comparator) on 15 random reviews.
5. Sensitivity analysis: re-run the models on reviews that pass every check.
