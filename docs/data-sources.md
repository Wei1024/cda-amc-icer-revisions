# Data sources and document selection

## Source
The study list and every document link come from CDA-AMC's reimbursement review listing export
(`data/raw/reimbursement-review.csv`, downloaded 2026-11-04). It is the agency's own index of each review and its
files, keyed by project number. The PDFs are downloaded from cda-amc.ca by `icer download` and are not
redistributed here.

Other routes were considered and not used as the primary source:
- **OpenAlex / Crossref.** Since about 2021 the review reports are also published in the *Canadian Journal of Health
  Technologies*, which has DOIs. Coverage of recommendations and pre-2022 pCODR reports is partial, records would
  have to be matched back to project numbers by title, and the PDFs are served from the same site anyway.
- **Each review's web page** (`title_url`). It may list documents added after the export date. This matters only
  if 2026 reviews are added.
- **NCBI Bookshelf.** It hosts many older CADTH reports, so it is a possible fallback for dead links.

## Parsing the export
The export has quirks that the cohort step (`icer_revisions.listing`) handles:
- a variable number of URL columns per row;
- relative links written `internal:/sites/...`;
- some file names with literal spaces, and one cell with several space-separated URLs. URLs are split only where
  a new link starts, then %-encoded;
- one file name containing an unquoted comma, which spills into the next cell and loses the space after the
  comma. A cell that does not start a link is joined back onto the previous one with ", ";
- three oncology reviews listed twice, once without documents. Rows are merged per project: 407 rows become 404
  reviews.

## Choosing two documents per review
The 404 reviews list 1,811 links between them (median 4, maximum 15). Two are kept per review
(`icer_revisions.documents.pick_docs`):

1. **Never used:** non-PDF links, stakeholder or sponsor feedback, patient and clinician input, supplements,
   conflict-of-interest forms, memos, funding algorithms, clinical-only reviews, procedural review panel reports,
   draft recommendations, French versions, and updated recommendations from class-wide therapeutic reviews
   (TS####/TR####), which belong to another project.
2. **Recommendation:** a recommendation-named file, preferring the final one (pCODR `fnRec`) over the initial one
   (`inRec`). Failing that, the first remaining file that is not named like an economic report.
3. **Economic report**, trying in order:
   - "pharmacoeconomic", "economic", "EGR", or a `####PE` suffix;
   - "combined" or "main report";
   - any remaining file not named like a recommendation.

## Content check
File names cannot be fully trusted, so every downloaded PDF is also checked against its contents
(`check_pdf`). The result goes in the `check` column of `data/interim/pdf_manifest.csv`:

| check | meaning |
|---|---|
| `ok` | passes |
| `no_recommendation_title` | a "rec" file whose first text does not name a recommendation or the committee |
| `looks_like_recommendation` | a "pe" file whose first page is headed as a recommendation |
| `no_economic_content` | a "pe" file with fewer than 5 economic-analysis terms (ICER, incremental cost, per QALY, cost-minimization, budget impact, ...) |
| `unreadable` | PyMuPDF cannot open the file |

## Validation (2026-11-15, against the pilot's 806 downloaded PDFs)
- **The original file-name rules made 12 wrong picks in 11 reviews.** Four recommendation links were broken by
  spaces in file names. Three reviews got another project's class-review recommendation. Two got the initial
  instead of the final pCODR recommendation. Three economic picks were wrong: a patient-input file, a
  recommendation, and a clinical report. All 12 are fixed, and each is a regression test in
  `tests/test_documents.py`. No other pick changed.
- **The content check on the 794 unchanged picks: 794 ok, 0 flagged.** It flags all three known wrong economic
  picks. Correct economic reports have at least 11 economic-analysis terms; the wrong ones have 0, except the
  recommendation, which is caught by its heading. The shortest correct reports are 16-page pCODR Economic
  Guidance Reports.
- **Full download (2026-11-15): 805 of 805 listed documents downloaded (2.9 GB), and all 805 pass the content
  check,** including the 12 corrected picks.
- **Three reviews list no economic report**, so they have a Recommendation only:
  - SR0644 (Entresto, a resubmission): the export lists only the recommendation and patient input.
  - SR0663 (Enspryng): only the clinical review report is listed.
  - SR0816-001 (Remsima SC, a second indication): its economics are probably in the combined report of
    SR0816-000.

  Recovering these would need another source, such as the review web page.
- **Not a selection error:** many combined reports have no ICER because the review was a cost-minimization or
  cost-comparison analysis.
