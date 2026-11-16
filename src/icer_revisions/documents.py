"""Choose, download and sanity-check each review's Recommendation and economic report.

The economic report is the pharmacoeconomic review, the combined clinical + economic report, or, for
pre-2022 pCODR reviews, the Economic Guidance Report (EGR). File names are inconsistent across years, so
documents are picked by file-name rules (`pick_docs`), and every downloaded file is then checked against
its first pages (`check_pdf`) so that a wrong pick is flagged in the manifest instead of passing silently.
The rules were derived from, and are regression-tested on, the 2020-2025 cohort's file names.
"""

import re
import time
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import pymupdf
import requests

from . import config

# Never a Recommendation or economic report. Letter lookarounds stand in for \b, which treats "_" as a
# word character and so misses names like "SR0644_Entresto_PI Submission.pdf".
EXCLUDE = re.compile(
    r"feedback|feddback|input|supplement|(?<![a-z])supp(?![a-z])|patient|clinician|clincian|"
    r"(?<![a-z])PI(?![a-z])|COI|memorandum|response|funding|algorithm|"
    r"clinical[-_ ]review|procedural[-_ ]review|draft[-_ ]?rec|french|rétroaction|"
    r"^T[RS]\d{4}",  # updated recommendations from class-wide therapeutic reviews (TS0001, TR0016, ...)
    re.I,
)
RECOMMENDATION = re.compile(r"rec(ommendation)?s?\b|_rec|rec[-_]|REC-|final[-_ ]rec|confidential final", re.I)
INITIAL_REC = re.compile(r"(?<![a-z])in(?:itial)?[-_ ]?rec", re.I)  # pCODR "inRec": superseded by "fnRec"
ECONOMIC = [  # tried in order
    re.compile(r"pharmacoeconomic|economic|EGR(?![a-z])|\d{4}PE[-_ ]", re.I),
    re.compile(r"combined?|main[-_ ]?report|\d{4}r[-_]", re.I),
]
KINDS = ("rec", "pe")
USER_AGENT = "Mozilla/5.0 (compatible; icer-revisions/0.1; academic research)"


def _filename(url: str) -> str:
    return unquote(url.rsplit("/", 1)[-1])


def _matches(pattern: re.Pattern, url: str) -> bool:
    return pattern.search(_filename(url)) is not None


def pick_docs(urls: list[str]) -> tuple[str | None, str | None]:
    """Return (recommendation_url, economic_report_url); either may be None.

    Recommendation: a recommendation-named file, final before initial; failing that, the first remaining
    file that is not named like an economic report. Economic report: the first file matching each
    `ECONOMIC` pattern in turn; failing that, any remaining file not named like a recommendation.
    """
    pdfs = [u for u in urls if u.lower().endswith(".pdf") and "drush.in" not in u]  # drush.in: staging mirror
    candidates = [u for u in pdfs if not _matches(EXCLUDE, u)]

    recs = sorted((u for u in candidates if _matches(RECOMMENDATION, u)), key=lambda u: _matches(INITIAL_REC, u))
    others = [u for u in candidates if not any(_matches(p, u) for p in ECONOMIC)]
    rec = recs[0] if recs else next(iter(others), None)

    rest = [u for u in candidates if u != rec]
    for pattern in ECONOMIC:
        pe = next((u for u in rest if _matches(pattern, u)), None)
        if pe:
            return rec, pe
    return rec, next((u for u in rest if not _matches(RECOMMENDATION, u)), None)


# Content check, calibrated on the 2020-2025 cohort's PDFs (see docs/data-sources.md).
REC_TITLE = re.compile(
    r"reimbursement recommendation|final recommendation|recommendation and reasons|pERC|"
    r"Drug Expert Committee|CDEC|recommendations? of the",
    re.I,
)
REC_HEADING = re.compile(r"reimbursement recommendation|recommendation and reasons|final recommendation", re.I)
# Terms of an economic analysis itself, not passing mentions. On the 2020-2025 cohort every correct economic
# report has at least 11; the patient input and clinical report once picked by mistake have none.
ECONOMIC_TERMS = re.compile(
    r"ICER|incremental cost|cost[- ]utility|cost[- ]minimi[sz]ation|budget impact|sponsor-submitted cost|"
    r"cost comparison|per QALY|pharmacoeconomic review|economic evaluation",
    re.I,
)
MIN_ECONOMIC_TERMS = 5


