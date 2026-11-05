import os
import stat
import subprocess
import time

from crespoqa.core.pages import render_page_texts


def fake_soffice(tmp_path, body):
    f = tmp_path / "soffice"
    f.write_text("#!/bin/sh\n" + body)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return str(f)


def test_timeout_kills_whole_process_group(tmp_path):
    marker = tmp_path / "child.pid"
    # parent spawns a child (like soffice -> soffice.bin) and both would sleep for a minute
    soffice = fake_soffice(tmp_path, f"sleep 60 &\necho $! > {marker}\nsleep 60\n")
    docx = tmp_path / "a.docx"; docx.write_bytes(b"x")
    t0 = time.time()
    assert render_page_texts(docx, soffice, timeout=1) is None
    assert time.time() - t0 < 10
    pid = int(marker.read_text())
    time.sleep(0.3)
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, "orphaned child process survived"


def test_missing_pdf_returns_none(tmp_path):
    soffice = fake_soffice(tmp_path, "exit 0\n")
    docx = tmp_path / "a.docx"; docx.write_bytes(b"x")
    assert render_page_texts(docx, soffice, timeout=5) is None


def test_row_taller_than_a_page_is_not_locked_but_short_rows_are(tmp_path, settings):
    """A row too tall for one page must stay free to split: Word cuts off what does not fit in a locked row."""
    from docx import Document
    from crespoqa.core.context import RunForm
    from crespoqa.core.pipeline import process_document
    from crespoqa.core.xmlutil import w
    from crespoqa.templates_store.seed import get_template
    from lxml import etree
    import zipfile
    d = Document(); t = d.add_table(rows=3, cols=1)
    t.cell(0, 0).text = "Finding title"; t.cell(1, 0).text = "Description"
    cell = t.cell(2, 0); cell.text = "first paragraph"
    for i in range(120):
        cell.add_paragraph(f"Line number {i} of a very long remediation text")
    src = tmp_path / "tall.docx"; d.save(src)
    rep = process_document(src, tmp_path / "o", get_template("WebApp", "technical"), RunForm(consultant="Ana"), settings=settings, use_layout=False)
    root = etree.fromstring(zipfile.ZipFile(tmp_path / "o" / "tall.docx").read("word/document.xml"))
    rows = list(root.iter(w("tr")))
    locked = [r.find(f"{w('trPr')}/{w('cantSplit')}") is not None for r in rows]
    assert locked == [True, True, False]
    assert any("free to split" in c for t_ in rep.tasks for c in t_.changes)


def test_filename_field_is_written_without_extension():
    from crespoqa.core.fields import _evaluate
    assert _evaluate(" FILENAME ", None, "Report V1.docx") == "Report V1"
