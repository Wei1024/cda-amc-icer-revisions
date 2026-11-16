"""PDF -> text -> one compact excerpt per review, the input to LLM extraction.

A review's two documents run to hundreds of thousands of characters, but the fields in docs/codebook.md
come from a small number of passages. Every cue match below is widened into a context window; overlapping
windows are merged into spans; spans are ranked and kept up to a per-document size cap.

Two cue sets are combined:
- target cues: ICERs, base cases and reanalyses, price reductions and bands;
- feature cues: trial design, comparison method, endpoints, survival, model structure, incremental costs
  and QALYs, and the stepwise reanalysis table.

Priority rule: passages on the QALY share gained after the trial (extrapolation) and on the stepwise
reanalysis are always kept, whatever the cap. Stepwise matches get a long tail so the table rows survive.
"""

import re
from pathlib import Path

import pandas as pd
import pymupdf

from . import config
from .documents import pdf_path

TARGET_CUES = (
    r"per QALY|/QALY|ICER|incremental cost-effectiveness|"
    r"(?:sponsor's|CDA-AMC|CADTH) (?:probabilistic )?base[- ]case|(?:CDA-AMC|CADTH) reanalys|"
    r"price reduction|reduction in price|band \d|dominant|dominated|cost[- ]saving|willingness[- ]to[- ]pay"
)
FEATURE_CUES = (
    r"accrued after|predicted to be accrued|extrapolat|time horizon|lifetime horizon|"
    r"indirect treatment comparison|network meta-analys|\bNMA\b|\bITC\b|\bMAIC\b|matching-adjusted|"
    r"single[- ]arm|open[- ]label|double[- ]blind|randomi[sz]ed|phase (?:I|II|III|1|2|3)\b|pivotal|"
    r"primary (?:end ?point|outcome)|overall survival|progression-free survival|median follow[- ]up|"
    r"not (?:yet )?reached|data cut|interim analys|surrogate|"
    r"resubmission|reconsideration|rare disease|orphan|prevalence|"
    r"partitioned survival|Markov|state[- ]transition|decision tree|microsimulation|"
    r"treatment-specific utilit|health state utilit|societal perspective|"
    r"incremental (?:costs?|QALYs?)|stepped|stepwise|cumulative (?:reanalys|impact)|comparator"
)
CUES = re.compile(f"{TARGET_CUES}|{FEATURE_CUES}", re.I)
PRIORITY = re.compile(
    r"accrued after|predicted to be accrued|after the trial period|beyond the trial|extrapolated period|"
    r"stepped|stepwise|incremental (?:costs?|QALYs?) ?=",
    re.I,
)
TABLE = re.compile(r"stepped|stepwise", re.I)
ICER_FIGURE = re.compile(r"\$[\d,]{4,}[^.]{0,30}QALY")
PERCENT = re.compile(r"\d+\s?%")
TOC = re.compile(r"\.{6,}")  # dot leaders: table-of-contents lines

WINDOW = 450  # characters of context on each side of a cue
TABLE_TAIL = 2500  # characters after a stepwise-table cue
MAX_CHARS = 30_000  # per document; priority spans may exceed it

DOC_LABELS = {"rec": "RECOMMENDATION DOCUMENT", "pe": "ECONOMIC / COMBINED REPORT"}


def pdf_text(path: Path) -> str:
    """Plain text of a PDF on one line, with curly apostrophes and non-breaking spaces normalised."""
    with pymupdf.open(path) as doc:
        text = " ".join(page.get_text() for page in doc)
    text = text.replace("’", "'").replace(" ", " ")
    return re.sub(r"\s+", " ", text)


def _spans(text: str) -> list[list[int]]:
    spans: list[list[int]] = []
    for m in CUES.finditer(text):
        tail = TABLE_TAIL if TABLE.fullmatch(m.group(0)) else WINDOW
        a, b = max(0, m.start() - WINDOW), min(len(text), m.end() + tail)
        if TOC.search(text[a : m.end() + WINDOW]):
            continue
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(b, spans[-1][1])
        else:
            spans.append([a, b])
    return spans


def excerpt(text: str, max_chars: int = MAX_CHARS) -> str:
    """Keep the highest-ranked passages of one document, returned in document order."""

    def rank(span: list[int]) -> tuple[bool, int]:
        x = text[span[0] : span[1]]
        density = 3 * len(ICER_FIGURE.findall(x)) + len(PERCENT.findall(x))
        density += len({m.group(0).lower() for m in CUES.finditer(x)})
        return (PRIORITY.search(x) is None, -density)

    keep, total = [], 0
    for span in sorted(_spans(text), key=rank):
        if total >= max_chars and not PRIORITY.search(text[span[0] : span[1]]):
            break  # ranking puts every priority span first, so nothing required is lost here
        keep.append(span)
        total += span[1] - span[0]
    return " [...] ".join(text[a:b] for a, b in sorted(keep))


def cached_text(project: str, kind: str, pdf_dir: Path = config.PDFS, text_dir: Path = config.TEXT) -> str | None:
    """Text of a review document, converting the PDF on first use. None if the PDF is missing."""
    txt = text_dir / f"{project}_{kind}.txt"
    if txt.exists():
        return txt.read_text()
    pdf = pdf_path(project, kind, pdf_dir)
    if not pdf.exists():
        return None
    text = pdf_text(pdf)
    txt.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text(text)
    return text


def review_excerpt(review: pd.Series) -> tuple[str, int]:
    """Excerpt for one cohort row and the number of documents it drew on."""
    parts = []
    for kind, label in DOC_LABELS.items():
        text = cached_text(review["project"], kind)
        if text is not None:
            parts.append(f"===== {label} ({len(text)} chars) =====\n{excerpt(text)}")
    date = review["recommendation_date"]
    header = (
        f"PROJECT: {review['project']} | DRUG: {review['brand_name']} ({review['generic_name']}) | "
        f"AREA: {review['therapeutic_area']} | REC: {review['recommendation_type']} | DATE: {date:%Y-%m-%d}\n"
    )
    return header + "\n\n".join(parts), len(parts)


def run(cohort: pd.DataFrame, out_dir: Path = config.EXCERPTS, stats_path: Path = config.EXCERPT_STATS) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = []
    for i, (_, review) in enumerate(cohort.iterrows(), 1):
        body, n_docs = review_excerpt(review)
        (out_dir / f"{review['project']}.txt").write_text(body)
        stats.append({"project": review["project"], "n_docs": n_docs, "chars": len(body)})
        if i % 50 == 0:
            print(f"  {i}/{len(cohort)} reviews")
    stats = pd.DataFrame(stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats.to_csv(stats_path, index=False)
    print(f"excerpts: {len(stats)} reviews, documents per review {stats.n_docs.value_counts().to_dict()}")
    chars = stats["chars"]
    print(f"characters per excerpt: median {chars.median():.0f}, max {chars.max()}, total {chars.sum()}")
    return stats
