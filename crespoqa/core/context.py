from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .package import DocxPackage


@dataclass
class RunForm:
    consultant: str = ""
    reviewer: str = ""
    client: str = ""
    report_date: str = ""
    period: str = ""

    def value(self, name: str) -> str:
        return getattr(self, name, "") or ""


@dataclass
class Ctx:
    pkg: DocxPackage
    form: RunForm
    output_name: str
    log: logging.Logger
    dry_run: bool = False
    page_texts: list[str] | None = None  # rendered page text (read-only cross-check), if available
    extras: dict = field(default_factory=dict)
    marks: list = field(default_factory=list)      # where the tool acted (see locate.py)

    def mark(self, what: str, el=None, *, page: int | None = None, where: str = "") -> None:
        from .locate import Mark
        self.marks.append(Mark(what, el, page, where))
