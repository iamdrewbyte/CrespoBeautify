"""Upload validation: real .docx, size cap, no macros, not encrypted."""
from __future__ import annotations

import zipfile
from pathlib import Path

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class InvalidDocx(Exception):
    """User-presentable validation failure."""


def validate_docx(path: Path, max_bytes: int) -> None:
    if path.suffix.lower() == ".docm":
        raise InvalidDocx("Macro-enabled files (.docm) are not accepted.")
    if path.suffix.lower() != ".docx":
        raise InvalidDocx("Only .docx files are accepted.")
    size = path.stat().st_size
    if size == 0:
        raise InvalidDocx("The file is empty.")
    if size > max_bytes:
        raise InvalidDocx(f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.")
    with path.open("rb") as fh:
        head = fh.read(8)
    if head == OLE_MAGIC:
        raise InvalidDocx("This file is password protected (encrypted). Remove the password and try again.")
    if not zipfile.is_zipfile(path):
        raise InvalidDocx("This is not a valid .docx file.")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "word/document.xml" not in names:
            raise InvalidDocx("This is not a valid Word document (word/document.xml is missing).")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise InvalidDocx("Macro-enabled documents are not accepted.")
        ct = z.read("[Content_Types].xml").decode("utf-8", "ignore") if "[Content_Types].xml" in names else ""
        if "macroEnabled" in ct:
            raise InvalidDocx("Macro-enabled documents are not accepted.")


_CORE_REL = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"


def check_output_package(path: Path) -> list[str]:
    """Problems that make Word refuse to open a saved file. Empty list = structurally sound.
    Checked on every file the tool writes, before it is handed over."""
    from lxml import etree
    problems: list[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if len(names) != len(set(names)):
                problems.append("a part is stored twice in the package")
            if z.testzip() is not None:
                problems.append("the zip is damaged")
            roots = {}
            for n in set(names):
                if n.endswith((".xml", ".rels")):
                    try:
                        roots[n] = etree.fromstring(z.read(n))
                    except etree.XMLSyntaxError:
                        problems.append(f"{n} is not well-formed XML")
            ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
            rels = roots.get("_rels/.rels")
            if rels is not None:
                kinds = [r.get("Type") for r in rels]
                if kinds.count(_CORE_REL) > 1:
                    problems.append("the package has two core-properties entries")
                ids = [r.get("Id") for r in rels]
                if len(ids) != len(set(ids)):
                    problems.append("duplicate relationship ids in the package")
            nameset = set(names)
            for n, root in roots.items():
                if not n.endswith(".rels"):
                    continue
                base = n.replace("_rels/", "").removesuffix(".rels")
                folder = base.rsplit("/", 1)[0] + "/" if "/" in base else ""
                for r in root:
                    if r.get("TargetMode") == "External":
                        continue
                    t = r.get("Target") or ""
                    full = t.lstrip("/") if t.startswith("/") else _join(folder, t)
                    if full not in nameset:
                        problems.append(f"{n} points at a missing part ({full})")
                ids = [r.get("Id") for r in root]
                if len(ids) != len(set(ids)):
                    problems.append(f"{n} has duplicate relationship ids")
            ct = roots.get("[Content_Types].xml")
            if ct is None:
                problems.append("[Content_Types].xml is missing")
            else:
                over = [o.get("PartName", "").lstrip("/") for o in ct if o.tag.endswith("Override")]
                if len(over) != len(set(over)):
                    problems.append("duplicate content-type entries")
    except zipfile.BadZipFile:
        problems.append("not a valid zip")
    return problems


def _join(folder: str, target: str) -> str:
    parts = (folder + target).split("/")
    out: list[str] = []
    for p in parts:
        if p == "..":
            if out:
                out.pop()
        elif p and p != ".":
            out.append(p)
    return "/".join(out)
