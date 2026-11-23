"""Find each evidence quote in the review's selected-page PDFs: which page it is on, and the boxes around it.

Quotes are matched word by word after normalising, so line breaks, hyphenation at a line end, curly quotes and
punctuation do not stop a match ("post-\\nmenopausal" matches "postmenopausal", "$171,723" matches "171,723").
The cited page is tried first, then every page of the cited document, then the other attached documents.

Each quote gets a status:
- `found`: on the cited page (at least 90% of its words, in order)
- `other_page`: found, but on a different page of the same document (`page_found` says which)
- `partial`: the best page holds 60-90% of its words: a loose quote, or text the PDF stores oddly
- `other_document`: not in the cited document but in another attached one (`document_found` says which)
- `not_found`: in none of the attached documents: paraphrased or invented, which the spec does not allow
- `no_document`: the cited document was not attached, and the quote is not in the others

This is the quote check of spec §5, and the viewer draws its boxes.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf

FOUND, PARTIAL = 0.9, 0.6


def _norm(word: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", word).lower())


def page_words(page: pymupdf.Page) -> list[tuple[str, tuple[float, float, float, float], tuple[int, int]]]:
    """(normalised word, box, (block, line)) for each word, with words hyphenated across a line end joined."""
    out = []
    raw = page.get_text("words", sort=True)
    i = 0
    while i < len(raw):
        x0, y0, x1, y1, text, block, line, _ = raw[i]
        boxes = [((x0, y0, x1, y1), (block, line))]
        while text.endswith("-") and i + 1 < len(raw) and (raw[i + 1][5], raw[i + 1][6]) != (block, line):
            i += 1
            nx0, ny0, nx1, ny1, ntext, nblock, nline, _ = raw[i]
            text += ntext
            boxes.append(((nx0, ny0, nx1, ny1), (nblock, nline)))
        if word := _norm(text):
            out.extend((word, box, key) for box, key in boxes[:1])
            out.extend(("", box, key) for box, key in boxes[1:])  # the second half: boxed, but not a token
        i += 1
    return out


def _match(words: list, quote: list[str]) -> tuple[float, list[int]]:
    """Share of the quote's words found in order on the page, and the page word indices they cover."""
    if not quote:
        return 0.0, []
    tokens = [w for w, _, _ in words]
    blocks = SequenceMatcher(None, tokens, quote, autojunk=False).get_matching_blocks()
    blocks = [b for b in blocks if b.size >= 2 or (b.size == 1 and len(quote) == 1)]  # ignore stray single words
    if not blocks:
        return 0.0, []
    # keep the densest run: blocks close together on the page, so a quote is not stitched from far-apart words
    runs, run = [], [blocks[0]]
    for b in blocks[1:]:
        if b.a - (run[-1].a + run[-1].size) <= 2 * len(quote):
            run.append(b)
        else:
            runs.append(run)
            run = [b]
    runs.append(run)
    best = max(runs, key=lambda r: sum(b.size for b in r))
    covered = [i for b in best for i in range(b.a, b.a + b.size)]
    # include the trailing halves of hyphenated words inside the match
    covered += [i + 1 for i in covered if i + 1 < len(tokens) and tokens[i + 1] == ""]
    return sum(b.size for b in best) / len(quote), sorted(set(covered))


def _boxes(words: list, covered: list[int]) -> list[list[float]]:
    """One box per text line the match covers."""
    lines: dict[tuple[int, int], list[float]] = {}
    for i in covered:
        (x0, y0, x1, y1), key = words[i][1], words[i][2]
        if key in lines:
            b = lines[key]
            lines[key] = [min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)]
        else:
            lines[key] = [x0, y0, x1, y1]
    return [[round(v, 1) for v in b] for b in lines.values()]


def locate(quote: str, doc: pymupdf.Document, page: int, cache: dict | None = None) -> dict:
    """Where `quote` is in `doc`, trying the cited `page` (1-based) first."""
    cache = {} if cache is None else cache
    tokens = [t for t in (_norm(w) for w in quote.split()) if t]

    def words(p: int) -> list:
        if p not in cache:
            cache[p] = page_words(doc[p - 1])
        return cache[p]

    candidates = [page] if 1 <= page <= len(doc) else []
    score, covered = _match(words(page), tokens) if candidates else (0.0, [])
    best = (score, page, covered)
    if score < FOUND:
        for p in range(1, len(doc) + 1):
            if p != page and (s := _match(words(p), tokens))[0] > best[0]:
                best = (s[0], p, s[1])
    score, found_page, covered = best
    if score >= FOUND:
        status = "found" if found_page == page else "other_page"
    elif score >= PARTIAL:
        status = "partial"
    else:
        return {"status": "not_found", "score": round(score, 2), "page_found": None, "boxes": []}
    return {
        "status": status,
        "score": round(score, 2),
        "page_found": found_page,
        "boxes": _boxes(words(found_page), covered),
    }


def locate_all(evidence: list[dict], pages_dir: Path) -> list[dict]:
    """Each evidence item of one review, with its location added. Documents are opened once."""
    docs = {p.stem: pymupdf.open(p) for p in sorted(pages_dir.glob("*.pdf"))}
    caches = {kind: {} for kind in docs}
    out = []
    try:
        for item in evidence:
            cited = item["document"]
            found = (
                locate(item["quote"], docs[cited], item["page"], caches[cited])
                if cited in docs
                else {"status": "no_document", "score": 0.0, "page_found": None, "boxes": []}
            )
            found["document_found"] = cited if found["page_found"] else None
            if found["status"] in ("not_found", "no_document"):
                for kind, doc in docs.items():
                    if kind != cited and (other := locate(item["quote"], doc, 0, caches[kind]))["score"] >= FOUND:
                        found = other | {"status": "other_document", "document_found": kind}
                        break
            out.append(item | found)
    finally:
        for doc in docs.values():
            doc.close()
    return out
