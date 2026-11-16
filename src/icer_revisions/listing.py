"""Parse the CDA-AMC reimbursement-review export and build the study cohort.

The export has 12 fixed columns followed by a variable number of document-URL columns, so it cannot be
read with a plain `pd.read_csv`. URLs are normalised to absolute, %-encoded form so that `doc_urls` can
be stored as one space-separated string. A few reviews are listed twice (once with documents, once without);
`build_cohort` merges them into one row per project.
"""

import csv
import re
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from . import config

COLUMNS = {
    "Title": "title",
    "Brand Name": "brand_name",
    "Generic Name": "generic_name",
    "Files": "files",
    "Therapeutic Area": "therapeutic_area",
    "Recommendation Type": "recommendation_type",
    "Status": "status",
    "Submission Date": "submission_date",
    "Recommendation Date": "recommendation_date",
    "Project Number": "project",
    "Performance Metric": "performance_metric",
    "Title URL": "title_url",
}
N_FIXED = len(COLUMNS)
URL_START = re.compile(r"\s+(?=https?://|internal:)")
URL_SAFE = ":/?#[]@!$&'()*+,;=%~"  # keep URL syntax and existing %-escapes; encode spaces and non-ASCII


def _rejoin(cells: list[str]) -> list[str]:
    """Undo unquoted commas in file names: a cell that does not start a URL continues the previous one.

    The export also drops the space after the comma ("May 31, 2021" arrives as "May 31" + "2021"), so it is
    restored; the rejoined URL for SR0655 resolves only in that form.
    """
    out: list[str] = []
    for cell in cells:
        if out and cell.strip() and not cell.lstrip().startswith(("http://", "https://", "internal:")):
            out[-1] += ", " + cell.lstrip()
        else:
            out.append(cell)
    return out


def split_urls(cell: str) -> list[str]:
    """Absolute, %-encoded URLs from one export cell.

    Most cells hold one URL, but some hold several separated by spaces, and some file names contain
    literal spaces. Split only where a new URL starts, then encode what is left.
    """
    parts = URL_START.split(cell.strip())
    return [quote(p.replace("internal:", config.BASE_URL), safe=URL_SAFE) for p in parts if p]


def load_listing(path: Path = config.RAW_LISTING) -> pd.DataFrame:
    """Read the raw export: one row per listing entry, document URLs joined into `doc_urls`."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)[:N_FIXED]
        rows = []
        for r in reader:
            rec = {COLUMNS[h]: v.strip() or None for h, v in zip(header, r[:N_FIXED], strict=True)}
            urls = [u for cell in _rejoin(r[N_FIXED:]) for u in split_urls(cell)]
            rec["doc_urls"] = " ".join(urls) or None
            rows.append(rec)
    df = pd.DataFrame(rows)
    for col in ("submission_date", "recommendation_date"):
        df[col] = pd.to_datetime(df[col], format="%b %d, %Y", errors="coerce")
    return df


def build_cohort(listing: pd.DataFrame) -> pd.DataFrame:
    """SR and PC reviews with a recommendation in the study window, one row per project number."""
    prefix = listing["project"].str[:2]
    in_window = listing["recommendation_date"].dt.year.between(config.FIRST_YEAR, config.LAST_YEAR)
    rows = listing[in_window & prefix.isin(config.STREAMS)]

    merged = rows.groupby("project", sort=False).first()  # first non-null value of each column
    merged["doc_urls"] = rows.groupby("project", sort=False)["doc_urls"].agg(_union_urls)
    merged = merged.reset_index()
    merged.insert(1, "stream", merged["project"].str[:2].map(config.STREAMS))
    merged.insert(2, "year", merged["recommendation_date"].dt.year)
    return merged.sort_values(["recommendation_date", "project"], ignore_index=True)


def _union_urls(values: pd.Series) -> str | None:
    urls = dict.fromkeys(u for v in values.dropna() for u in v.split())  # ordered, de-duplicated
    return " ".join(urls) or None


def run(out: Path = config.COHORT) -> pd.DataFrame:
    cohort = build_cohort(load_listing())
    out.parent.mkdir(parents=True, exist_ok=True)
    cohort.to_csv(out, index=False)
    counts = cohort["stream"].value_counts().to_dict()
    print(f"cohort: {len(cohort)} reviews {counts} -> {out}")
    return cohort


def read_cohort(path: Path = config.COHORT) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"{path} not found; run `icer cohort` first")
    return pd.read_csv(path, parse_dates=["submission_date", "recommendation_date"])
