# Codebook v1: CDA-AMC ICER revision project

Consolidates the pilot's two extraction prompts and the decision rules that came out of the 60-review pilot ([pilot-findings.md](pilot-findings.md)). Each feature lists where its hypothesis comes from: **[P]** a published paper ([literature.md](literature.md)), **[D]** observed in CDA-AMC documents, **[K]** domain knowledge.

## 1. Unit of analysis and inclusion
- **Unit:** one CDA-AMC reimbursement review, i.e. one project number (one drug × indication).
- **Include:** recommendation dated 2020-01-01 to 2025-12-31 and project prefix `SR` (non-oncology, CDEC) or `PC` (oncology, pERC). That is 407 listing rows and 404 unique reviews (three oncology reviews are listed twice; the listing step merges them).
- **Exclude:** PH (provisional funding algorithms), PX, PG, SX, SG, ST, SF, TS. They are not standard sponsor submissions.
- **Documents:** the Recommendation, plus the economic or combined clinical+economic report. Choose them with `icer_revisions.documents.pick_docs`; for pre-2022 pCODR reviews this is the "EGR" (Economic Guidance Report).

## 2. Target

**Revision ratio = agency base-case ICER ÷ sponsor base-case ICER. The model uses log(ratio).**

Defined only when both ICERs are positive point estimates for the **same comparator**, in cost per QALY, at the
sponsor's submitted price. Otherwise the review gets a `ratio_status` and is reported descriptively, not dropped
silently.

| field | definition |
|---|---|
| sponsor_icer, sponsor_icer_status | Sponsor's submitted base case. Status: `point`, `dominant`, `dominated`, `redacted`, `range_only`, `not_reported` |
| agency_icer, agency_icer_status | CADTH/CDA-AMC base case. Same codes, plus `no_reanalysis` and `lower_bound` |
| agency_icer_range_low, agency_icer_range_high | The agency's range, if it gives one (with or without a point estimate) |
| agency_icer_headline | The figure the Recommendation leads with, if it differs from `agency_icer` (sensitivity analysis only) |
| comparator | The comparator both ICERs refer to |
| icer_type | `probabilistic` or `deterministic` |
| icer_type_mismatch | True if the sponsor and agency figures are of different types (rule 3) |
| icer_basis | `pairwise` or `sequential` (rule 7) |
| sponsor_version | `original` or `revised`: which sponsor submission the sponsor ICER comes from (rule 5) |
| analysis_type | `cost_utility`, `cost_minimization`, `cost_comparison`, `none`, `unclear` |
| ratio_status | `ok`, `sponsor_dominant`, `agency_dominant`, `no_reanalysis`, `range_only`, `comparator_mismatch`, `redacted`, `not_cost_utility`, `not_reported` |

**Decision rules (from the pilot, tightened after it):**
1. **Primary comparator** = the one the Recommendation's price condition is based on. Failing that, the most
   relevant Canadian comparator. Failing that, the first one listed. Use the same comparator for the sponsor and
   agency values.
2. **Deterministic vs probabilistic:** use the **probabilistic** base case when the agency reports it as its base
   case (usually), and the matching sponsor figure. Record which one in `icer_type`.
3. **No matching ICER type:** if one side reports only one type, use what is reported and set
   `icer_type_mismatch = true`. These reviews stay in the main model and are dropped in a sensitivity analysis.
4. **Scenarios never count as a base case.**
   - Agency has only exploratory or scenario results: `no_reanalysis`.
   - Agency gives a **point estimate and a range**: use the point estimate; record the range in the range fields.
     (PC0195: sponsor $157,293; agency point $171,723, range $157,226–$370,710. The point gives a ratio of 1.09×;
     the top of the range would give 2.36×.)
   - Agency gives **only a range**: `range_only`, put the lower end in the number field, record both ends.
   - In every case, record the Recommendation's headline figure in `agency_icer_headline` if it differs.
5. **Which sponsor base case:** the last base case the sponsor itself submitted before the agency's reanalysis, as
   the economic report summarises it. If the sponsor revised its model during the review (for example in answer to
   the agency's questions), use the revised one and set `sponsor_version = revised`. A model the agency corrected
   is never the sponsor's base case.
6. **Multiple populations:** use the reimbursement-request population, or the one the price condition refers to.
   Note the others.
7. **Sequential vs pairwise:** prefer the **pairwise** ICER against the primary comparator when both sides report
   one. Otherwise use the sequential (fully incremental) ICER against the next comparator on the frontier, and set
   `icer_basis = sequential`. The agency's frontier can include cheap, rarely used comparators (Lachaine 2025), so
   sequential rows are dropped in a sensitivity analysis.
8. **Dominance:** if the sponsor reports dominance (cheaper and more effective) and the agency reports a positive
   ICER, set `ratio_status = sponsor_dominant`. The ratio is undefined, but these are among the largest revisions,
   so they are **kept** in the secondary targets below and counted in every table. Report how excluding them
   shifts the median, as Walton 2019 did not.
9. **Different comparators for sponsor and agency** (e.g. abemaciclib, PC0400/PC0409):
   `ratio_status = comparator_mismatch`. Exclude from the model.
10. **Several indications or a reconsideration in one project** (e.g. SR0816-000/001): use the indication the final
    Recommendation covers, and the economic report it cites. One row per project number.
11. **Units and price:** cost per QALY only, never per life-year or per responder. Both ICERs at the sponsor's
    submitted price, never at a price the agency proposes.
12. **Consistency check:** if there is a cumulative stepwise table (§4), its last ICER must equal `agency_icer`
    within ±2%. Flag the row if it doesn't.

**Secondary targets (computed in code from the fields above).** The main target is the size of the revision. Two
coarser versions are less sensitive to noise in the exact size, and they keep the `sponsor_dominant` reviews that
the ratio loses. If all three point the same way, the findings hold up.

| target | definition | `sponsor_dominant` reviews |
|---|---|---|
| large_revision | ratio ≥ 2 | coded true when the agency ICER is positive |
| crossed_threshold | sponsor ICER ≤ *T* and agency ICER > *T* (*T* = `wtp_threshold`, §6) | coded true when the agency ICER > *T* |

Per-category outcomes from the stepwise table (§4), such as "the agency changed the survival extrapolation", are
a possible third set. They belong to the mechanism question and are decided once the stepwise fields are
extracted.

**Precision of the target, measured before the full run.** Two extractors run independently on about 20 reviews.
The bar, set in advance: at least 90% agreement on `sponsor_icer`, `agency_icer`, `comparator` and `ratio_status`.
Below that, the disagreements show which rule is still ambiguous; fix it and repeat.

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
0. Before the full run: the target-precision check at the end of §2.
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
