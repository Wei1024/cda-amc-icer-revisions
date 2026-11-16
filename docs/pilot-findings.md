# EDA feasibility: CDA-AMC ICER revision and price reduction (2020–2025)

> **Pilot record.** This summarises the exploration run that preceded this repository. Script and data paths below (`scripts/0*_*.py`, `data/llm/`, the `.png` figures) refer to that exploration workspace, not to this repo. The cohort counts are listing rows: 407 rows are 404 unique reviews (190 PC, 214 SR) once three duplicated oncology rows are merged.

## Scope and method
- **Universe.** The CDA-AMC reimbursement review export has 1,601 rows; 530 have a recommendation dated 2020–2025. Of those, 407 are full drug reviews: 214 SR (non-oncology, CDEC) and 193 PC (oncology, pERC). Provisional funding algorithms (PH) and other project types were excluded because they carry no sponsor ICER.
- **Documents.** The Recommendation and the economic or combined report were downloaded for 404 reviews (802 PDFs, 2.9 GB).
- **Exploration sample.** 60 reviews, stratified 5 per year × stream.
- **Excerpts.** Each sampled review was cut to its ICER, price-reduction and base-case passages, about 20k characters per review (`scripts/04_make_excerpts.py`).
- **Extraction.** Three LLM subagents read the excerpts against the spec in `scripts/extraction_instructions.md` and wrote structured rows with verbatim evidence quotes (`data/llm/out_*.jsonl`, merged into `data/sample_extracted.csv`).
- **Sanity check.** All 97 extracted ICER values appear verbatim in the source text. This confirms the numbers are copied correctly, not that the right comparator or population was chosen.
- **Uncertainty.** With n = 60, proportions are roughly ±12 percentage points.

## Q1: ICER revision ratio
- **39 of 60 (65%) have both a sponsor and a CDA-AMC point ICER.** Projected to all 407 reviews, that is about 265 (95% CI roughly 210–310).
  - PC (oncology): 73%. SR (non-oncology): 57%.
  - No clear trend by year (50–90% per year, 10 per cell).
- **Why the rest drop out.**
  - The agency did no base case or only exploratory scenarios: 7 `no_reanalysis` and 2 `range_only`.
  - The sponsor ICER is missing or not in the excerpt: 8.
  - Dominant or dominated results: 5.
  - Cost-minimisation or cost-comparison analyses: 3.
- **Distribution of log(agency / sponsor).**
  - Median 0.64, which means the agency ICER is about 1.9× the sponsor's.
  - IQR 0.17–1.03 (ratio 1.2×–2.8×); range −0.28 to 2.43 (0.75× to 11×).
  - Only 4 of 39 were revised downward. The target is continuous and right-skewed and is well behaved on the log scale.
- **By therapeutic area, the data are thin outside oncology.**
  - Oncology n = 22, median 0.43 (about 1.5×).
  - Immunology / derm / GI n = 7, median 1.48 (about 4.4×).
  - Every other area has n ≤ 4.
  - With about 265 usable reviews in total, use **oncology vs non-oncology** or at most 4–5 coarse groups. The listing's free-text therapeutic area has 396 distinct values and needs mapping (see `scripts/05_analyse.py`).
- **Caveats the extraction surfaced.** These choices need to be defined consistently, and they are good material for the validation post.
  - Comparator choice: the sponsor and agency sometimes use different comparators, or a sequential vs pairwise analysis.
  - Probabilistic vs deterministic ICER.
  - Multiple populations.
  - "No base case, headline scenario" reviews.

## Q2: price reduction
- **47 of 60 (78%) report a specific %.** Projected, that is about 320 of 407.
  - 3 need no reduction, 4 require a reduction with no figure given, 1 is "not achievable", and 5 are other or not reported.
  - 21 of the 47 are lower bounds ("at least X%"), which is fine for binning.
- **Proposed bins (<50 / 50–80 / ≥80): 12 / 18 / 17.** The groups are reasonably balanced.
  - CDA-AMC's own band cut-points (<25 / 25–50 / 50–75 / ≥75) give 3 / 9 / 14 / 21. Using **<50 / 50–75 / ≥75** (12 / 14 / 21) is a good compromise.
  - It also maps directly onto the new reporting format.
  - Distribution: median 72%, with a large mass at 90–100%.
- **Reporting format change.** From late November 2025 recommendations give **bands** (band 1 = 1–24%, 2 = 25–49%, 3 = 50–74%, 4 = ≥75%) instead of exact percentages. Only 2 of 399 recommendations in 2020–2025 use bands, so the historical data are unaffected, but any 2026+ data or deployed model will only ever see bands. Binning at band edges future-proofs the target.

