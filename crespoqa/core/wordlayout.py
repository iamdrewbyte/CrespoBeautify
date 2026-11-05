"""Exact page layout from Microsoft Word itself (Windows with Word installed, or WSL calling Windows PowerShell).

Word opens a throwaway COPY read-only, with macros off and no window, and exports it to PDF. The page texts of that PDF
are what the tool reads page numbers from, so they match what Word shows (LibreOffice breaks pages differently).
The report is never changed by this. If Word is missing, busy or fails, the caller falls back to LibreOffice.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_WSL_PS = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"

_SCRIPT = r'''
param([string]$In, [string]$Out)
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject Word.Application
$shared = ($w.Documents.Count -gt 0)          # we got the user's own running Word: never close or hide it
if (-not $shared) { $w.Visible = $false; $w.DisplayAlerts = 0; $w.AutomationSecurity = 3 }
$d = $null
try {
  $d = $w.Documents.Open($In, $false, $true, $false)      # path, no conversion prompt, read-only, not in recent files
  $d.ExportAsFixedFormat($Out, 17)                         # 17 = PDF
} finally {
  if ($d) { $d.Close($false) }
  if (-not $shared) { $w.Quit($false) }
}
'''


def _is_wsl() -> bool:
    return os.name != "nt" and os.path.exists(_WSL_PS)


def _powershell() -> str | None:
    if os.name == "nt":
        return shutil.which("powershell") or shutil.which("powershell.exe")
    return _WSL_PS if os.path.exists(_WSL_PS) else None


@functools.lru_cache(maxsize=1)
def word_available() -> bool:
    if os.environ.get("CRESPOQA_LAYOUT", "auto").lower() == "libreoffice":
        return False
    ps = _powershell()
    if not ps:
        return False
    try:
        r = subprocess.run([ps, "-NoProfile", "-Command",
                            "if (Test-Path 'Registry::HKEY_CLASSES_ROOT\\Word.Application\\CLSID') {'yes'}"],
                           capture_output=True, timeout=20)
        return b"yes" in r.stdout
    except Exception:
        return False


def _win_tempdir() -> Path | None:
    """A temp folder both Python and Windows can see."""
    if os.name == "nt":
        return Path(tempfile.gettempdir())
    try:                                              # WSL: the Windows %TEMP% seen through /mnt/c
        out = subprocess.run(["cmd.exe", "/c", "echo %TEMP%"], capture_output=True, timeout=10, cwd="/mnt/c").stdout.decode().strip()
        p = subprocess.run(["wslpath", "-u", out], capture_output=True, timeout=10).stdout.decode().strip()
        return Path(p) if p and Path(p).is_dir() else None
    except Exception:
        return None


def _to_windows(p: Path) -> str:
    if os.name == "nt":
        return str(p)
    return subprocess.run(["wslpath", "-w", str(p)], capture_output=True, timeout=10).stdout.decode().strip()


def render_word_texts(docx: Path, timeout: int, pdftotext: str) -> list[str] | None:
    """Page texts as Word lays the document out, or None (Word missing, failed or too slow)."""
    ps, base = _powershell(), _win_tempdir()
    if not ps or base is None:
        return None
    work = Path(tempfile.mkdtemp(prefix="crespoqa_word_", dir=base))
    try:
        src, pdf, script = work / "doc.docx", work / "doc.pdf", work / "export.ps1"
        shutil.copyfile(docx, src)
        script.write_text(_SCRIPT, encoding="utf-8-sig")
        proc = subprocess.Popen([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", _to_windows(script),
                                 "-In", _to_windows(src), "-Out", _to_windows(pdf)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            return None
        if not pdf.exists() or pdf.stat().st_size == 0:
            return None
        res = subprocess.run([pdftotext, "-layout", str(pdf), "-"], capture_output=True, timeout=90)
        pages = res.stdout.decode("utf-8", "ignore").split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        return pages if any(p.strip() for p in pages) else None
    except Exception:
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
