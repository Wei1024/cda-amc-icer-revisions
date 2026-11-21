# Decision log

Why the project is set up the way it is, including choices that were later replaced. Newest last. The current
rules are in [extraction-spec.md](extraction-spec.md) and [analysis-plan.md](analysis-plan.md); this file only
explains them. Until 2026-11-20 both lived in a single `docs/codebook.md` (see the git history).

Each entry: what was decided, why, and what it replaced.

| | date | decision |
|---|---|---|
| [D1](#d1-cohort-and-unit) | pilot | Cohort: SR + PC reviews, 2020–2025, one record per project number |
| [D2](#d2-two-features-dropped) | pilot | Two features dropped |
| [D3](#d3-no-full-hand-labelled-set) | 2026-11-15 | Validate by agreement and checks, not a hand-labelled set |
| [D4](#d4-price-cut-folded-into-the-revision-question) | 2026-11-15 | Price cut folded into the revision question |
| [D5](#d5-page-selection-replaces-text-excerpts) | 2026-11-15 | Page selection replaces text excerpts |
| [D6](#d6-keep-the-outcome-tighten-its-rules) | 2026-11-19 | Keep the outcome, tighten its rules |
| [D7](#d7-point-estimate-over-range) | 2026-11-19 | Agency point estimate over its range |
| [D8](#d8-pairwise-over-sequential) | 2026-11-19 | Pairwise over sequential ICERs |
| [D9](#d9-sponsor-dominant-reviews-kept) | 2026-11-19 | Sponsor-dominant reviews kept, in the secondary outcomes |
| [D10](#d10-precision-check-before-the-full-run) | 2026-11-19 | Precision check before the full run |
| [D11](#d11-statistics-first-prediction-as-a-check) | 2026-11-20 | Statistics first, prediction as a check |
| [D12](#d12-three-hypotheses-stated-in-advance) | 2026-11-20 | Three hypotheses stated in advance |
| [D13](#d13-codebook-split-into-three-files) | 2026-11-20 | Codebook split into three files |
| [D14](#d14-clinical-reports-for-economic-only-reviews) | 2026-11-20 | Clinical reports added for economic-only reviews |
| [D15](#d15-rare-disease-from-a-prevalence-figure) | 2026-11-20 | Rare disease set in code from a prevalence figure |
| [D16](#d16-page-selection-by-bookmarked-section) | 2026-11-20 | Page selection by bookmarked section, with cue pages added |
| [D17](#d17-four-grouped-calls-through-openrouter-pdfs-cached) | 2026-11-20 | Four grouped calls through OpenRouter, PDFs cached |

Not decided yet: [ideas on hold](#ideas-on-hold).

### D1. Cohort and unit
**Decided:** one record per project number (one drug × indication), for SR (non-oncology) and PC (oncology) reviews
with a recommendation dated 2020–2025: 404 reviews.
**Why:** other prefixes (PH provisional funding algorithms, PX, PG, SX, SG, ST, SF, TS) are not standard sponsor
submissions, so they have no sponsor ICER to compare.

### D2. Two features dropped
**Decided:** `pct_qaly_after_trial` and `perspective_societal_base` are not model features.
**Why:** `pct_qaly_after_trial` was found in 27 of 60 pilot reviews, mostly from the agency's tables, so it would
leak the agency's view. It may still be described if taken from the sponsor's own table.
`perspective_societal_base` did not vary in the pilot.

### D3. No full hand-labelled set
**Decided:** extraction is validated by two independent LLM passes, an adjudicator for disagreements, and automatic
checks. A hand check of the outcome fields on 15 reviews is optional.
**Why:** hand-labelling 404 reviews is not feasible for this project. Agreement and the checks measure
reliability directly, and Q3 reports them.

### D4. Price cut folded into the revision question
**Decided:** the price cut is not a separate outcome. It is split, in code, into the part the sponsor's own ICER
already implied and the part the agency's revision added.
**Replaced:** a secondary outcome that modelled the cut in bands (<50 / 50–75 / ≥75%).
**Why:** the cut follows almost mechanically from the agency ICER and the threshold, so modelling it adds little.
The split says something new: in the pilot, the sponsor's ICER already implied a typical 65% cut and the revision
added about 13 points ([pilot-findings.md](pilot-findings.md)). The bands are kept for description.

### D5. Page selection replaces text excerpts
**Decided:** the LLM reads the relevant PDF pages directly (as PDF pages or images), instead of text excerpts.
**Replaced:** cue-based text excerpts (`icer excerpts`), as used in the pilot.
**Why:** converting to text flattens tables, and the key numbers are in tables. The cues are kept to score pages,
and the text layer is kept to check that quoted numbers appear in the source. Built in D16.

### D6. Keep the outcome, tighten its rules
**Decided:** keep log(agency ICER ÷ sponsor ICER) as the outcome, and write rules for the cases that were ambiguous
in the pilot (rules 3, 5, 7, 8, 10, 11, 12 in the spec, and the range handling in rule 4).
**Considered:** switching to a different outcome.
**Why:** much of the noise in the pilot came from ambiguous cases: which sponsor version, ranges, mismatched ICER
types. That is measurement noise, and rules fix it. The rest is reviewers' judgement, which is the thing being
studied, so it should stay in the outcome.

### D7. Point estimate over range
**Decided:** when the agency gives a point estimate and a range, use the point estimate and record the range.
**Replaced:** any range was coded `range_only`, with its lower end as the ICER.
**Why:** the old rule threw away a point estimate the agency had reported. In PC0195 the point gives 1.09×, while
the top of the range would give 2.36×, so the choice matters and has to be written down.

### D8. Pairwise over sequential
**Decided:** prefer the pairwise ICER against the primary comparator. Sequential ICERs are flagged
(`icer_basis = sequential`) and dropped in a sensitivity analysis.
**Replaced:** use the ICER against the next relevant comparator, with a note.
**Why:** the agency's efficiency frontier can include cheap, rarely used comparators that drive large cuts
(Lachaine 2025), so sequential ratios are not comparable to pairwise ones.

### D9. Sponsor-dominant reviews kept
**Decided:** when the sponsor claims dominance and the agency reports a positive ICER, the ratio is undefined, but
the review is kept in the two secondary outcomes (`large_revision`, `crossed_threshold`) and counted in every table.
**Replaced:** excluded with the ratio.
**Why:** these are among the largest revisions, so dropping them would understate the gap. Walton 2019 did not
report their effect; we report how excluding them shifts the median.

### D10. Precision check before the full run
**Decided:** two extractors on about 20 reviews must agree on at least 90% of `sponsor_icer`, `agency_icer`,
`comparator` and `ratio_status` before the full run.
**Why:** it tests whether the rules in D6 are clear enough, cheaply, before spending on 404 reviews. The bar is set
in advance so it cannot be moved after seeing the result.

### D11. Statistics first, prediction as a check
**Decided:** the main analysis is regression on the log ratio, with effect sizes and CIs, fixed in advance.
Cross-validated prediction measures how much the features explain; a tree model checks for interactions.
**Replaced:** a prediction-first framing, where the goal was to predict the ratio with ML. A decision tree and kNN
were considered as the main model.
**Why:** the question is which kinds of submission get larger revisions, and by how much: an explanation question
(Breiman 2001, "Two Cultures"; Shmueli 2010, "To Explain or to Predict?"). With about 260 usable reviews and a noisy
outcome, a flexible model would mostly fit noise and gives no effect sizes. The ML and LLM work is the extraction.

### D12. Three hypotheses stated in advance
**Decided:** H1 surrogate endpoint vs overall survival, H2 no active comparator vs an active drug, H3 single-arm or
observational trial vs head-to-head RCT ([analysis-plan.md](analysis-plan.md) §2).
**Not a hypothesis:** comparison method. The pilot pointed the opposite way to what was expected (indirect
comparison 1.77× vs direct 2.03×), so it is exploratory.
**Why:** stating them first separates the tests from exploration. H1 and H2 came from the pilot, so the model is
also refitted without the pilot reviews.

### D13. Codebook split into three files
**Decided:** `docs/codebook.md` became the extraction spec, the analysis plan, and this log.
**Why:** one file was doing three jobs: what to build, what to test, and why. Separating them makes the spec easy
to build from and keeps past decisions on record without cluttering it.

### D14. Clinical reports for economic-only reviews
**Decided:** for the 78 reviews (2020–2021) whose economic report covers economics only, also download the
separate clinical report (pCODR's Clinical Guidance Report or CDR's Clinical Review Report).
**Replaced:** two documents per review, with the trial fields taken from the Recommendation's short clinical
summary for those years.
**Considered:** accepting the gaps. In 6 reviews from 2020, the Recommendation gave trial design in 6 and the
primary endpoint in 5, but median follow-up in only 1. Gaps that fall only on early years are harder to treat as
missing at random, and the fuller clinical reports also firm up the fields behind H1 and H3. Downloading them
took minutes, and page selection needs one more rule (take the clinical report's executive summary).

### D15. Rare disease from a prevalence figure
**Decided:** the LLM extracts the stated prevalence (number, unit, kind, region), and code sets
`rare_disease` = fewer than 50 per 100,000 (1 in 2,000).
**Replaced:** a yes/no flag taken from an external source, planned after the pilot (CDA-AMC's rare-disease
designation or the listing). The listing export has no rare-disease field, Health Canada has no orphan
designation, and FDA or EMA designations do not always match Canadian indications, so they are kept as a
cross-check only.
**Why:** a yes/no read from the text was inconsistent between pilot batches. Reports call a condition rare in
no standard way, and some mentions are the committee's deliberation, close to the leakage rule. Copying a number
and applying one threshold in code gives the same definition for every review.
**Role in the analysis:** the only evidence is one descriptive split (Balijepalli 2024: about 2.5× for rare
diseases vs 2.3× overall), so it is not a hypothesis. It is kept as a control, because rare diseases tend to
have the weaker evidence that H1–H3 test.

### D16. Page selection by bookmarked section
**Decided:** select pages by document section, using the PDFs' bookmarks, and add a few pages by text cue
([extraction-spec.md](extraction-spec.md) §1.1). Short economic reports are kept whole.
**Considered:** scoring every page by cues alone (the pilot's excerpt logic). Keeping pages with three or more
cues gives about 16 pages per review, but it cannot tell an ICER in the economic review from one in a budget
impact appendix or a table of contents, and it splits tables across pages.
**Why:** from 2022, 96–100% of combined reports have a "Pharmacoeconomic Review" bookmark, and the reports are laid
out the same way, so sections are a reliable map. Measured on all 883 documents, the rules keep every $/QALY page,
stepped-analysis table, included-studies table and follow-up page that the cues find, at a median of 58 pages
per review. Prevalence is the weak spot (307 of 354 reviews) and is checked in the precision run.

### D17. Four grouped calls through OpenRouter, PDFs cached
**Decided:** extraction runs through OpenRouter, so models are easy to switch. Each review takes four calls, one
per field group, sent one after another. The PDFs are cached after the first call, and each group's JSON schema
goes in the final message rather than in `response_format` ([extraction-spec.md](extraction-spec.md) §1.2).
**Replaced:** one call per review through the Anthropic SDK, with the whole schema enforced as structured output.
**Why:**
- *One schema was not possible.* Anthropic's structured outputs allow at most 16 fields that may be null or of
  several types, and the full record has 29. Splitting by field group fixes that and keeps each call focused.
- *An enforced schema per call broke the cache.* Providers treat the output schema as part of the prompt prefix
  (Anthropic: "Changing the output_config.format parameter invalidates any prompt cache"). With a schema per call,
  each of the four calls wrote its own cache of the PDFs: about 175k tokens each, $0.46 for PC0195 with Haiku 5.5.
  With the schema in the final message, calls 2–4 read 172,643 tokens from the cache: $0.154.
- *The trade-off:* the schema is requested rather than enforced. Every reply is validated in code, and a failed
  call is repeated on the next run.
**Considered:** one call per review with numbers returned as a list (to fit the limit), the cheapest option at
about two thirds of the grouped cost. Grouped calls were preferred for focus, at a cost the cache keeps moderate.
**Still open:** extractor B. Gemini is a different model family and reads PDFs at roughly 258–560 tokens per page,
against several thousand for Claude, so it is the first candidate to test.

## Ideas on hold

- **Adding 2026 reviews.** Open.
- **Hand check of 15 reviews** (D3). Optional; decide after the precision check.
- **A public web tool** where users enter a drug's submission details and see similar past reviews and the model's
  estimate. If built, it comes last, leads with the similar-reviews explorer (useful even if the model is weak),
  shows ranges rather than point estimates, and shows the estimate only if cross-validation supports it.
