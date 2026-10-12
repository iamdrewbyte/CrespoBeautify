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


def _details_doc(tmp_path, author_cell="", qa_cell=""):
    doc = Document()
    doc.add_paragraph("Document Details")
    d = doc.add_table(rows=2, cols=2)
    d.cell(0, 0).text = "Document Name"; d.cell(0, 1).text = "Name of report"
    d.cell(1, 0).text = "Date"; d.cell(1, 1).text = "09 October 2026"
    v = doc.add_table(rows=3, cols=4)
    for i, h in enumerate(["Version", "Date", "Author", "QA Review"]):
        v.cell(0, i).text = h
    v.cell(1, 0).text = "0.1"; v.cell(1, 2).text = "Someone Else"
    v.cell(2, 0).text = "1.0"; v.cell(2, 2).text = author_cell; v.cell(2, 3).text = qa_cell
    src = tmp_path / "D.docx"; doc.save(src)
    return src


def _last_row(path):
    t = Document(path).tables[1]
    return [c.text for c in t.rows[-1].cells]


def test_version_table_author_is_filled_but_never_overwritten(tmp_path, settings):
    tpl = get_template("WebApp", "technical")
    src = _details_doc(tmp_path)
    rep = process_document(src, tmp_path / "o", tpl, RunForm(consultant="Ana Ruiz", reviewer="Rob Ray"), settings=settings, use_layout=False)
    assert _last_row(tmp_path / "o" / "D.docx") == ["1.0", "", "Ana Ruiz", "Rob Ray"]
    assert Document(tmp_path / "o" / "D.docx").tables[1].rows[1].cells[2].text == "Someone Else"   # older row untouched
    assert any("Author" in L["what"] for L in rep.locations)

    src2 = _details_doc(tmp_path, author_cell="Already Here")
    rep2 = process_document(src2, tmp_path / "o2", tpl, RunForm(consultant="Ana Ruiz"), settings=settings, use_layout=False)
    assert _last_row(tmp_path / "o2" / "D.docx")[2] == "Already Here"
    assert any("already contains text" in x for t in rep2.tasks for x in t.warnings)


def test_squeezed_details_table_is_spread(tmp_path, settings):
    from crespoqa.core.package import DocxPackage
    from crespoqa.core.xmlutil import w
    doc = Document()
    doc.add_paragraph("Document Details")
    d = doc.add_table(rows=2, cols=2)
    d.cell(0, 0).text = "Document Name"; d.cell(0, 1).text = "x"
    grid = d._tbl.find(w("tblGrid"))
    grid[0].set(w("w"), "7000"); grid[1].set(w("w"), "3000")
    pr = d._tbl.find(w("tblPr"))
    tw = pr.find(w("tblW"))
    if tw is None:
        from lxml import etree
        tw = etree.SubElement(pr, w("tblW"))
    tw.set(w("type"), "pct"); tw.set(w("w"), "3300")
    src = tmp_path / "S.docx"; doc.save(src)
    process_document(src, tmp_path / "o", get_template("WebApp", "technical"), RunForm(consultant="A"), settings=settings, use_layout=False)
    t = next(DocxPackage(tmp_path / "o" / "S.docx").document.iter(w("tbl")))
    assert t.find(f"{w('tblPr')}/{w('tblW')}").get(w("w")) == "5000"
    cols = [int(c.get(w("w"))) for c in t.find(w("tblGrid"))]
    assert cols[1] > cols[0]
