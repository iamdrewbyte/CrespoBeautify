"""Per-document pipeline. Stage A: analysis. Stage B: XML edits. Stage C: finalise + save."""
from __future__ import annotations

import logging
import re
import shutil
import time
import uuid
from pathlib import Path

from ..templates_store import models as m
from .change_report import DocReport, TaskResult
from .config import Settings, load_settings
from .context import Ctx, RunForm
from .docx_validate import InvalidDocx, check_output_package, validate_docx
from .logging_setup import JobLogger
from .package import DocxPackage
from .locate import locate, stranded_labels
from .pagenum import _plan_contents, contents_labels, pages_from_layout, refresh_page_numbers
from .pages import find_soffice, render_page_texts
from .wordlayout import word_available
from .steps import fields_steps, tables, text
from .xmlutil import para_text, w

RUNNERS = {
    "period_removal": text.period_removal,
    "placeholders": text.placeholders,
    "find_replace": text.find_replace,
    "toc_update": fields_steps.toc_update,
    "document_details": tables.document_details,
    "table_fix": tables.table_fix,
    "final_refresh": fields_steps.final_refresh,
}


STEP_LABELS = {
    "period_removal": "Remove 'Period:' label (page 1)",
    "placeholders": "Fill placeholders",
    "find_replace": "Custom find/replace",
    "toc_update": "Update table of contents",
    "document_details": "Update & format Document Details table",
    "table_fix": "Fix table splits across pages",
    "final_refresh": "Final global refresh",
}


def plan_for(template: m.Template) -> list[dict]:
    return [{"key": s.type, "label": STEP_LABELS[s.type]} for s in template.steps if s.enabled and s.type in RUNNERS]


def _final_layout(ctx, pkg, work, use_layout, settings):
    """Page texts of the finished (edited) document, rendered once and shared by the page numbers and the locations."""
    if "layout_texts" in ctx.extras:
        return ctx.extras["layout_texts"]
    texts = None
    soffice = find_soffice(settings.soffice) if use_layout else None
    if soffice or (use_layout and word_available()):
        tmp = work / "layout_probe.docx"
        pkg.save(tmp)
        texts = render_page_texts(tmp, soffice, min(settings.doc_timeout_s, 120)) or None
    ctx.extras["layout_texts"] = texts
    return texts


CLIP_CHECK_MIN_LINES = 24     # rows shorter than this (in text lines) cannot be taller than a page


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", s)).strip().casefold()


def _rescue_clipped_rows(ctx, pkg, work, use_layout, settings, log, res_changes: list) -> None:
    """Safety net against losing text. A row set not to split but taller than the page is cut off by Word. After
    the edits the document is laid out (by Word when available); any row we locked whose last paragraph is missing
    from the rendered pages is unlocked again. Repeats once, because moving rows can change what fits."""
    locked = ctx.extras.get("cantsplit_rows") or []
    if not locked or not use_layout:
        return
    unlocked = 0
    for _round in range(2):
        ctx.extras.pop("layout_texts", None)
        texts = _final_layout(ctx, pkg, work, use_layout, settings)
        if not texts:
            return
        whole = _norm_text(" ".join(texts))
        clipped = []
        for tr in locked:
            if tr.getparent() is None:
                continue
            if tables.row_lines(tr) < CLIP_CHECK_MIN_LINES:
                continue                                            # far too short to be taller than a page
            paras = [_norm_text(para_text(p)) for p in tr.iter(w("p"))]
            real = [p for p in paras if p]                          # every non-empty paragraph, however short
            if len(real) < 3:
                continue
            # the same sentence can repeat inside a row (e.g. one solution per operating system), so test the JUNCTION of
            # the last two paragraphs, which is unique to the true end of the row
            key = (real[-2][-30:] + " " + real[-1][:30]).strip()
            if len(key) >= 8 and key not in whole:
                clipped.append(tr)
        if not clipped:
            break
        for tr in clipped:
            trpr = tr.find(w("trPr"))
            cs = trpr.find(w("cantSplit")) if trpr is not None else None
            if cs is not None:
                trpr.remove(cs)
            locked.remove(tr)
            unlocked += 1
        pkg.touch("word/document.xml")
    if unlocked:
        ctx.extras.pop("layout_texts", None)                        # the layout changed: render again for the numbers
        res_changes.append(f"Unlocked {unlocked} row(s) that Word would have cut off (their text did not fit on one page): they split across pages instead")
        log.info(f"Unlocked {unlocked} clipped row(s)")