def check_pdf(path: Path, kind: str) -> str:
    """'ok', or why the file does not look like the document it was picked as."""
    try:
        with pymupdf.open(path) as doc:
            if kind == "rec":
                # first 400 characters of text; some pCODR files open with image-only cover pages
                head = re.sub(r"\s+", " ", " ".join(doc[i].get_text() for i in range(min(5, len(doc))))).strip()
                return "ok" if REC_TITLE.search(head[:400]) else "no_recommendation_title"
            title = re.sub(r"\s+", " ", doc[0].get_text())[:250] if len(doc) else ""
            if REC_HEADING.search(title):
                return "looks_like_recommendation"
            hits = 0
            for page in doc:  # stop as soon as there is enough evidence
                hits += len(ECONOMIC_TERMS.findall(page.get_text()))
                if hits >= MIN_ECONOMIC_TERMS:
                    return "ok"
            return "no_economic_content"
    except (pymupdf.FileDataError, RuntimeError):
        return "unreadable"


def pdf_path(project: str, kind: str, pdf_dir: Path = config.PDFS) -> Path:
    return pdf_dir / f"{project}_{kind}.pdf"


def _fetch(session: requests.Session, url: str, dest: Path, retries: int = 2) -> str:
    """Download one PDF, retrying network and server errors. Returns a status code for the manifest."""
    status = "error"
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, timeout=120)
        except requests.RequestException:
            status = "error"
        else:
            if resp.ok and resp.content[:4] == b"%PDF":
                tmp = dest.with_suffix(".part")  # write then rename, so an interrupted run leaves no bad PDF
                tmp.write_bytes(resp.content)
                tmp.rename(dest)
                return "downloaded"
            if resp.ok:
                return "not_pdf"
            status = f"http_{resp.status_code}"
            if resp.status_code < 500:
                return status
        if attempt < retries:
            time.sleep(2**attempt)
    return status


def _previous_urls(manifest: Path) -> dict[tuple[str, str], str]:
    if not manifest.exists():
        return {}
    m = pd.read_csv(manifest).dropna(subset=["url"])
    return {(r.project, r.kind): r.url for r in m.itertuples()}


def download(
    cohort: pd.DataFrame, pdf_dir: Path = config.PDFS, manifest: Path = config.MANIFEST, delay: float = 0.3
) -> pd.DataFrame:
    """Download missing PDFs and check every file; return a manifest with one row per (project, kind).

    A cached file is re-downloaded when the previous manifest shows it came from a different URL, so a
    change to the picking rules cannot leave a stale document behind.
    """
    pdf_dir.mkdir(parents=True, exist_ok=True)
    previous = _previous_urls(manifest)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    rows = []
    for i, r in enumerate(cohort.itertuples(), 1):
        urls = r.doc_urls.split() if isinstance(r.doc_urls, str) else []
        for kind, url in zip(KINDS, pick_docs(urls), strict=True):
            dest = pdf_path(r.project, kind, pdf_dir)
            if url is None:
                status = "not_listed"
            elif dest.exists() and previous.get((r.project, kind), url) == url:
                status = "cached"
            else:
                status = _fetch(session, url, dest)
                time.sleep(delay)
                if status != "downloaded":
                    print(f"  {r.project} {kind}: {status} {url}")
            check = check_pdf(dest, kind) if dest.exists() else None
            if check not in (None, "ok"):
                print(f"  {r.project} {kind}: check {check} ({_filename(url)})")
            rows.append({"project": r.project, "kind": kind, "url": url, "status": status, "check": check})
        if i % 50 == 0:
            print(f"  {i}/{len(cohort)} reviews")
    return pd.DataFrame(rows)


def run(cohort: pd.DataFrame, out: Path = config.MANIFEST) -> pd.DataFrame:
    manifest = download(cohort, manifest=out)
    if out.exists():  # a --projects run updates its rows and keeps the rest
        rest = pd.read_csv(out)
        manifest = pd.concat([rest[~rest["project"].isin(manifest["project"])], manifest], ignore_index=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(out, index=False)
    print(manifest.groupby("kind")["status"].value_counts().unstack(fill_value=0).to_string())
    flagged = manifest[manifest["check"].notna() & (manifest["check"] != "ok")]
    print(f"content check: {len(flagged)} files flagged (see the `check` column of {out})")
    return manifest