## Implications for the project
1. **Both targets are feasible in volume:** about 265 for the ICER ratio and about 320 for price reduction. That is modest for supervised learning: fine for regularised linear or ordinal models and a small tree ensemble with cross-validation, not for anything deep.
2. **The targets measure different things.** In the sample:
   - The price reduction is driven mostly by the ICER level: Spearman 0.63 with the sponsor ICER and 0.63 with the agency ICER.
   - It is essentially unrelated to how much the agency revised the ICER: Spearman −0.11 with the log ratio.
   - Price-reduction bins are therefore partly predictable from the sponsor's own submitted ICER, a strong pre-decision feature that makes a good baseline.
   - The revision ratio is the more interesting "what does CDA-AMC disagree with" target, but it is likely noisier and harder to predict.
3. **Leakage watch.** Features must come from the sponsor submission side: the sponsor ICER, trial design, comparator type, OS maturity, extrapolation share, and so on. The agency's critique sections ("key issues") describe the revision itself and should not be used as features.
4. **The extraction-validation part is clearly viable.** Excerpting plus LLM extraction with quotes worked. The judgement calls listed above are exactly what a hand-labelled set should adjudicate.

## Files
- `scripts/01_load_listing.py`: parses the variable-width CSV export.
- `scripts/doc_picker.py` and `scripts/02_download_recs.py`: choose and download the Recommendation and economic report for each review.
- `scripts/03_sample.py`: stratified sample.
- `scripts/04_make_excerpts.py`: PDF to text to excerpt (`--sample` for the 60).
- `scripts/extraction_instructions.md`: LLM extraction spec.
- `scripts/05_analyse.py`: EDA tables and `eda_sample.png`.

## Feature pilot (60 sampled reviews, 39 with a usable ratio)
Scripts: `scripts/06_feature_excerpts.py`, `scripts/feature_instructions.md`, `scripts/07_feature_pilot.py`. Output: `data/sample_features.csv`, `feature_pilot.png`. n = 39 is far too small to show predictability; this checks whether the features can be extracted, whether they vary, and gives a first look at signal.

**Availability (out of 60)**
- **Reliable:**
  - pivotal design, comparison method, primary endpoint type, model type, comparator type: 60 each
  - number of comparators: 58
  - time horizon: 53
- **Patchy:**
  - follow-up: 32
  - % of QALY gain after the trial: 27, and mostly CDA-AMC's own figure rather than the sponsor's, so it is a leakage risk
  - OS median reached: 23 (oncology only)
  - treatment-specific utilities: 13
- **Coded inconsistently between batches:**
  - rare disease: 48
  - resubmission: 43. One batch counted reconsiderations as resubmissions.
- **No variation:** societal perspective (all false). Drop it.

**First-look signal (median agency/sponsor ratio)**
- **Stream:** oncology 1.54× vs non-oncology 2.45×.
- **Primary endpoint:** PFS/EFS 1.18×, OS 1.51×, clinical scale 2.41×, response or surrogate 2.82×.
- **Comparator:** BSC/no treatment 2.48× vs active drug 1.60×.
- **Model type:** Markov 2.43× vs partitioned survival 1.51×. Largely the same split as oncology vs non-oncology.
- **Follow-up length:** Spearman ρ = −0.39 (n = 23). Longer follow-up goes with smaller revisions.
- **Weaker than hypothesised:**
  - ITC/NMA 1.77× vs direct comparison 2.03×
  - share of QALYs gained after the trial: ρ = 0.09
- **Many features overlap with oncology vs non-oncology,** so their separate effects can't be pulled apart at n = 39.
- **Toy ridge regression (leave-one-out, 11 features):** median absolute error 0.51 vs 0.57 for always predicting the median, a typical error of ×1.66 vs ×1.77. A weak but non-zero signal.

**Cost / QALY decomposition (n = 34): works well.**
- The cost and QALY parts rebuild the extracted log ratio almost exactly (r = 1.00, median absolute difference 0.004), which also shows the incremental values were extracted consistently.
- **The revision is driven mainly by QALYs in 26 of 34 reviews** (median QALY part ×1.34 vs cost part ×1.06). This matches Saluja 2021 and extends it to non-oncology, where the QALY part is larger (×1.77 vs ×1.30).

**Stepwise reanalysis tables: present in 45 of 60.** The change with the largest ICER impact:

| Change | Reviews |
|---|---|
| Survival extrapolation | 15 |
| Utilities | 8 |
| Other | 8 |
| Drug costs, wastage, dosing | 6 |
| Treatment-effect waning | 4 |
| Treatment duration | 2 |
| Population | 1 |
| Comparator | 1 |

**Codebook fixes before the full run**
1. Take the % of QALYs after the trial only from the sponsor's own results table, or drop it.
2. Get rare-disease status from an external source, e.g. CDA-AMC's Drugs for Rare Diseases designation or the listing, rather than the text.
3. Define resubmission precisely: an earlier review of the same indication, not a reconsideration of a draft.
4. Add rules for co-primary endpoints, for placebo-plus-backbone trials (record them as head-to-head), and for trial duration vs median follow-up.
5. Expand the stepwise extraction from "top change only" to every step with its ICER, so each type of change gets a contribution to the revision.