def _apply_page_numbers(ctx, pkg, work, use_layout, settings, log) -> TaskResult:
    """Render the already-edited document and write the section page numbers into the contents."""
    res = TaskResult("page_numbers", "Contents page numbers")
    layout = None
    texts = _final_layout(ctx, pkg, work, use_layout, settings)
    if texts:
        layout = pages_from_layout(pkg, texts, contents_labels(pkg))
    st = refresh_page_numbers(pkg, layout)
    if st.contents_tables:
        for plan in _plan_contents(pkg.document.find(w("body"))):
            tbl = next(plan["cells"][0].iterancestors(w("tbl")), None) if plan["cells"] else None
            if tbl is not None:
                ctx.mark(f"Contents page numbers set ({len(plan['names'])} entries)", tbl)
    res.counts.update(source=0, set=st.contents_cells + st.updated)
    if st.source == "layout":
        eng = "Word's own layout" if getattr(texts, "engine", "") == "word" else "a LibreOffice layout (approximate: press F9 in Word to confirm)"
        res.changes.append(f"Page numbers read from {eng} of the finished document ({len(layout)} section(s) placed)")
    elif st.source == "markers":
        res.changes.append("Page numbers estimated from Word's saved page markers (LibreOffice not available)")
        res.warnings.append("These numbers are approximate. In Word, select the contents and press F9 to make them exact.")
    else:
        if st.pagerefs:
            res.warnings.append("No layout information available for the page numbers. In Word, select the contents and press F9.")
        return res
    if st.contents_tables:
        res.changes.append(f"Contents table: {st.contents_cells} page number(s) set"
                           + (f", {st.contents_fields_made} turned into refreshable page-reference fields" if st.contents_fields_made else "")
                           + (f", {st.contents_cleaned} stray digit(s) removed" if st.contents_cleaned else ""))
    if st.updated:
        res.changes.append(f"{st.updated} other page reference(s) updated")
    if st.unresolved:
        res.warnings.append(f"{st.unresolved} contents row(s) could not be placed; check them in Word (select, F9).")
    if not (st.contents_cells or st.updated) and not st.pagerefs:
        res.changes.append("No contents or page references to update")
    return res


def output_name_for(src: Path, suffix: str = "") -> str:
    return f"{src.stem}{suffix}.docx"


