"""Document picking and content checks. Link sets are real cohort reviews that earlier rules got wrong."""

import pymupdf
import pytest

from icer_revisions.documents import check_pdf, pick_clinical, pick_docs

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


def test_pcodr_final_cgr_for_an_egr():
    pcodr = f"{CDA}/pcodr/Reviews2020/10185PembrolizumabRCC"
    egr = f"{pcodr}_fnEGR_NOREDACT-ABBREV_Post02Apr2020_final.pdf"
    final_cgr = f"{pcodr}_fnCGR_REDACT_Post02Apr2020_final.pdf"
    urls = [
        f"{pcodr}_inCGR_NOREDACT_Post30Jan2020_final.pdf",  # listed first, but superseded
        final_cgr,
        egr,
        f"{pcodr}_ClinicianFeedback_CCOGUDAC_Post02Apr2020_final_Redacted.pdf",
        f"{pcodr}_Combined_Clinician_COIs_Post02Apr2020_final.pdf",
    ]
    assert pick_clinical(urls, egr) == final_cgr


def test_pcodr_initial_cgr_when_no_final():  # PC0186
    pcodr = f"{CDA}/pcodr/Reviews2020/10186CabozantinibHCC"
    egr = f"{pcodr}_fnEGR_NOREDACT-ABBREV_EC_22Apr2020_final.pdf"
    initial = f"{pcodr}_inCGR_NOREDACT_EC_22Apr2020_final.pdf"
    assert pick_clinical([egr, initial, f"{pcodr}_Combined ClinicianFeedback_EC_22Apr2020_final.pdf"], egr) == initial


@pytest.mark.parametrize(
    ("pe", "clinical"),
    [
        ("sr0631-mayzent-pharmacoeconomic-review-report.pdf", "sr0631-mayzent-clinical-review-report.pdf"),
        ("sr0655PE-corzyna.pdf", "sr0655CL-corzyna.pdf"),
        (
            "SR0652 Zeposia - Final Pharmacoeconomic Review Report.pdf",
            "SR0652 Zeposia - Final Clinical Review Report.pdf",
        ),
    ],
)
def test_cdr_clinical_review_report(pe, clinical):
    base = f"{CDA}/attachments/2020-06"
    assert pick_clinical([f"{base}/{clinical}", f"{base}/{pe}"], f"{base}/{pe}") == f"{base}/{clinical}"


@pytest.mark.parametrize(
    "pe",
    [
        "sr0647-entyvio-clinical-economic-review-report.pdf",
        "SR0690-Opsynvi_combined.pdf",
        "PC0407-Voranigo_Main_Report.pdf",
    ],
)
def test_no_clinical_report_when_the_economic_report_is_combined(pe):
    base = f"{CDA}/DRR/2021"
    urls = [f"{base}/{pe}", f"{base}/sr0647-entyvio-clinical-review-report.pdf"]
    assert pick_clinical(urls, f"{base}/{pe}") is None
    assert pick_clinical(urls, None) is None


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
        (["pan-Canadian Oncology Drug Review", "Final Clinical Guidance Report"], "clin", "ok"),
        (["CADTH Common Drug Review", "Clinical Review Report Drug X"], "clin", "ok"),
        (["Pharmacoeconomic Review Report Drug X"], "clin", "no_clinical_title"),
    ],
)
def test_check_pdf(tmp_path, pages, kind, expected):
    assert check_pdf(_pdf(tmp_path / "doc.pdf", pages), kind) == expected
