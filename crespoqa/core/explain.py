"""Plain-language reasons for everything the tool could not do or wants checked by hand.

Rule-based on purpose: each entry is written for a known cause, so the explanation is the same every time and never
guessed by a model. Input is only the tool's own messages (error text, step warnings): no report content is used.
Each entry: {level, title, why, fix, page}. Levels: error | warning | check.
"""
from __future__ import annotations

import re

# (pattern on the message, title, why, what to do). First match wins.
_RULES: list[tuple[str, str, str, str]] = [
    (r"password protected|encrypted", "The file is password protected",
     "The document is encrypted, so the tool cannot read it.", "Open it in Word, remove the password (File > Info > Protect Document), save and upload again."),
    (r"not a valid \.docx|not a valid word|word/document\.xml is missing", "This is not a valid .docx file",
     "The file is damaged, or it is another format renamed to .docx.", "Open it in Word and use Save As > Word Document (.docx), then upload that copy."),
    (r"Only \.docx|\.docm|Macro-enabled", "Only plain .docx files are accepted",
     "Old .doc files and macro-enabled files (.docm) are not processed for safety.", "Save the report as a normal Word Document (.docx) and upload again."),
    (r"larger than the", "The file is too large", "The file is bigger than the upload limit.", "Compress the images in Word (Picture Format > Compress Pictures) or ask the admin to raise the limit."),
    (r"file is empty", "The file is empty", "The upload has no content.", "Upload the report again; the copy may not have finished saving."),
    (r"probably open in Word|Cannot write|open in Word or another", "The file is open in Word",
     "Windows will not let the tool replace a file that is open.", "Close the report in Word and run it again."),
    (r"could not produce a file Word will open|two core-properties|package check", "The tool refused to save a file Word may not open",
     "After editing, the tool checks the file's internal structure. This check failed, so it did not hand you a file that could be corrupt.", "Your original is untouched. Run again; if it repeats, send the file name to the tool owner."),
    (r"would overwrite the original", "Output would replace the original", "The output folder is the same as the upload folder.", "Pick a different output folder."),
    (r"Per-document timeout|timed out|Timeout", "The report took too long",
     "The report is very large or complex, or the computer was busy.", "Run it again on its own (not in a large batch). If it repeats, split out big images or ask the admin to raise the time limit."),
    (r"Layout render failed|No layout information|LibreOffice not available|could not be placed", "Page numbers could not be confirmed",
     "The tool numbers pages by drawing a copy of the report with LibreOffice. That copy could not be made or read, so the page numbers are not certain.", "In Word, click the contents table and press F9 (Update field > Page numbers only), then check the page list."),
    (r"is the last line of this page|cell takeover", "A Description may be split from its content",
     "A label such as Description is the last line of a page while its text continues on the next page.", "In Word select that Description row and press Shift+Enter (or Ctrl+Enter) so the section starts on the next page."),
    (r"Table continues onto page", "A table runs over a page break", "The table is longer than the space left on the page.", "Check the break in Word: the header row repeats, but make sure no row is cut in half."),
    (r"Document Details table not found", "Document Details table not found",
     "The tool looks for the table by its title and by its place on page 2. Neither matched, so nothing was filled in.", "Fill the Document Details table by hand, or check the title of the table matches the template."),
    (r"Layout check sees .* on page 1", "A label on page 1 is in an unusual place",
     "The text is visible on the page but it sits in a text box or field the tool does not edit.", "Edit that text by hand in Word."),
    (r"no engagement period was supplied", "No period was entered", "The template needs a period but the form field was empty.", "Type the period in the form and run again."),
    (r"no .* value was supplied", "A placeholder has no value", "A placeholder (e.g. a client name) is in the report but the form did not provide a value.", "Fill that field in the form and run again."),
    (r"column of the version table has no name", "Version table column has no name to replace",
     "The Author / QA Review column is empty, so there was nothing to replace; the tool never writes into empty cells.", "Type the name in that cell by hand."),
    (r"No tables found", "No tables found", "The document has no tables, so table fixes were skipped.", "Nothing to do unless the report should have tables."),
    (r"tracked changes", "The report has tracked changes",
     "The tool leaves tracked changes alone, and its own edits are not tracked.", "Accept or reject the changes in Word first if you want the edits to be visible."),
    (r"unusual structure|text box", "Content the tool cannot edit", "The text sits in a structure the tool does not change.", "Edit it by hand in Word."),
]


def _entry(level: str, msg: str, page=None) -> dict:
    for pat, title, why, fix in _RULES:
        if re.search(pat, msg, re.I):
            return dict(level=level, title=title, why=why, fix=fix, page=page, detail=msg)
    if level == "error":
        return dict(level=level, title="The report could not be processed",
                    why="An unexpected problem stopped the tool. Usually this is an unusual structure in the file that the tool does not know yet.",
                    fix="Your original is untouched. Run it again; if it repeats, tell the tool owner the file name and the step that failed.", page=page, detail=msg)
    return dict(level=level, title=msg.rstrip(".")[:90], why="The tool flagged this but has no more detail.", fix="Check it by hand in Word.", page=page, detail=msg)


def explain_report(error: str | None, tasks, locations) -> list[dict]:
    out: list[dict] = []
    if error:
        out.append(_entry("error", error))
    for t in tasks:
        if t.status == "failed" and not error:
            out.append(_entry("error", f"{t.title} failed"))
        for wmsg in t.warnings:
            out.append(_entry("warning", wmsg))
    for loc in locations or []:
        if re.search(r"last line of this page|Table continues onto page", loc.get("what", ""), re.I):
            out.append(_entry("check", loc["what"], page=loc.get("page")))
    merged: dict[tuple, dict] = {}
    for e in out:                                          # same problem on several pages: one entry listing the pages
        k = (e["title"], e["level"]) if e["level"] == "check" else (e["title"], e["level"], e["detail"])
        if k not in merged:
            merged[k] = dict(e, pages=[])
        if e["page"] and e["page"] not in merged[k]["pages"]:
            merged[k]["pages"].append(e["page"])
    res = []
    for e in merged.values():
        e["page"] = ", ".join(str(n) for n in sorted(e.pop("pages"))) or None
        res.append(e)
    return res
