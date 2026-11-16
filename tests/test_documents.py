"""Document picking and content checks. Link sets are real cohort reviews that earlier rules got wrong."""

import pymupdf
import pytest

from icer_revisions.documents import check_pdf, pick_docs

CDA = "https://www.cda-amc.ca/sites/default/files"
CADTH = "https://www.cadth.ca/sites/default/files"


def test_pcodr_final_recommendation_and_egr():
    pcodr = f"{CDA}/pcodr/Reviews2020/10185PembrolizumabRCC"
    initial = f"{pcodr}_inRec_2020-01-30_ApprovedbyChair_Post_30Jan2020_final.pdf"
    final = f"{pcodr}_fnRec_2020-03-31_ApprovedpERCChair_Post02Apr2020_final.pdf"
    egr = f"{pcodr}_fnEGR_NOREDACT-ABBREV_Post02Apr2020_final.pdf"
    urls = [
        initial,  # listed first, but superseded by the final recommendation
        final,
        egr,
        f"{pcodr}_fnCGR_REDACT_Post02Apr2020_final.pdf",  # clinical guidance report
        f"{pcodr}_SponsorFeedback_Post24Mar2020_final.pdf",
        f"{pcodr}_PatientInput_KCC_COI_Post02Apr2020_final_Redacted.pdf",
    ]
    assert pick_docs(urls) == (final, egr)


def test_class_review_recommendation_is_not_the_reviews_own():
    rec = f"{CADTH}/DRR/2022/SR0698%20Bimzelx%20-%20CADTH%20Final%20Rec%20Final.pdf"
    report = f"{CADTH}/DRR/2022/SR0698-Bimzelx.pdf"
    urls = [
        f"{CADTH}/DRR/2023/TSDrugClas/TS0001/TS0001-PsO-Updated-Streamlined-Rec.pdf",
        rec,
        report,
        f"{CADTH}/DRR/2022/SR0698-Bimzelx-Stakeholder-Feedback.pdf",
    ]
    assert pick_docs(urls) == (rec, report)


def test_patient_input_is_never_the_economic_report():
    rec = f"{CDA}/cdr/complete/SR0644%20Entresto%20-%20%20CDEC%20Final%20Recommendation_for%20Posting.pdf"
    urls = [rec, f"{CDA}/cdr/relatedinfo/SR0644_Entresto%20Resubmission_PI%20Submission.pdf"]
    assert pick_docs(urls) == (rec, None)


def test_pe_suffix_beats_clinical_report():
    rec = (
        f"{CDA}/cdr/complete/SR0655%20Corzyna%20-%20CDEC%20Final%20Recommendation%20May%2031,%202021_For%20Posting.pdf"
    )
    pe = f"{CDA}/attachments/2021-08/sr0655PE-corzyna.pdf"
    urls = [rec, f"{CDA}/attachments/2021-08/sr0655CL-corzyna.pdf", pe]
    assert pick_docs(urls) == (rec, pe)


def test_combined_report_preferred_over_supplement_and_input():
    urls = [
        f"{CDA}/DRR/2026/SR0881-Hepcludex_Recommendation.pdf",
        f"{CDA}/DRR/2026/SR0881-Hepcludex_Combined_Review_Supplemental_Material.pdf",
        f"{CDA}/DRR/2026/SR0881-Hepcludex_Combined_Review.pdf",
        f"{CDA}/DRR/2026/SR0881-Clinician_Input.pdf",
    ]
    assert pick_docs(urls) == (urls[0], urls[2])


def test_no_documents():
    assert pick_docs([]) == (None, None)
    assert pick_docs(["https://example.org/page.html"]) == (None, None)


def _pdf(path, pages):
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    return path


@pytest.mark.parametrize(
    ("pages", "kind", "expected"),
    [
        (["CADTH Reimbursement Recommendation Drug X"], "rec", "ok"),
        (["Clinical Review Report Drug X"], "rec", "no_recommendation_title"),
        (
            ["Reimbursement Review Drug X", "Summary", "ICER, incremental cost, per QALY", "ICER, budget impact"],
            "pe",
            "ok",
        ),
        (
            ["Clinical Review Report", "see the pharmacoeconomic report for cost-effectiveness"],
            "pe",
            "no_economic_content",
        ),
        (["CADTH Reimbursement Recommendation Drug X", "cost-effectiveness"], "pe", "looks_like_recommendation"),
        (["Patient Group Input Submission"], "pe", "no_economic_content"),
    ],
)
def test_check_pdf(tmp_path, pages, kind, expected):
    assert check_pdf(_pdf(tmp_path / "doc.pdf", pages), kind) == expected
