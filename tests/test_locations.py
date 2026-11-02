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


def _details_doc(tmp_path, qa_cell="Old Reviewer"):
    doc = Document()
    doc.add_paragraph("Document Details")
    d = doc.add_table(rows=2, cols=2)
    d.cell(0, 0).text = "Document Name"; d.cell(0, 1).text = "Name of report"
    d.cell(1, 0).text = "Date"; d.cell(1, 1).text = "09 October 2026"
    v = doc.add_table(rows=3, cols=4)
    for i, h in enumerate(["Version", "Date", "Author", "QA Review"]):
        v.cell(0, i).text = h
    v.cell(1, 0).text = "0.1"; v.cell(1, 2).text = "Template Author"
    v.cell(2, 0).text = "1.0"; v.cell(2, 3).text = qa_cell
    src = tmp_path / "D.docx"; doc.save(src)
    return src


def test_version_table_author_name_is_replaced_and_empty_cells_stay_empty(tmp_path, settings):
    tpl = get_template("WebApp", "technical")
    src = _details_doc(tmp_path)
    rep = process_document(src, tmp_path / "o", tpl, RunForm(consultant="Ana Ruiz", reviewer="Rob Ray"), settings=settings, use_layout=False)
    rows = [[c.text for c in r.cells] for r in Document(tmp_path / "o" / "D.docx").tables[1].rows]
    assert rows[1][2] == "Ana Ruiz"            # the existing author is replaced
    assert rows[2][2] == ""                    # the empty Author cell is NOT filled
    assert rows[2][3] == "Rob Ray"             # the existing QA reviewer is replaced
    assert rows[1][3] == ""
    assert any("Author" in L["what"] for L in rep.locations)

    rep2 = process_document(src, tmp_path / "o2", tpl, RunForm(consultant="Ana Ruiz"), settings=settings, use_layout=False)
    assert [c.text for c in Document(tmp_path / "o2" / "D.docx").tables[1].rows[2].cells][3] == "Old Reviewer"   # no reviewer supplied


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


def _finding_doc(tmp_path, filler: int):
    doc = Document()
    for i in range(filler):
        doc.add_paragraph(f"Filler paragraph number {i} for the page")
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "FIND-001"; t.cell(0, 1).text = "Client asset"
    t.cell(1, 0).merge(t.cell(1, 1)); t.cell(1, 0).text = "Description"
    c = t.cell(2, 0).merge(t.cell(2, 1))
    c.text = "Summary of the finding"
    for k in range(14):
        c.add_paragraph(f"Detail line {k} that explains the finding under the Description label")
    src = tmp_path / f"F{filler}.docx"; doc.save(src)
    return src


@pytest.mark.skipif(not find_soffice(), reason="LibreOffice not installed")
def test_description_label_is_never_left_alone_at_page_bottom(tmp_path, settings):
    from crespoqa.core.locate import stranded_labels
    from crespoqa.core.pages import render_page_texts
    from crespoqa.core.package import DocxPackage
    from crespoqa.core.xmlutil import w
    from crespoqa.templates_store.textfmt import from_text, to_text
    on = get_template("WebApp", "technical")
    off = on.model_copy(deep=True)
    for s in off.steps:
        if s.type == "table_fix":
            s.params.keep_with_content = []
            s.params.keep_together_max_rows = 0
    so = find_soffice()
    case = None
    for n in range(14, 40):                       # find a layout where the label really lands at the bottom without the rule
        src = _finding_doc(tmp_path, n)
        process_document(src, tmp_path / f"off{n}", off, FORM, settings=settings, use_layout=False)
        texts = render_page_texts(tmp_path / f"off{n}" / src.name, so, 120)
        if stranded_labels(texts, ["Description"]):
            case = (n, src); break
    assert case, "could not build a page layout that strands the label"
    n, src = case
    only_rule = on.model_copy(deep=True)          # prove the new rule on its own, without the general keep-together rule
    for st in only_rule.steps:
        if st.type == "table_fix":
            st.params.keep_together_max_rows = 0
    rep = process_document(src, tmp_path / "on", only_rule, FORM, settings=settings)
    texts = render_page_texts(tmp_path / "on" / src.name, so, 120)
    assert not stranded_labels(texts, ["Description"])
    assert any("label kept with its content" in L["what"] for L in rep.locations)
    # the Notepad format round-trips the new rule
    assert 'keep-with-next "Description"' in to_text(on.steps)
    back = next(x for x in from_text(to_text(on.steps)) if x.type == "table_fix")
    assert back.params.keep_with_content == ["Description"]
    off_text = to_text(off.steps)
    assert "keep-with-next off" in off_text
    assert next(x for x in from_text(off_text) if x.type == "table_fix").params.keep_with_content == []
