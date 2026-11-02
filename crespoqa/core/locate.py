"""Where did the tool act? Turns recorded edits into page numbers so a person doing manual QA can jump to them.

Each step records a mark (what it did + the element it touched). After all edits the finished document is rendered
(LibreOffice) and every mark is placed on a page by finding the opening words of its element in the rendered page text.
Word's saved page markers are used only to choose between several candidate pages, or as the fallback (flagged approx).
Read-only: nothing here changes the document. Opening words are for display to the user only; they are never logged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from .pages import element_pages
from .xmlutil import para_text, w


@dataclass
class Mark:
    what: str                    # tool-authored label, e.g. "Table kept together on one page"
    el: etree._Element | None    # element touched (None when `page` is fixed)
    page: int | None = None      # fixed page (e.g. page 1 for the Period label)
    where: str = ""              # non-page place, e.g. "headers/footers"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip().casefold()


def _words(text: str, n: int = 4) -> str:
    return " ".join(text.split()[:n])


def _own_cell_paras(tc):
    for p in tc.iter(w("p")):
        a = p.getparent()
        while a is not None and a.tag != w("tc"):
            a = a.getparent()
        if a is tc:
            yield p


def _row_anchor(tr) -> str:
    for tc in tr.findall(w("tc")):
        for p in _own_cell_paras(tc):
            t = para_text(p).strip()
            if len(_norm(t)) >= 4:
                return _words(t)
    return ""


def _el_anchor(el) -> str:
    if el.tag == w("tbl"):
        tr = el.find(w("tr"))
        return _row_anchor(tr) if tr is not None else ""
    if el.tag == w("tr"):
        return _row_anchor(el)
    for p in ([el] if el.tag == w("p") else el.iter(w("p"))):
        t = para_text(p).strip()
        if len(_norm(t)) >= 4:
            return _words(t)
    return ""


class _Finder:
    def __init__(self, page_texts: list[str] | None, body):
        self.pages = [_norm(t) for t in page_texts] if page_texts else None
        self.est = element_pages(body)

    def find(self, anchor: str, el, start: int = 1) -> int | None:
        """1-based page on which `anchor` appears at or after page `start`; nearest to the marker estimate if several."""
        if self.pages is None:
            return self.est.get(el)
        a = _norm(anchor)
        if len(a) < 4:
            return None
        cands = []
        for probe in dict.fromkeys([a, a[:12], a[:8], a[:6]]):      # a narrow column may wrap the opening words
            if len(probe) < 6 and probe != a:
                continue
            cands = [i + 1 for i in range(max(start, 1) - 1, len(self.pages)) if probe in self.pages[i]]
            if cands:
                break
        if not cands:
            return None
        guess = self.est.get(el)
        return min(cands, key=lambda c: abs(c - guess)) if guess else cands[0]


def locate(body, marks: list[Mark], page_texts: list[str] | None, *, max_rows: int = 60) -> list[dict]:
    """[{page, what, hint, approx}] sorted by page, plus tables that still run over a page break."""
    fin = _Finder(page_texts, body)
    approx = page_texts is None
    order = {el: i for i, el in enumerate(body.iter())}
    out: dict[tuple, dict] = {}

    def add(page, what, hint="", n=1, where=""):
        key = (page, where, what, hint)
        if key in out:
            out[key]["count"] += n
        else:
            out[key] = dict(page=page, where=where, what=what, hint=hint, count=n, approx=approx and page is not None and where == "")

    live = [mk for mk in marks if mk.el is None or mk.el in order]
    live.sort(key=lambda mk: order.get(mk.el, -1))
    for mk in live:
        if mk.page is not None or mk.where:
            add(mk.page, mk.what, where=mk.where)
            continue
        anchor = _el_anchor(mk.el)
        page = fin.find(anchor, mk.el)
        add(page, mk.what, hint=anchor if page else "")

    # tables that still run over a page break: the cell/row hand-checks are here
    tops = [t for t in body.iter(w("tbl")) if next((a for a in t.iterancestors(w("tbl"))), None) is None]
    for tbl in tops:
        rows = tbl.findall(w("tr"))
        if len(rows) < 2 or len(rows) > 400:
            continue
        a_first, a_last = _el_anchor(rows[0]), _row_anchor(rows[-1])
        if not a_first or not a_last or _norm(a_first) == _norm(a_last):
            continue
        p1 = fin.find(a_first, rows[0])
        if p1 is None:
            continue
        p2 = fin.find(a_last, rows[-1], start=p1)
        if p2 is not None and p2 > p1:
            hdr = tbl.find(f"{w('tr')}/{w('trPr')}/{w('tblHeader')}") is not None
            add(p1, f"Table continues onto page {p2 if p2 == p1 + 1 else str(p1 + 1) + '-' + str(p2)}"
                    + (" (header row repeats)" if hdr else "") + ": check the page break", hint=a_first)

    res = sorted(out.values(), key=lambda r: (r["page"] is None, r["page"] or 0, r["what"]))
    return res[:max_rows]


def pages_with(page_texts: list[str] | None, quote: str) -> list[int]:
    """Pages (max 3) whose rendered text contains the opening words of `quote`. Empty when unknown."""
    if not page_texts or not quote:
        return []
    q = _norm(_words(quote, 6))
    if len(q) < 6:
        return []
    return [i + 1 for i, t in enumerate(page_texts) if q in _norm(t)][:3]


_FOOTER = re.compile(r"^(page\s+\d+\s+(of\s+\d+)?|client confidential|confidential|\d+)$", re.I)


def stranded_labels(page_texts: list[str] | None, labels: list[str]) -> list[tuple[int, str]]:
    """(page, label) where a label such as 'Description' is the last real line of a rendered page: its content is on the
    next page (or cut off), i.e. a cell takeover."""
    if not page_texts or not labels:
        return []
    wanted = {l.strip().rstrip(":").casefold() for l in labels if l.strip()}
    out = []
    for i, text in enumerate(page_texts, 1):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        lines = [ln for ln in lines if not _FOOTER.match(re.sub(r"\s{2,}", " ", ln))
                 and not re.fullmatch(r"page\s+\d+\s+of\s+\d+(\s+.*)?", ln, re.I)]
        for ln in lines[-2:]:
            if ln.rstrip(":").casefold() in wanted:
                out.append((i, ln))
                break
    return out
