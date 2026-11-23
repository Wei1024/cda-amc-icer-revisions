# Extraction spec

What the extraction pipeline reads, what it produces for each review, the rules for hard cases, and how we
decide it works. Build from this file. The analysis that uses the data is in [analysis-plan.md](analysis-plan.md),
and the reasons behind each choice are in [decisions.md](decisions.md).

The output schema is `src/icer_revisions/schema.py` and the runner is `src/icer_revisions/extract.py`, which calls models
through OpenRouter: native PDF input, four grouped calls per review with the PDFs cached, and replies validated
against the schema (§1.2).

**Still open:** extractor B (a different model family; Gemini 4 Hydrogen is the lead candidate, §1.2) and the adjudicator; the comparison and
automatic-check code (§5); and whether to use OpenRouter's half-price batch models for the full run.

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
| Pages | The pages that hold the fields below, sent to the LLM as PDF pages so tables keep their layout (§1.1). The text layer is kept for checking quotes. | Done: `uv run icer pages`; replaces the text excerpts from the pilot |

### 1.1 Page selection

Each document type has its own rule. Section ranges come from the PDF's bookmarks; text cues pick a few extra
pages and serve as the fallback when there are no usable bookmarks. The rules are the `TARGETS` table in
`src/icer_revisions/pages.py`: each target names the fields it serves, its document, its sections and its cues, so
changing where a field is looked for means editing one entry.

| document | rule | pages kept (median, p90, max) |
|---|---|---|
| Recommendation | The whole document, minus the stakeholder-input and committee-membership sections when bookmarks mark them | 16, 25, 42 of 20, 31, 49 |
| Economic report, 60 pages or fewer | The whole document. These are the economic-only reports (pCODR EGRs, CDR pharmacoeconomic reports) and a few short combined ones | whole |
| Economic report, longer, with a "Pharmacoeconomic Review" bookmark | **Pharmacoeconomic Review:** Executive Summary, Economic Review, the appendix on the submitted evaluation, and the appendix on the agency's reanalyses. **Clinical Review:** Executive Summary. **Extra pages from the Clinical Review, by cue:** the 3 best matches for the included-studies table, the 2 best for median follow-up, the 2 best for prevalence | 37, 47, 92 of 145, 210, 383 (all long reports) |
| Economic report, longer, other bookmarks (7 reports) | Bookmarked sections named executive summary, economic, cost information, reanalysis or disease background (under 40 pages each), plus the 12 pages with the most $/QALY figures and the same extra pages | |
| Clinical report (78 reviews, 2020–2021) | The first 25% of pages (at least 15, at most 30), plus the 2 best pages for median follow-up and the 2 best for the included-studies table | 26, 30, 31 of 108, 136, 197 |

On top of these rules, in every document:
- **Always kept:** any page with the agency's stepped-analysis table ("Summary of the Stepped Analysis of the
  CDA-AMC Base Case"), wherever the bookmarks put it.
- **Always dropped:** table-of-contents, list-of-tables, list-of-figures and abbreviation pages.
- **Never kept on purpose:** budget impact appendices, cost comparison tables, submission quality, references,
  and patient or clinician input.

**Result: a median of 58 pages per review (p90 72, max 108), 23,185 of 70,577 pages in all; 4.9 MB per review
(max 18 MB), 2.0 GB in all.**

**Coverage, measured with text cues** (documents that have such a page anywhere → selection keeps at least one):

