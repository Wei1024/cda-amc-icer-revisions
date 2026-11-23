# Data

| Path | Versioned | Contents |
|---|---|---|
| `raw/reimbursement-review.csv` | yes | CDA-AMC Reimbursement Review listing export, downloaded 2026-11-04 from cda-amc.ca. 1,601 rows; recommendations dated 2005-05-18 to 2026-10-19 |
| `interim/cohort.csv` | no | Study cohort, one row per review (`icer cohort`) |
| `interim/pdf_manifest.csv` | no | Chosen document URL (one row per review and document type), download status and content check for each review (`icer download`; see [docs/data-sources.md](../docs/data-sources.md)) |
| `interim/excerpt_stats.csv` | no | Documents used and excerpt size for each review (`icer excerpts`) |
| `pdfs/` | no | `<project>_rec.pdf` (Recommendation), `<project>_pe.pdf` (economic or combined report) and, for 78 economic-only reviews from 2020–2021, `<project>_clin.pdf` (clinical report); about 3 GB |
| `text/` | no | Plain text of each PDF, cached on first conversion |
| `pages/<project>/` | no | `rec.pdf`, `pe.pdf` and, where there is one, `clin.pdf`: the selected pages of each document, the input to extraction (`icer pages`); about 2 GB |
| `interim/page_selection.csv` | no | One row per kept page: source page, output page, and the rule that kept it (`icer pages`) |
| `extractions/<extractor id>/` | no | One JSON record per review: each of the four calls (output, model and provider, effort, time, tokens, cost, error, the raw reply when it failed validation, and any keys dropped because the schema lacks them) and the merged extraction (`icer extract`). Saved after every call. The id includes a hash of the prompt, so a prompt change writes to a new folder |
| `excerpts/` | no | One text excerpt per review (`icer excerpts`). Temporary: page selection will replace it as the input to LLM extraction |

The export's parsing quirks (variable URL columns, `internal:` links, spaces and an unquoted comma in file
names, three duplicated reviews) are described in [docs/data-sources.md](../docs/data-sources.md).
