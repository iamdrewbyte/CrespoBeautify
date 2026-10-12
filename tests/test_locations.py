import pytest
from docx import Document

from crespoqa.core.context import RunForm
from crespoqa.core.locate import pages_with
from crespoqa.core.pages import find_soffice
from crespoqa.core.pipeline import process_document
from crespoqa.templates_store.seed import get_template

FORM = RunForm(consultant="Ana Ruiz", client="Acme")


def test_locations_without_layout(sample_docx, tmp_path, settings):
    rep = process_document(sample_docx, tmp_path / "o", get_template("WebApp", "technical"), FORM,
                           settings=settings, use_layout=False)
    whats = [(L["page"], L["what"]) for L in rep.locations]
    assert (1, "'Period:' label removed") in whats
    assert any("Document Details table" in w for _p, w in whats)
    assert all(L["approx"] for L in rep.locations if L["page"] and not L["where"] and L["what"] != "'Period:' label removed")


def test_pages_with():
    pages = ["Cover page Acme Corp", "Findings overview and summary of the results", "Appendix"]
    assert pages_with(pages, "Findings overview and summary") == [2]
    assert pages_with(pages, "no such text anywhere here") == []
    assert pages_with(None, "Findings overview") == []
    assert pages_with(pages, "ab") == []


@pytest.mark.skipif(not find_soffice(), reason="LibreOffice not installed")
def test_long_table_is_reported_across_pages(tmp_path, settings):
    doc = Document()
    doc.add_paragraph("Security Report")
    doc.add_paragraph("Findings overview")
    t = doc.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Reference"; t.cell(0, 1).text = "Description"
    for i in range(1, 120):
        r = t.add_row()
        r.cells[0].text = f"FINDING-{i:03d}"; r.cells[1].text = "Some description text"
    src = tmp_path / "Long.docx"; doc.save(src)
    rep = process_document(src, tmp_path / "o", get_template("WebApp", "technical"), FORM, settings=settings)
    hits = [L for L in rep.locations if L["what"].startswith("Table continues onto page")]
    assert hits and hits[0]["page"] == 1 and "(header row repeats)" in hits[0]["what"]
