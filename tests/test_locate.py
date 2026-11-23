"""Finding evidence quotes in small synthetic PDFs, and the viewer's summary of a review."""

import json

import pymupdf
import pytest

from icer_revisions import locate, view

PE = [
    "Executive summary. The sponsor submitted a partitioned survival model.",
    "Results. The ICER was $171,723 per QALY gained versus fulvestrant alone.",
    "Utilities. The trial enrolled post-\nmenopausal women with advanced breast cancer.",
]


@pytest.fixture
def review(tmp_path):
    d = tmp_path / "pages" / "PC0195-000"
    d.mkdir(parents=True)
    for kind, texts in (("pe", PE), ("rec", ["Recommendation. Reimburse with a 15-year time horizon noted."])):
        doc = pymupdf.open()
        for text in texts:
            doc.new_page().insert_text((72, 72), text)
        doc.save(d / f"{kind}.pdf")
    return d


def _one(review, quote, document="pe", page=2):
    return locate.locate_all([{"fields": ["f"], "document": document, "quote": quote, "page": page}], review)[0]


def test_a_quote_on_its_cited_page_is_found_with_a_box(review):
    hit = _one(review, "The ICER was $171,723 per QALY gained")
    assert (hit["status"], hit["page_found"], hit["document_found"]) == ("found", 2, "pe")
    ((x0, y0, x1, y1),) = hit["boxes"]
    assert 70 <= x0 < x1 and 50 < y0 < y1 < 90


def test_punctuation_case_and_hyphenated_line_breaks_do_not_stop_a_match(review):
    assert _one(review, "the icer was 171723 per qaly gained")["status"] == "found"
    hit = _one(review, "enrolled postmenopausal women with advanced breast cancer", page=3)
    assert hit["status"] == "found" and len(hit["boxes"]) == 2  # the match spans two lines


def test_a_quote_elsewhere_is_reported_where_it_is(review):
    hit = _one(review, "submitted a partitioned survival model")
    assert (hit["status"], hit["page_found"]) == ("other_page", 1)
    hit = _one(review, "Reimburse with a 15-year time horizon noted")
    assert (hit["status"], hit["document_found"], hit["page_found"]) == ("other_document", "rec", 1)
    hit = _one(review, "Reimburse with a 15-year time horizon noted", document="clin")
    assert hit["status"] == "other_document"


def test_a_paraphrase_is_not_found(review):
    hit = _one(review, "a lifetime horizon was assumed by the sponsor for all patients")
    assert (hit["status"], hit["page_found"], hit["boxes"]) == ("not_found", None, [])
    assert _one(review, "nothing like this anywhere", document="clin")["status"] == "no_document"


def test_a_loose_quote_is_partial(review):
    hit = _one(review, "The ICER was $171,723 per QALY gained versus fulvestrant and letrozole together")
    assert hit["status"] == "partial" and hit["page_found"] == 2


def test_a_table_row_label_is_found_between_the_cells_of_its_row(tmp_path):
    # how a stepped table's text layer reads: the label's words are interleaved with the other cells
    doc = pymupdf.open()
    doc.new_page().insert_text(
        (72, 72), "CADTH reanalysis BSC 39,810 5.51 Ref. 5: Durability of BSC UPA 15 85,131 6.40 51,113 response"
    )
    label = "CADTH reanalysis 5: Durability of BSC response"
    assert locate.locate(label, doc, 1, skip_numbers=True)["status"] == "found"
    assert locate.locate("CADTH reanalysis 6: Treatment waning", doc, 1, skip_numbers=True)["status"] == "not_found"


def test_the_viewer_summary_shows_a_failed_review_with_its_finished_groups(tmp_path, review):
    out = tmp_path / "extractions" / "x-model-1234abcd"
    out.mkdir(parents=True)
    icers = {
        "sponsor_icer": 157293.0,
        "evidence": [{"field": "sponsor_icer", "document": "pe", "quote": "The ICER was $171,723 per QALY", "page": 2}],
        "notes": "rule 4",
    }
    record = {
        "model": "google/model",
        "error": "price: length",
        "calls": {
            "icers": {"error": None, "seconds": 9.5, "usage": {"cost_usd": 0.1}, "output": icers},
            "price": {"error": "length", "usage": {"cost_usd": 0.05}, "output": None},
        },
    }
    (out / "PC0195-000.json").write_text(json.dumps(record))
    pages = review.parent
    assert view.reviews(out.parent, pages) == [{"project": "PC0195-000", "extractors": ["x-model-1234abcd"]}]
    data = view.review("PC0195-000", out.parent, pages)
    assert data["documents"] == ["rec", "pe"] and [g["group"] for g in data["fields"]][0] == "icers"
    (x,) = data["extractors"]
    assert x["values"] == {"sponsor_icer": 157293.0} and x["notes"] == [{"group": "icers", "text": "rule 4"}]
    assert x["evidence"][0]["status"] == "found" and x["cost_usd"] == pytest.approx(0.15)
    assert x["evidence"][0]["fields"] == ["sponsor_icer"]  # an old record's single `field` is read as a list
