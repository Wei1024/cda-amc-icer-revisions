import csv

from icer_revisions.listing import COLUMNS, _rejoin, build_cohort, load_listing, split_urls


def test_urls_with_spaces_and_several_urls_per_cell():
    cell = "https://h/DRR/2021/SR0666 Jorveza - CADTH Final Rec.pdf"
    assert split_urls(cell) == ["https://h/DRR/2021/SR0666%20Jorveza%20-%20CADTH%20Final%20Rec.pdf"]
    assert split_urls("http://a/x.pdf http://a/y%20z.pdf") == ["http://a/x.pdf", "http://a/y%20z.pdf"]


def test_unquoted_comma_in_file_name_is_rejoined():
    cells = ["https://h/SR0655 Final Recommendation May 31", "2021_For Posting.pdf", "https://h/sr0655PE.pdf", ""]
    assert _rejoin(cells) == ["https://h/SR0655 Final Recommendation May 31, 2021_For Posting.pdf", cells[2], ""]


HEADER = [*COLUMNS, "field_document_url_1_col_1", "field_document_url_1_col_2"]


def _row(project, date, brand="", urls=()):
    fixed = {h: "" for h in COLUMNS} | {"Project Number": project, "Recommendation Date": date, "Brand Name": brand}
    return [fixed[h] for h in COLUMNS] + list(urls)


def test_variable_width_rows_and_cohort_rules(tmp_path):
    path = tmp_path / "listing.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerow(
            _row("SR0001-000", "Mar 1, 2021", "Alpha", ["internal:/a_rec.pdf", "internal:/a_pe.pdf", "https://h/x.pdf"])
        )
        w.writerow(_row("PC0002-000", "Jun 2, 2022", "", ["https://h/b_rec.pdf"]))
        w.writerow(_row("PC0002-000", "Jun 2, 2022", "Beta"))  # duplicate listing entry without documents
        w.writerow(_row("PH0003-000", "Jun 2, 2022", "Algorithm"))  # excluded project type
        w.writerow(_row("SR0004-000", "Jan 5, 2019", "Old"))  # outside the window

    raw = load_listing(path)
    assert len(raw) == 5
    assert raw.loc[0, "doc_urls"] == "https://www.cda-amc.ca/a_rec.pdf https://www.cda-amc.ca/a_pe.pdf https://h/x.pdf"

    cohort = build_cohort(raw).set_index("project")
    assert list(cohort.index) == ["SR0001-000", "PC0002-000"]
    assert cohort.loc["PC0002-000", "brand_name"] == "Beta"
    assert cohort.loc["PC0002-000", "doc_urls"] == "https://h/b_rec.pdf"
    assert cohort.loc["PC0002-000", "stream"] == "onc"
    assert cohort.loc["SR0001-000", "year"] == 2021
