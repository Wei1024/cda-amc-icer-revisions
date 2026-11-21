"""Select the pages each review's fields come from, and write one PDF per document (docs/extraction-spec.md §1.1).

What to keep is declared in `TARGETS`, not in the selection code: each target names the fields it serves, the
document it reads, the bookmarked sections to keep, and the cue patterns that add a few more pages. Changing
where a field is looked for means editing one target. Every kept page records which target kept it, so a missed
field can be traced to selection or to extraction.

Section ranges come from the PDF's bookmarks. A section is matched by its path, the lower-case titles from the
top level down joined with " > " (for example "pharmacoeconomic review > executive summary"), with numbering
and "Appendix N:" prefixes removed.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pymupdf

from . import config
from .documents import pdf_path

KINDS = ("rec", "pe", "clin")
WHOLE_IF_AT_MOST = {"pe": 60}  # economic-only reports and short combined ones are kept whole

# Cue patterns, matched against a page's text.
DOLLAR_PER_QALY = re.compile(r"\$\s?[\d,]{4,}[^.]{0,30}QALY")
STEPPED_TABLE = re.compile(
    r"stepped analysis of the (?:CADTH|CDA-AMC) (?:base[- ]case|reanalys)|stepped (?:CADTH|CDA-AMC) reanalys|"
    r"summary of (?:the )?stepped analys",
    re.I,
)
STUDY_TABLE = re.compile(
    r"details of (?:the )?(?:studies|included stud|pivotal)|characteristics of (?:the )?(?:included )?stud", re.I
)
MEDIAN_FOLLOWUP = re.compile(r"median (?:duration of )?follow[- ]up", re.I)
PREVALENCE = re.compile(r"prevalen|incidence|affects? (?:about|approximately) [\d,]+", re.I)
# Table-of-contents, list-of-tables and abbreviation pages: short pages with dot leaders or such a heading.
CUE_LABELS = {
    DOLLAR_PER_QALY: "$/QALY figure",
    STEPPED_TABLE: "stepped-analysis table",
    STUDY_TABLE: "included-studies table",
    MEDIAN_FOLLOWUP: "median follow-up",
    PREVALENCE: "prevalence",
}
TOC = re.compile(r"\.{6,}|^\s*(?:list of tables|list of figures|table of contents|abbreviations)\s*$", re.I | re.M)
TOC_MAX_CHARS = 2500


@dataclass(frozen=True)
class Target:
    """Pages of one document that serve one group of fields."""

    name: str
    kind: str
    sections: tuple[str, ...] = ()  # regexes on section paths; matching sections are kept whole
    max_section_pages: int | None = None  # skip a matching section longer than this
    cues: tuple[tuple[re.Pattern, int], ...] = ()  # (pattern, n): the n pages with the most matches
    within: str | None = None  # regex on section paths: look for cues only there (whole document if none match)
    whole: bool = False  # keep every page
    drop: tuple[str, ...] = ()  # with `whole`: regexes on section paths to leave out
    front: float | None = None  # keep this share of the first pages...
    front_pages: tuple[int, int] = (15, 30)  # ...but at least / at most this many
    primary: bool = False  # if no primary target of the document matches a section, the fallbacks run
    fallback: bool = False
    fields: str = ""  # which output fields it serves (documentation only)


ECON = r"^pharmacoeconomic (?:review|report)"
CLIN = r"^clinical review"
TARGETS = (
    Target(
        "recommendation",
        "rec",
        whole=True,
        drop=(
            r"stakeholder perspectives|perspectives of patients|patient input|clinician input|drug program input",
            r"(?:cdec|perc|committee) information|members of the committee",
        ),
        fields="price reduction, threshold, headline ICER, price-condition comparator (rule 1), resubmission",
    ),
    Target(
        "economic",
        "pe",
        sections=(
            rf"{ECON} > (?:executive summary|economic review|economic evaluation|issues for consideration|"
            r"overall conclusions?)",
            rf"{ECON} > (?:additional information on the submitted|summary of the sponsor)",
            rf"{ECON} > .*reanalys",
        ),
        primary=True,
        fields="both ICERs, costs and QALYs, stepwise changes, the sponsor's model features",
    ),
    Target(
        "trial",
        "pe",
        sections=(rf"{CLIN} > executive summary",),
        cues=((STUDY_TABLE, 3), (MEDIAN_FOLLOWUP, 2)),
        within=CLIN,
        fields="pivotal design, primary endpoint, follow-up, OS reached",
    ),
    Target("prevalence", "pe", cues=((PREVALENCE, 2),), within=CLIN, fields="prevalence"),
    Target(
        "fallback",
        "pe",
        sections=(r"executive summary|economic|cost information|reanalys|disease background",),
        max_section_pages=40,
        cues=((DOLLAR_PER_QALY, 12), (STUDY_TABLE, 3), (MEDIAN_FOLLOWUP, 2), (PREVALENCE, 2)),
        fallback=True,
        fields="everything, for long reports whose bookmarks do not follow the usual layout",
    ),
    Target(
        "trial",
        "clin",
        front=0.25,
        cues=((MEDIAN_FOLLOWUP, 2), (STUDY_TABLE, 2)),
        fields="pivotal design, primary endpoint, follow-up, OS reached, prevalence",
    ),
)
ALWAYS = {"pe": (STEPPED_TABLE,)}  # kept wherever the bookmarks put them


def _clean(title: str) -> str:
    title = title.replace("_", " ").replace("’", "'").strip().lower()
    title = re.sub(r"^(?:appendix\s+\d+\s*[:.]?|\d+(?:\.\d+)*\.?)\s*", "", title)
    return re.sub(r"\s+", " ", title)


def sections(toc: list, n_pages: int) -> list[tuple[str, int, int]]:
    """(path, first page, last page) for every bookmark. A section runs to the page before the next bookmark at
    the same or a higher level; pages are 1-based."""
    out, stack = [], []
    for i, (level, title, page) in enumerate(toc):
        if page < 1:
            continue
        stack = stack[: level - 1] + [_clean(title)]
        nxt = next((p for lv, _, p in toc[i + 1 :] if lv <= level and p >= page), n_pages + 1)
        out.append((" > ".join(stack), page, max(page, nxt - 1)))
    return out


def page_texts(path: Path) -> tuple[list, list[str]]:
    with pymupdf.open(path) as doc:
        return doc.get_toc(), [p.get_text().replace("’", "'") for p in doc]


def _top_pages(texts: list[str], pages: set[int], pattern: re.Pattern, n: int) -> list[int]:
    scored = sorted(((len(pattern.findall(texts[p - 1])), -p) for p in pages), reverse=True)
    return [-q for count, q in scored[:n] if count > 0]


def select(kind: str, toc: list, texts: list[str], targets: tuple[Target, ...] = TARGETS) -> dict[int, str]:
    """Pages to keep from one document, each with the reason it is kept ("target: detail")."""
    n = len(texts)
    keep: dict[int, str] = {}

    def add(pages, reason):
        for p in pages:
            keep.setdefault(p, reason)

    if n <= WHOLE_IF_AT_MOST.get(kind, 0):
        add(range(1, n + 1), f"whole: {n} pages or fewer")
        return keep
    secs = sections(toc, n)
    mine = [t for t in targets if t.kind == kind]
    primary_hit = False
    for target in sorted(mine, key=lambda t: t.fallback):  # fallbacks last, so they can see what matched
        if target.fallback and primary_hit:
            continue
        if target.whole:
            dropped = {
                p for path, a, b in secs if any(re.search(d, path) for d in target.drop) for p in range(a, b + 1)
            }
            add((p for p in range(1, n + 1) if p not in dropped), f"{target.name}: whole document")
        if target.front:
            lo, hi = target.front_pages
            add(range(1, min(n, max(lo, round(target.front * n)), hi) + 1), f"{target.name}: front of document")
        for path, a, b in secs:
            if any(re.search(s, path) for s in target.sections):
                if target.max_section_pages and b - a + 1 > target.max_section_pages:
                    continue
                add(range(a, b + 1), f"{target.name}: section {path}")
                primary_hit |= target.primary
        if target.cues:
            region = {
                p for path, a, b in secs if target.within and re.search(target.within, path) for p in range(a, b + 1)
            }
            region = region or set(range(1, n + 1))
            for pattern, k in target.cues:
                add(_top_pages(texts, region, pattern, k), f"{target.name}: cue {CUE_LABELS[pattern]}")
    for pattern in ALWAYS.get(kind, ()):
        add((i for i, t in enumerate(texts, 1) if pattern.search(t)), f"always: {CUE_LABELS[pattern]}")
    return {
        p: r for p, r in sorted(keep.items()) if not (TOC.search(texts[p - 1]) and len(texts[p - 1]) < TOC_MAX_CHARS)
    }


def write_pages(src: Path, pages: list[int], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(src) as doc:
        doc.select([p - 1 for p in pages])
        doc.save(dest, garbage=3, deflate=True)


@dataclass
class Selection:
    rows: list[dict] = field(default_factory=list)

    def add(self, project: str, kind: str, n_pages: int, kept: dict[int, str]) -> None:
        for out_page, (src_page, reason) in enumerate(kept.items(), 1):
            self.rows.append(
                {
                    "project": project,
                    "kind": kind,
                    "n_pages": n_pages,
                    "source_page": src_page,
                    "output_page": out_page,
                    "reason": reason,
                }
            )


def run(
    cohort: pd.DataFrame, pdf_dir: Path = config.PDFS, out_dir: Path = config.PAGES, out_map: Path = config.PAGE_MAP
) -> pd.DataFrame:
    """Write <out_dir>/<project>/<kind>.pdf for every downloaded document, and the page map."""
    sel = Selection()
    for i, project in enumerate(cohort["project"], 1):
        for kind in KINDS:
            src = pdf_path(project, kind, pdf_dir)
            if not src.exists():
                continue
            toc, texts = page_texts(src)
            kept = select(kind, toc, texts)
            write_pages(src, list(kept), out_dir / project / f"{kind}.pdf")
            sel.add(project, kind, len(texts), kept)
        if i % 50 == 0:
            print(f"  {i}/{len(cohort)} reviews")
    page_map = pd.DataFrame(sel.rows)
    if out_map.exists():  # a --projects run updates its rows and keeps the rest
        rest = pd.read_csv(out_map)
        page_map = pd.concat([rest[~rest["project"].isin(cohort["project"])], page_map], ignore_index=True)
    out_map.parent.mkdir(parents=True, exist_ok=True)
    page_map.to_csv(out_map, index=False)
    per_review = page_map.groupby("project").size()
    print(
        f"pages: {len(per_review)} reviews, median {per_review.median():.0f} pages kept per review "
        f"(max {per_review.max()}), {len(page_map)} in all"
    )
    return page_map