| cue | reviews covered | notes |
|---|---|---|
| a $/QALY figure | 368 of 368 | |
| the stepped-analysis table | 251 of 251 | |
| the included-studies table | 366 of 366 | |
| "median follow-up" | 211 of 211 | |
| "primary endpoint / outcome" | 389 of 404 | The other 15 likely state the endpoint without the phrase |
| "prevalence" | 307 of 354 | Many of the 47 others mention it only in the budget impact appendix (the sponsor's population estimate), references or patient input. Check in the precision run |

These cues show where the information is, not that it is correct; the precision check (§5) is the real test.
If an extractor reports a field as not found, the review's full documents are searched with the same cues, and a
hit outside the selection is flagged so the rule can be fixed.

**Output.** For each review, one PDF per document, `data/pages/<project>/{rec,pe,clin}.pdf`, sent to the model as
separate labelled documents in one request. Separate documents keep fields that depend on the source clear (the
Recommendation's price condition and headline figure, rule 1) and let each quote name its document. The page map,
`data/interim/page_selection.csv`, has one row per kept page: `project`, `kind`, `n_pages`, `source_page`,
`output_page`, `reason` (the target and the section or cue). Evidence quotes give a document and an output page,
and are mapped back to source pages with this file.

### 1.2 Extraction calls

Each review is extracted in **four calls, one per group of fields**: `icers` (§2.1 and §2.2), `stepwise` (§2.3),
`features` (§2.4) and `price` (§2.5). Each call returns its group's fields plus `evidence` and `notes`, and the four
are merged into one record. The calls are made one after another, through OpenRouter.

- **The four calls are one conversation.** The first call sends the instructions, the labelled PDFs (with a cache
  breakpoint after the last one) and the first group's question, which names the group and gives its JSON schema.
  Each later call repeats everything before it, adds the previous answer and asks the next question. Later
  groups therefore see the earlier answers, so the stepped table uses the comparator the ICER call chose; a
  mistake in an early group can also carry forward. The two extractors stay independent of each other.
- **The PDFs are cached across the four calls.** Because each request contains the whole previous one, both
  providers' caches work: Claude reads the PDFs after the breakpoint, and Gemini 4, which caches a request only
  for one that extends it, does too. With four separate calls sharing only the PDFs, Gemini had no cache hits in
  16 calls (D20).
- **The schema goes in the final message, not in `response_format`.** Providers treat an output schema as part
  of the prompt prefix, so a different schema per call would invalidate the cache. The reply is validated against
  the schema in code; an invalid reply fails that call and is left out of the conversation, and a re-run repeats
  only the calls that failed, after the groups that succeeded.
- **Why four groups.** Each call stays focused on related fields. The split began with Anthropic's limit of 16
  fields that may be null when a schema is enforced; with the schema in the prompt that limit no longer applies,
  and the stepped-analysis group now exceeds it (D17, D19).

Measured on PC0195 with Claude Haiku 5.5 (about 175k input tokens per call): $0.154 for the review with the cache,
against $0.46 with a schema per call and no cache hits ([decisions.md](decisions.md), D17).

Test runs on PC0195 (one review, so a first look only):

| model, effort | time | cost | cache | quotes on the cited page |
|---|---|---|---|---|
| Claude Haiku 5.5, medium | about 1 min | $0.15 | calls 2–4 read the PDFs | 5 of 15 (old quote rules) |
| Claude Sonnet 5.5, medium | 47 s | $0.53 | calls 2–4 read the PDFs | 19 of 20 |
| Gemini 4 Carbon, high (stepwise at medium) | about 14 min | $0.80 | 2 of 4 calls hit | 13 of 14 (old quote rules) |

- Haiku cited the page numbers printed on the reports rather than positions in the attached PDFs, and its
  answers were the weakest; Sonnet is the cheaper model used for testing.
- Gemini reads a PDF page as about 1,300 tokens (77k for PC0195's 58 pages), not the 258–560 its older
  documentation gives, and its automatic cache hit on only some calls. At high effort Carbon spent up to 31,600
  tokens thinking per call and once ran out of room before answering; medium effort avoided that.

The new stepped-analysis schema was then run with Sonnet 5.5 on four reviews chosen for their table shapes
(PC0195, PC0330, SR0685, PC0350): $0.53–0.63 and under a minute per review, calls 2–4 reading the PDFs from the
cache, and every cost, QALY and ICER in the four tables matched the PDFs (D19).

Gemini 4 Hydrogen as one conversation, on the same four reviews: $0.24–0.30 and about a minute per review, calls
2–4 reading 83k–109k tokens from the cache. Every stepped-table number matched Sonnet's, and 175 of 192 other
fields agreed; most differences were wording, rounding or rules the spec leaves open (D20).

Replies are streamed, so a stalled connection is caught rather than waited out, and each review's record is saved
after every call. A reply that fails validation is kept with the reason, so it can be read.

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

### 2.3 The agency's stepped analysis

Most economic reports from 2021 on have a table titled "Summary of the Stepped Analysis of the CADTH (or CDA-AMC)
Reanalysis Results". It starts from the sponsor's base case, applies each of the agency's changes **on its own**,
and ends with all the changes together, which is the agency's base case. Example, PC0330 (2024):

| row | ICER |
|---|---|
| Sponsor's base case | $55,198 |
| CADTH reanalysis 1: use of KM data when modelling OS and PFS | $54,172 |
| CADTH reanalysis 2: choice of parametric distribution for OS | $97,546 |
| CADTH reanalysis 3: treatment duration | $109,289 |
| CADTH reanalysis 4: health state utility values | $58,191 |
| CADTH base case (1 + 2 + 3 + 4), probabilistic | $195,000 |

The table is copied as printed, row by row, for the drug under review and one comparator. How much each change
contributes is computed afterwards, and the method is not yet chosen ([analysis-plan.md](analysis-plan.md) §4):
keeping each row's costs and QALYs leaves every method open, including for rows whose ICER is negative or
dominated, where an ICER alone is unusable.

| field | values | notes |
|---|---|---|
| `has_stepped_table` | bool | Rule 13 |
| `table_title` | text | Verbatim |
| `table_document`, `table_page` | `rec` / `pe` / `clin`, number | Where the table's first row is |
| `table_format` | `changes_then_combined`, `cumulative`, `other` | Rule 13 |
| `table_drug`, `table_comparator` | text | The pair taken from the table, as the table names them: rule 14 |
| `rows` | list of rows, in table order | Empty if there is no table |

Each row:

| field | values | notes |
|---|---|---|
| `order` | number | From 1 |
| `label` | text | The row's label, verbatim, without the drug names. Code finds it on the table's pages, so every row is checked |
| `row_type` | `sponsor_base`, `sponsor_corrected`, `change`, `combined` | Rule 13 |
| `analysis` | `deterministic`, `probabilistic`, `not_stated` | As the table or its footnote says for this row: rule 13 |
| `category` | `extrapolation_survival`, `treatment_effect`, `treatment_effect_waning`, `utilities`, `time_horizon`, `comparator`, `drug_costs_wastage_dosing`, `treatment_duration`, `other_costs`, `population`, `model_structure`, `other` | `change` rows only: rule 15 |
| `multiple_changes` | bool | The row applies several changes in different categories; `category` is the one listed first |
| `cost_drug`, `qaly_drug` | number | Total cost and QALYs of the drug under review, as printed |
| `cost_comparator`, `qaly_comparator` | number | Total cost and QALYs of the comparator, as printed |
| `inc_cost`, `inc_qaly` | number | Only when the table prints incremental values instead of totals (2020 pCODR tables) |
| `icer` | number ($/QALY) | As printed, negative values included (PC0350: −1,429); null if no number is printed |
| `icer_note` | `point`, `dominant`, `dominated`, `extended_dominance`, `not_reported` | What the figure means: a negative ICER with more QALYs is `dominant` |

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
| `evidence` | Verbatim quotes of 30 words or fewer, each with its document (`rec`, `pe`, `clin`), its page and the `fields` it supports. **Every number extracted needs a quote that contains it**; a number computed from others (rule 10) quotes the figures it came from. One quote may support several fields: a sentence giving the agency's ICER and its range supports `agency_icer`, `agency_icer_status`, `agency_icer_range_low` and `agency_icer_range_high`. Coded fields (statuses, design, model type) need a quote when the choice is not obvious. The stepped table needs no quotes: its title and row labels are verbatim, and code finds them. About 10 quotes per call at most |
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

12. **Stepped-table check.** A `combined` row of the same `analysis` type as `agency_icer` (`icer_type`) should
    match it within ±2%, and a `sponsor_base` row of the same type should match `sponsor_icer` unless the sponsor
    revised its model (rule 5). Rows of the other type are not compared: the single-change rows are usually
    deterministic while the base cases are usually probabilistic (PC0330's table starts at $55,198
    deterministic; the sponsor's probabilistic base case is $60,879). Code flags the record if a comparison
    fails; the extractor still copies the table as printed.

**The stepped analysis**

13. **Which table, and its rows.** Take the economic evaluation's stepped analysis, never the budget impact
    analysis's (which also says "stepped analysis" but reports budgets, not ICERs), and never a table of
    scenario or sensitivity analyses run on the agency's base case. If there is no such table,
    `has_stepped_table = false` and `rows` is empty.
    - Row types: `sponsor_base` (the sponsor's base case), `sponsor_corrected` (after the agency's error
      corrections, when the table shows it), `change` (one numbered reanalysis) and `combined` (all changes
      together). Copy each row the table has; a table may lack some types, and may give the combined row twice,
      deterministic and probabilistic: copy both.
    - `analysis`: what the table says for the row, often in a footnote ("Deterministic analysis, unless
      otherwise stated") or in the label ("(probabilistic)"). `not_stated` when it says nothing.
    - `table_format`: `changes_then_combined` when each change is applied on its own to the sponsor's (corrected)
      base case and a final row combines them (the usual form, "Reanalysis 1 + 2 + 3"); `cumulative` when each
      row adds its change to the row before; `other` for anything else.
    - Older pCODR reports (2020–21) instead list one-way analyses with a "best case" or "base case" row that
      combines some of them (e.g. PC0195: "Best case estimate of parameters (No. 2, 3, 10)"). Record only the
      changes that make up the agency's base case, plus the starting and combined rows, and set
      `table_format = other`.
14. **Which drug and comparator.** Many tables list several treatments in every row. Take the drug under review
    and the comparator the agency's base-case ICER refers to (rule 1), and copy those two lines of each row. If
    the drug appears in several doses or regimens, take the one the Recommendation is about and say so in
    `notes`. If the table has an ICER only against another comparator (a sequential analysis), still copy the
    costs and QALYs of the chosen pair, set `icer_note` from what is printed for the drug, and explain in `notes`.
15. **Categories.** Code what the change does to the model. The agency's "Revisions to the Submitted Economic
    Evaluation" table, which gives the sponsor's and the agency's value for each change, is the best guide.
    - `extrapolation_survival`: the curves for OS, PFS or other time-to-event outcomes beyond the trial: the
      parametric distribution, use of Kaplan-Meier data, cure assumptions
    - `treatment_effect`: the size of the drug's effect compared with the comparator: hazard ratios, response
      rates, which indirect comparison is used
    - `treatment_effect_waning`: whether and when the drug's benefit fades over time
    - `utilities`: health-state utility values, utility decrements, adverse-event disutilities
    - `time_horizon`: the length of the model
    - `comparator`: which treatments are compared, or the mix of treatments in a comparator basket
    - `drug_costs_wastage_dosing`: price, dose, dose intensity, vial sharing and wastage of the drugs compared
    - `treatment_duration`: how long patients stay on treatment, and stopping rules
    - `other_costs`: health-state, monitoring, administration, adverse-event, subsequent-treatment and
      end-of-life costs
    - `population`: who is modelled: the eligible population, subgroup, age or weight
    - `model_structure`: health states, transitions, cycle length, half-cycle correction
    - `other`: none of the above; say what in `notes`

## 4. Computed in code, not by the LLM

| value | how |
|---|---|
| `ratio`, `log_ratio` | `agency_icer / sponsor_icer`, only when `ratio_status = ok` |
| `large_revision` | ratio ≥ 2. For `sponsor_dominant` reviews: true if the agency ICER is positive |
| `crossed_threshold` | sponsor ICER ≤ T and agency ICER > T, with T = `wtp_threshold`. For `sponsor_dominant` reviews: true if the agency ICER > T |
| Cost vs QALY split | log(ratio) = log(ΔC agency / ΔC sponsor) − log(ΔQ agency / ΔQ sponsor) |
| Price-cut split | sponsor-implied cut = max(0, 1 − T / sponsor ICER); agency-implied cut = max(0, 1 − T / agency ICER); the revision's part is the difference. It treats the drug price as the whole incremental cost, so it is an approximation, reported next to `price_reduction_pct` |
| Contribution of each stepped-analysis change | From `rows`. Method not yet chosen ([analysis-plan.md](analysis-plan.md) §4) |
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
   - every evidence quote is found word for word in the attached pages, on the page and in the document it cites
     (`locate.py`; built, and shown in the viewer)
   - ΔC ÷ ΔQ reproduces each ICER within ±2%
   - the stepped table's combined row matches `agency_icer` (rule 12)
   - the Recommendation and the economic report agree
   - the price cut is consistent with the agency ICER and threshold
   - the record passes schema validation
4. Optional: a hand check of `sponsor_icer`, `agency_icer` and `comparator` on 15 random reviews.

There is no full hand-labelled set; agreement and the checks above stand in for it ([decisions.md](decisions.md),
D3). How agreement is reported is in [analysis-plan.md](analysis-plan.md).
