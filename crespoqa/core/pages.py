"""Page estimation without a layout engine, plus optional LibreOffice rendering.

Word stores `w:lastRenderedPageBreak` markers where pages broke when the file was last saved,
and authors add explicit page breaks. Together they give a good page map of top-level body
children. LibreOffice (if installed) is used only as a read-only cross-check; its output is
never used to build the delivered file.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from lxml import etree

from .xmlutil import w


_BREAK_TAGS = None


def _is_page_br(el) -> bool:
    return el.tag == w("br") and el.get(w("type")) == "page"


def _leading_break(el):
    """A lastRenderedPageBreak that comes before any text of `el`: Word marks the START of a new page with it,
    so `el` begins on that new page. (An explicit page break instead ENDS a page, so it never counts here.)"""
    for sub in el.iter():
        if sub.tag == w("lastRenderedPageBreak"):
            return sub
        if sub.tag == w("t") and (sub.text or "").strip():
            return None
    return None


def element_pages(body: etree._Element) -> dict[etree._Element, int]:
    """element -> 1-based page on which each paragraph and table (at any nesting depth) starts.

    Uses Word's saved `lastRenderedPageBreak` markers when present (they reflect the real layout of the
    last save); otherwise explicit page breaks, page-break-before and next-page section breaks.
    A break at the very start of an element moves that element to the new page.
    """
    has_lrpb = next(body.iter(w("lastRenderedPageBreak")), None) is not None
    explicit = not has_lrpb
    page, pending = 1, 0
    out: dict[etree._Element, int] = {}
    consumed: set = set()
    for el in body.iter():
        tag = el.tag
        if tag == w("p") or tag == w("tbl"):
            page += pending; pending = 0
            if tag == w("p"):
                ppr = el.find(w("pPr"))
                if explicit and ppr is not None and ppr.find(w("pageBreakBefore")) is not None:
                    page += 1
            lead = _leading_break(el)
            if lead is not None:
                consumed.add(lead); page += 1
            out[el] = page
            if tag == w("p") and explicit:
                sect = el.find(f"{w('pPr')}/{w('sectPr')}")
                if sect is not None:
                    typ = sect.find(w("type"))
                    if typ is None or typ.get(w("val")) in (None, "nextPage", "oddPage", "evenPage"):
                        pending = 1
        elif (tag == w("lastRenderedPageBreak") or (explicit and _is_page_br(el))) and el not in consumed:
            page += 1
    return out


def body_page_map(body: etree._Element) -> list[tuple[etree._Element, int]]:
    """[(top-level paragraph/table/sdt, page where it starts)]."""
    pages = element_pages(body)
    out = []
    for child in body:
        if child.tag in (w("p"), w("tbl")):
            out.append((child, pages[child]))
        elif child.tag == w("sdt"):
            first = next((e for e in child.iter(w("p"), w("tbl"))), None)
            out.append((child, pages.get(first, 1) if first is not None else 1))
    return out


_WIN = os.name == "nt"


def _program_dirs() -> list[Path]:
    return [Path(os.environ[k]) for k in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA") if os.environ.get(k)]


def find_soffice(configured: str = "") -> str | None:
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found or not _WIN:
        return found
    for base in _program_dirs():                       # the Windows installer does not put LibreOffice on PATH
        for rel in ("LibreOffice/program/soffice.exe", "Programs/LibreOffice/program/soffice.exe"):
            if (base / rel).exists():
                return str(base / rel)
    return None


def find_pdftotext() -> str | None:
    """pdftotext from Poppler: CRESPOQA_PDFTOTEXT, then PATH, then the usual Windows places."""
    configured = os.environ.get("CRESPOQA_PDFTOTEXT", "")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("pdftotext")
    if found or not _WIN:
        return found
    roots = [Path(os.environ[k]) for k in ("LOCALAPPDATA", "ProgramFiles", "USERPROFILE") if os.environ.get(k)]
    for base in roots:
        for pat in ("Microsoft/WinGet/Packages/*oppler*/**/pdftotext.exe", "poppler*/**/pdftotext.exe", "CrespoBeautify/poppler/**/pdftotext.exe"):
            for hit in base.glob(pat):
                return str(hit)
    return None


def render_copy(src: Path, dst: Path, blank_charts: bool = False) -> bool:
    """Write a render-only copy of `src` that LibreOffice can load. Never touches the edited document.
    - Some report generators wrap content in <w:body> inside <w:body>: Word reads that, LibreOffice shows an empty
      page. The inner bodies are unwrapped (same content, same order).
    - blank_charts: a chart LibreOffice cannot import stops the whole file loading; its frame is kept but emptied.
    True when the copy differs from the source."""
    import zipfile
    from .xmlutil import w
    A, C = "{http://schemas.openxmlformats.org/drawingml/2006/main}", "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
    with zipfile.ZipFile(src) as zin:
        root = etree.fromstring(zin.read("word/document.xml"))
        body = root.find(w("body"))
        nested = [b for b in body.iter(w("body")) if b is not body] if body is not None else []
        changed = bool(nested)
        for inner in reversed(nested):                    # innermost first
            parent = inner.getparent()
            at = parent.index(inner)
            for child in list(inner):
                parent.insert(at, child)
                at += 1
            parent.remove(inner)
        if nested:
            # Section properties directly in the body are only valid at the very end: earlier ones (they close a
            # section) go inside an empty paragraph, as Word writes them.
            sects = [c for c in body if c.tag == w("sectPr")]
            for sp in sects[:-1]:
                at = body.index(sp)
                body.remove(sp)
                para = etree.Element(w("p"))
                etree.SubElement(para, w("pPr")).append(sp)
                body.insert(at, para)
            if sects:
                body.remove(sects[-1])
                body.append(sects[-1])
        if blank_charts:
            for gd in list(root.iter(A + "graphicData")):
                if gd.find(C + "chart") is not None:
                    for c in list(gd):
                        gd.remove(c)
                    changed = True
        if not changed:
            return False
        data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
            for info in zin.infolist():
                out.writestr(info.filename, data if info.filename == "word/document.xml" else zin.read(info.filename))
    return True


def _convert(docx: Path, soffice: str, timeout: int, tmp: str, pdftotext: str) -> list[str] | None:
    profile = Path(tmp, "profile").as_uri()
    proc = subprocess.Popen(
        [soffice, "--headless", "--norestore", f"-env:UserInstallation={profile}",
         "--convert-to", "pdf", "--outdir", tmp, str(docx)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if _WIN else {"start_new_session": True}),
    )
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        _kill_group(proc)  # soffice may spawn soffice.bin; always reap our own process group
    pdf = Path(tmp, docx.stem + ".pdf")
    if not pdf.exists():
        return None
    res = subprocess.run([pdftotext, "-layout", str(pdf), "-"], capture_output=True, timeout=60)
    pages = res.stdout.decode("utf-8", "ignore").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    if not any(p.strip() for p in pages):
        return None                                       # a blank render is not a layout: say so instead of guessing
    return pages


class Pages(list):
    """Page texts plus which engine drew them ('word' or 'libreoffice')."""
    engine = "libreoffice"


def render_page_texts(docx: Path, soffice: str | None, timeout: int) -> list[str] | None:
    """Page texts of the document as laid out by Microsoft Word when it is installed (exact page numbers), else by
    LibreOffice (approximate). None if neither can do it."""
    pdftotext = find_pdftotext()
    if not pdftotext:
        return None
    from .wordlayout import render_word_texts, word_available
    if word_available():
        pages = render_word_texts(docx, timeout, pdftotext)
        if pages:
            out = Pages(pages); out.engine = "word"
            return out
    if not soffice:
        return None
    with tempfile.TemporaryDirectory(prefix="crespoqa_lo_") as tmp:
        for i, blank in enumerate((False, True)):         # second try: leave out charts LibreOffice cannot load
            copy = Path(tmp, f"render{i}_" + docx.name)
            try:
                made = render_copy(docx, copy, blank_charts=blank)
            except Exception:
                made = False
            if blank and not made:
                break                                     # nothing different to try
            pages = _convert(copy if made else docx, soffice, timeout, tmp, pdftotext)
            if pages:
                return Pages(pages)
        return None


def _kill_group(proc: subprocess.Popen) -> None:
    if _WIN:                                           # soffice.exe starts soffice.bin: end the whole tree
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, 9)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
