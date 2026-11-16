# Literature: manufacturer vs CADTH/pCODR ICERs, and ML/LLM on HTA documents

Searched 2026-11-12. Items marked (unverified) came from a fetch tool's summary of the paper rather than verbatim text.

## Manufacturer vs agency ICERs (Canada)

| Study | Scope | Extraction | Key result | Analysis |
|---|---|---|---|---|
| Saluja, Jiao, Koshy, Cheung, Chan. *Curr Oncol* 2021;28(1):606–18. [PMC7924399](https://pmc.ncbi.nlm.nih.gov/articles/PMC7924399/) | pCODR oncology, Jul 2011–Nov 2018; 73 indications from 109 economic guidance reports; redacted or missing ICERs excluded | Manual, 2 reviewers + adjudicator | Mean manufacturer ICER $134k vs EGP low $166k and EGP high $365k; manufacturer below the EGP low in 52/73. Gap driven by **ΔQALY, not ΔCost**. Most common revision: shortened time horizon (49/50 flagged), then utilities (36) | Absolute differences, cumulative distributions, Gamma GLM time trend only. **No ratio, no predictors, no tumour-type analysis** |
| Mirzayeh Fashami, Tarride, … Levine. *PharmacoEcon Open* 2024;8(6):823–36. [PMC11499573](https://pmc.ncbi.nlm.nih.gov/articles/PMC11499573/) | CADTH non-oncology, 2018–2022; 178 reports | Manual, 2 reviewers, Excel sheet | Median ICUR $138,658 (manufacturer) vs $380,251 (CADTH), **2.5×**. Price reduction requested in 95% of submissions, median 63.5%. Critique taxonomy with frequencies (e.g. comparator 47%, ITC/NMA 48%, extrapolation 10%, programming error 27%) | Medians, Wilcoxon, chi-square of critiques vs recommendation. Regression only for the recommendation outcome (unverified). **No model of the ratio** |
| Balijepalli, Gullapalli, Joshy, Rawson. *J Comp Eff Res* 2024;13(5):e230178. [PMC11037021](https://pmc.ncbi.nlm.nih.gov/articles/PMC11037021/) | CADTH oncology, 2020–2022; 206 assessments, 103 with a price-reduction value | Manual (implied) | Median $145k (sponsor) vs $295k (CADTH), about 2×. Price-reduction bands <25 / 25–50 / 51–70 / 71–90 / 91–100% = 5 / 18 / 21 / 29 / 30. Splits by clinical benefit and metastatic status. Higher reductions → longer pCPA negotiation | Descriptive only; says reductions "appear to correlate" with the revised ICER. Calls for a review of CADTH's revised assumptions. AbbVie-funded (unverified) |
| Balijepalli et al. ISPOR 2024 abstract HTA67, *Value Health* 27(6) S256. [link](https://www.valueinhealthjournal.com/article/S1098-3015(24)01533-X/fulltext) | CADTH non-oncology, 2021–2022; 72 submissions | Not stated | Median $475k (CADTH) vs $206k (sponsor), >2×; rare disease $908k vs $359k; ≥70% reduction in 71% of rare-disease positives | Descriptive. Conclusion: relationship to "other submission factors require[s] further investigation" |

**Our sample (2020–2025, both streams, n=39 usable): median agency/sponsor ratio 1.9×, IQR 1.2–2.8×.** This agrees with the published 2–2.5×, which is a useful external check on the LLM extraction.

## ML / LLM on HTA documents
- **LLM extraction:** Claude 3 Opus vs rule-based and classifier NLP on 50 NICE reports; 88–98% accuracy on 12/14 attributes, about 70% for outcome and comparator. [PMC13120885](https://pmc.ncbi.nlm.nih.gov/articles/PMC13120885/)
- **LLM extraction:** ISPOR Europe 2026, a custom GPT agent extracting cost-effectiveness models from 9 NICE/CADTH/ICER appraisals; human verification still needed. [ISPOR](https://www.ispor.org/heor-resources/presentations-database/presentation-cti/ispor-europe-2026/artificial-intelligence-for-evidence-generation-and-synthesis/ready-for-prime-time-evaluating-large-language-models-for-automated-extraction-of-cost-effectiveness-models-from-hta-submissions)
- **LLM extraction:** a case study of LLM extraction of cost-effectiveness analysis data. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1098301525023691)
- **Prediction:** Janoudi, Rada, Yasinov, Richter. medRxiv 2026 preprint, Monte Carlo Committee Simulation. 14 LLM personas predict CDA-AMC **recommendation category and condition types**; n=67 (Oct 2024–Dec 2025). Accuracy 93.2% on confident cases vs a **91.8% majority-class baseline**. Does not predict ICER revisions or the size of price cuts. [medRxiv](https://www.medrxiv.org/content/10.64898/2026.03.02.26347434v2.full)
- **Prediction:** classical ML on HTA outcomes, all ISPOR abstracts with small samples, predicting recommendation categories:
  - multi-country, 550 outcomes [ISPOR 2024](https://www.ispor.org/heor-resources/presentations-database/presentation/euro2024-4013/146240)
  - NICE/SMC/NCPE text classifiers [ISPOR 2025](https://www.ispor.org/heor-resources/presentations-database/presentation-cti/ispor-europe-2025/poster-session-5-2/predictive-algorithms-in-hta-what-factors-influence-decision-making-in-nice-smc-and-ncpe)

## Gap this project can fill
1. Every ICER-gap study used **manual** extraction on 2–7 year windows split by stream. None covers 2020–2025 across oncology and non-oncology with one method.
2. **No one models the revision ratio as an outcome** or tests which submission characteristics predict it. Two papers explicitly call this future work.
3. Critique *frequencies* are tallied, but **no one quantifies each issue's contribution to the ICER**. CDA-AMC's stepwise reanalysis tables make this possible.
4. ML/LLM prediction work targets the recommendation category, which is about 90% "reimburse with conditions" and makes a weak target. Continuous economic outcomes are untouched.