def process_document(
    src: Path,
    out_dir: Path | None,
    template: m.Template,
    form: RunForm,
    *,
    settings: Settings | None = None,
    dry_run: bool = False,
    use_layout: bool = True,
    job_id: str | None = None,
    progress=None,  # callable(step_key, state) for live UI; state: running|ok|warning|failed
    layout_out: list | None = None,  # receives the rendered page texts (memory only) so reviews can name pages
) -> DocReport:
    settings = settings or load_settings()
    job_id = job_id or uuid.uuid4().hex[:8]
    log = JobLogger(logging.getLogger("crespoqa"), {"job": job_id})
    out_name = output_name_for(src, settings.output_suffix)
    report = DocReport(
        job_id=job_id, input_name=src.name, report_type=template.report_type, template=template.name,
        template_version=template.version, processed_by=form.consultant.strip(), dry_run=dry_run,
        output_name=None if dry_run else out_name,
    )
    started = time.monotonic()
    work = settings.temp_dir / uuid.uuid4().hex
    try:
        work.mkdir(parents=True, exist_ok=True)
        validate_docx(src, settings.max_file_bytes)
        copy = work / src.name
        shutil.copyfile(src, copy)  # the original is never opened for writing

        pkg = DocxPackage(copy)
        ctx = Ctx(pkg=pkg, form=form, output_name=out_name, log=log, dry_run=dry_run)

        pre = TaskResult("prechecks", "Pre-checks")
        has_revisions = pkg.track_revisions_on() or any(True for _ in pkg.document.iter(w("ins"), w("del")))
        if has_revisions:
            pre.warnings.append("Document contains tracked changes; they were left untouched and edits made by this tool are not tracked.")
        # Stage A: optional read-only layout render for cross-checks
        if use_layout:
            soffice = find_soffice(settings.soffice)
            if soffice or word_available():
                ctx.page_texts = render_page_texts(copy, soffice, min(settings.doc_timeout_s, 120))
                if ctx.page_texts is None:
                    pre.warnings.append("Layout render failed or timed out; page cross-checks skipped.")
            else:
                pre.changes.append("Neither Word nor LibreOffice is available: page checks use Word's saved page markers only.")
        pre.changes.extend(pkg.repairs)
        report.tasks.append(pre)

        steps = [s for s in template.steps if s.enabled and s.type in RUNNERS]
        for i, step in enumerate(steps, 1):
            if time.monotonic() - started > settings.doc_timeout_s:
                raise TimeoutError(f"Per-document timeout of {settings.doc_timeout_s}s exceeded")
            t0 = time.monotonic()
            if progress:
                progress(step.type, "running")
            try:
                result = RUNNERS[step.type](ctx, step.params)
            except Exception as exc:  # a failing step fails the document, with the step named
                log.error(f"[Task {i}/{len(steps)}] {step.type} FAILED ({type(exc).__name__})")
                if progress:
                    progress(step.type, "failed")
                raise
            report.tasks.append(result)
            if progress:
                progress(step.type, result.status)
            log.info(f"[Task {i}/{len(steps)}] {result.title} ... {result.status.upper()} {result.counts} ({time.monotonic() - t0:.2f}s)")

        rescue_notes: list[str] = []
        try:
            _rescue_clipped_rows(ctx, pkg, work, use_layout, settings, log, rescue_notes)
        except Exception as exc:                                    # a safety check must never fail the document
            log.warning(f"Clipped-row check skipped ({type(exc).__name__})")
        if rescue_notes:
            fixed = TaskResult("text_safety", "Text safety check")
            fixed.changes.extend(rescue_notes)
            report.tasks.append(fixed)

        if ctx.extras.get("want_page_numbers"):
            report.tasks.append(_apply_page_numbers(ctx, pkg, work, use_layout, settings, log))

        # Where to check by hand: pages of everything the tool touched, and tables still crossing a page break
        try:
            texts = _final_layout(ctx, pkg, work, use_layout, settings)
            report.locations = locate(pkg.document.find(w("body")), ctx.marks, texts)
            tf = next((s.params for s in template.steps if s.enabled and s.type == "table_fix"), None)
            for pg, label in stranded_labels(texts, tf.keep_with_content if tf else []):
                report.locations.append(dict(page=pg, where="", what=f"'{label}' is the last line of this page: its content may be cut off or on the next page (cell takeover). Check it",
                                             hint="", count=1, approx=False))
            report.locations.sort(key=lambda r: (r["page"] is None, r["page"] or 0, r["what"]))
            if layout_out is not None and texts:
                layout_out.extend(texts)
        except Exception as exc:              # a helper list must never fail the document
            log.warning(f"Could not work out page locations ({type(exc).__name__})")

        # Stage C: save
        if not dry_run:
            if out_dir is None:
                raise ValueError("out_dir required unless dry_run")
            out_dir.mkdir(parents=True, exist_ok=True)
            if (out_dir / out_name).resolve() == src.resolve():
                raise InvalidDocx("The output would overwrite the original file. Choose a different output folder.")
            try:
                pkg.save(out_dir / out_name)
                bad = [b for b in check_output_package(out_dir / out_name) if b not in check_output_package(src) or "core-properties" in b]   # only what this tool introduced (never a doubled properties entry)
                if bad:
                    (out_dir / out_name).unlink(missing_ok=True)
                    log.error("Output failed the package check: " + "; ".join(bad))
                    raise InvalidDocx("The tool could not produce a file Word will open (" + "; ".join(bad[:2]) + "). Nothing was saved, your original is untouched.")
            except PermissionError:
                raise InvalidDocx(f"Cannot write '{out_name}'. It is probably open in Word or another program: close it and run again.") from None
    except InvalidDocx as exc:
        report.error = str(exc)
        log.warning("Rejected upload: " + type(exc).__name__)
    except Exception as exc:
        report.error = f"{type(exc).__name__}: {exc}" if not isinstance(exc, TimeoutError) else str(exc)
        log.error(f"Document failed ({type(exc).__name__})")
    finally:
        shutil.rmtree(work, ignore_errors=True)
        report.duration_s = time.monotonic() - started
        report.finalize()
        log.info(f"Done: {report.status} in {report.duration_s:.1f}s")
    return report
