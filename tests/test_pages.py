"""Page selection on small synthetic PDFs with bookmarks."""

import pandas as pd
import pymupdf

from icer_revisions import pages


def _pdf(path, texts, toc=()):
    doc = pymupdf.open()
    for text in texts:
        doc.new_page().insert_text((72, 72), text)
    if toc:
        doc.set_toc(list(toc))
    doc.save(path)
    return path


def _combined_report(n=100):
    """A long combined report laid out like 2022+ CDA-AMC reports."""
    texts = [f"page {i}" for i in range(1, n + 1)]
    texts[1] = "Table of contents\n" + "Executive Summary ........ 5"
    texts[29] = "Table 3: Details of Included Studies\nDesign: phase III RCT\nDetails of studies"
    texts[39] = "The median follow-up was 24 months"
    texts[89] = "Table 7: Summary of the Stepped Analysis of the CDA-AMC Base Case"  # inside the BIA appendix
    toc = [
        (1, "Clinical Review", 3),
        (2, "Executive Summary", 4),
        (2, "Clinical Evidence", 10),
        (2, "References", 50),
        (1, "Pharmacoeconomic_Review", 55),
        (2, "Executive Summary", 56),
        (2, "Economic Review", 60),
        (2, "Appendix 2: Submission Quality", 70),
        (2, "Appendix 4: Additional Details on the CDA-AMC Reanalyses and Sensitivity Analyses", 75),
        (2, "Appendix 5: Submitted Budget Impact Analysis and CDA-AMC Appraisal", 80),
        (1, "Stakeholder Input", 95),
    ]
    return texts, toc


def test_sections_get_paths_and_ranges():
    texts, toc = _combined_report()
    secs = {path: (a, b) for path, a, b in pages.sections(toc, len(texts))}
    assert secs["clinical review > executive summary"] == (4, 9)
    assert secs["pharmacoeconomic review > additional details on the cda-amc reanalyses and sensitivity analyses"] == (
        75,
        79,
    )
    assert secs["stakeholder input"] == (95, 100)


def test_long_combined_report_keeps_the_economic_sections_and_a_few_clinical_pages():
    texts, toc = _combined_report()
    kept = pages.select("pe", toc, texts)
    assert set(range(56, 70)) <= set(kept)  # economic executive summary and economic review
    assert set(range(75, 80)) <= set(kept)  # reanalysis appendix
    assert set(range(4, 10)) <= set(kept)  # clinical executive summary
    assert {30, 40, 90} <= set(kept)  # study table and follow-up by cue; stepped table always
    assert kept[90] == "always: stepped-analysis table"
    assert not set(kept) & ({2} | set(range(70, 75)) | set(range(95, 101)))  # TOC, submission quality, input
    assert not set(range(81, 90)) & set(kept)  # budget impact pages other than the stepped table


def test_short_economic_report_is_kept_whole():
    texts = ["economic page"] * 40
    assert list(pages.select("pe", [], texts)) == list(range(1, 41))


def test_long_report_without_the_usual_bookmarks_falls_back_to_cues():
    texts = ["clinical page"] * 80
    texts[49] = "ICER of $120,000 per QALY gained versus placebo"
    toc = [(1, "Executive Summary", 3), (1, "Introduction", 10), (1, "Cost Information", 45)]
    kept = pages.select("pe", toc, texts)
    assert set(range(3, 10)) <= set(kept) and 50 in kept
    assert kept[50].startswith("fallback: section cost information")
    assert 20 not in kept
    texts[69] = "Incremental: $95,000 per QALY in a scenario"  # outside any kept section: found by cue
    assert pages.select("pe", toc[:2], texts)[70] == "fallback: cue $/QALY figure"


def test_recommendation_drops_stakeholder_and_committee_sections():
    texts = ["rec page"] * 20
    toc = [
        (1, "Recommendation", 1),
        (1, "Stakeholder Perspectives", 8),
        (1, "Economic Evidence", 12),
        (1, "pERC Information", 19),
    ]
    assert list(pages.select("rec", toc, texts)) == list(range(1, 8)) + list(range(12, 19))


def test_clinical_report_keeps_its_front_within_bounds():
    for n, expected in [(56, 15), (108, 27), (197, 30)]:
        kept = pages.select("clin", [], ["clinical"] * n)
        assert list(kept) == list(range(1, expected + 1))


def test_run_writes_one_pdf_per_document_and_a_page_map(tmp_path):
    pdf_dir, out_dir, out_map = tmp_path / "pdfs", tmp_path / "pages", tmp_path / "page_selection.csv"
    pdf_dir.mkdir()
    texts, toc = _combined_report()
    _pdf(pdf_dir / "SR0001-000_pe.pdf", texts, toc)
    _pdf(pdf_dir / "SR0001-000_rec.pdf", ["rec"] * 10)
    page_map = pages.run(pd.DataFrame({"project": ["SR0001-000"]}), pdf_dir, out_dir, out_map)

    pe = page_map[page_map.kind == "pe"]
    with pymupdf.open(out_dir / "SR0001-000" / "pe.pdf") as doc:
        assert len(doc) == len(pe)
        stepped = pe[pe.source_page == 90].output_page.item()
        assert "Stepped Analysis" in doc[stepped - 1].get_text()
    assert (out_dir / "SR0001-000" / "rec.pdf").exists() and not (out_dir / "SR0001-000" / "clin.pdf").exists()
    assert pd.read_csv(out_map).equals(page_map)
