"""Paths and the cohort definition shared by every pipeline step.

Everything under `data/` except `data/raw/` is generated and gitignored. Set `ICER_DATA_DIR` to keep the
generated data (about 3 GB of PDFs) somewhere else.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("ICER_DATA_DIR", ROOT / "data"))

RAW_LISTING = ROOT / "data" / "raw" / "reimbursement-review.csv"
COHORT = DATA / "interim" / "cohort.csv"
MANIFEST = DATA / "interim" / "pdf_manifest.csv"
EXCERPT_STATS = DATA / "interim" / "excerpt_stats.csv"
PAGE_MAP = DATA / "interim" / "page_selection.csv"
PDFS = DATA / "pdfs"
TEXT = DATA / "text"
EXCERPTS = DATA / "excerpts"
PAGES = DATA / "pages"  # selected pages: <project>/<kind>.pdf (extraction-spec §1.1)
EXTRACTIONS = DATA / "extractions"

# Cohort: standard sponsor submissions with a recommendation dated in this window (docs/extraction-spec.md, section 1).
FIRST_YEAR, LAST_YEAR = 2020, 2025
STREAMS = {"SR": "non_onc", "PC": "onc"}  # project-number prefix -> stream (CDEC / pERC)

BASE_URL = "https://www.cda-amc.ca"
