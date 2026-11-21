# How much does CDA-AMC revise sponsor ICERs, and why?

Drug manufacturers seeking public reimbursement in Canada submit a cost-effectiveness model to Canada's Drug
Agency (CDA-AMC, formerly CADTH). The agency critiques the model and reports its own base-case incremental
cost-effectiveness ratio (ICER), which is typically about twice the sponsor's. That gap drives the price reduction
the agency recommends.

Earlier studies tallied these gaps by hand, over short windows and one review stream at a time. This project
uses LLM extraction with validation to cover **all 404 CDA-AMC oncology and non-oncology reimbursement reviews
with recommendations from 2020 to 2025**, and asks:

1. **Revision.** How large is log(agency ICER / sponsor ICER), what kind of submission gets a larger one
   (features known before the decision), and how much of the recommended price cut does it account for? Each
   cut is split into the part the sponsor's own ICER already implies and the part the agency's revision adds.
2. **Mechanism.** How much of each revision comes from incremental costs versus QALYs, and from each type
   of change in the agency's stepwise reanalysis (survival extrapolation, utilities, drug costs, …)?
3. **Method.** How reliable is LLM extraction from HTA reports, measured by agreement between two independent
   extractors and a set of automatic consistency checks?

LLMs are used to build the dataset. The analysis itself is statistical: regression with effect sizes and
confidence intervals, fixed in advance. Cross-validated prediction measures how much the features explain, and a
tree-based model checks for missed interactions ([analysis plan](docs/analysis-plan.md)).

**Start here:** [extraction spec](docs/extraction-spec.md) (what the pipeline produces and the rules for hard
cases), then the [analysis plan](docs/analysis-plan.md) (hypotheses and models, fixed in advance), then the
[decision log](docs/decisions.md) (why things are the way they are, including choices that were replaced).

## Status

| Stage | State |
|---|---|
| Cohort, document download | Done (this repo) |
| Page selection | Done: one PDF per document of the pages extraction reads, so tables keep their layout ([docs/extraction-spec.md](docs/extraction-spec.md) §1.1) |
| LLM extraction and adjudication | Being designed; specified in [docs/extraction-spec.md](docs/extraction-spec.md) |
| Validation, statistical analysis, write-up | Not started; planned in [docs/analysis-plan.md](docs/analysis-plan.md) |

A 60-review pilot confirmed the approach is feasible: about 65% of reviews have a usable ICER ratio, and the
median ratio of 1.9× agrees with published estimates. In a typical review the sponsor's own ICER already
implied most of the price cut, and the agency's revision added about 13 percentage points
([docs/pilot-findings.md](docs/pilot-findings.md)).

## Setup

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 if needed).

```bash
uv sync
cp .env.example .env    # then add your own API key; .env is gitignored
```

The API key is needed only for LLM extraction (`icer extract`); the other steps run without one.

## Pipeline

```bash
uv run icer cohort      # parse the listing export -> data/interim/cohort.csv (404 reviews)
uv run icer download    # Recommendation, economic and (2020-21) clinical report PDFs -> data/pdfs/ (~880 files, ~3 GB), content-checked
uv run icer pages       # selected pages -> data/pages/<project>/{rec,pe,clin}.pdf + a page map
uv run icer all         # cohort, download and pages in order
uv run icer excerpts    # PDF -> text -> one excerpt per review -> data/excerpts/ (temporary, not in `all`)
uv run icer extract --extractor a --projects PC0195-000   # LLM extraction (calls the API, costs money)
```

`excerpts` is the text-based step from the pilot. It flattens tables into plain text, so `pages` replaces it: the
LLM reads the selected PDF pages as they are. `excerpts` will be removed once extraction runs on `pages`.

The download (about 3 GB) takes a while and is safe to rerun: it skips PDFs that are already there and checks every file.
`download`, `pages` and `excerpts` accept `--projects SR0616-000 PC0238-000 ...` to run on a subset. Re-runs skip
PDFs and text that already exist. Set `ICER_DATA_DIR` to keep generated data outside the repo. See
[data/README.md](data/README.md) for every file.

## Repository layout

```
docs/
  extraction-spec.md   what to extract per review, rules for hard cases, checks and the pass bar
  analysis-plan.md     questions, hypotheses, models and sensitivity analyses, fixed in advance
  decisions.md         dated log of design decisions and what they replaced
  data-sources.md      where documents come from, how two per review are chosen and checked
  pilot-findings.md    results of the 60-review feasibility pilot
  literature.md        prior work and the gap this project fills
data/raw/              CDA-AMC listing export (the only versioned data)
src/icer_revisions/
  config.py            paths and cohort definition
  listing.py           parse the export, build the cohort
  documents.py         pick, download and content-check each review's documents
  pages.py             page selection: the TARGETS rules table, one PDF per document
  excerpts.py          PDF to text, cue-based excerpting (temporary; replaced by pages.py)
  schema.py            the extraction output (pydantic), from docs/extraction-spec.md §2
  extract.py           runs one LLM extractor on each review's selected pages
  cli.py               the `icer` command
tests/
```

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## License

Code: MIT. CDA-AMC documents are © Canada's Drug Agency and are downloaded from cda-amc.ca, not redistributed here.
