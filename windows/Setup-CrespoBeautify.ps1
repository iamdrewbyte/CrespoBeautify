<#
  CrespoBeautify: one-click setup for Windows 10/11.
  Installs Python, LibreOffice, Poppler and (optionally) Ollama + the Qwen model, builds the app environment,
  writes the settings, creates a desktop shortcut and runs a self-test. Safe to run again: finished steps are skipped.

  Run:  powershell -ExecutionPolicy Bypass -File Setup-CrespoBeautify.ps1            (everything)
        powershell -ExecutionPolicy Bypass -File Setup-CrespoBeautify.ps1 -NoAI      (skip Ollama + the 4.7 GB model)
  Nothing leaves your computer except the downloads of those programs and the model.
#>
param(
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'CrespoBeautify'),
  [switch]$NoAI,
  [string]$Model = 'qwen2.5:7b-instruct'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $env:TEMP 'CrespoBeautify-setup.log'
Start-Transcript -Path $log -Append | Out-Null

function Step($n, $t) { Write-Host ""; Write-Host "[$n] $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "    OK  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    !!  $t" -ForegroundColor Yellow }
function Fail($t) { Write-Host "    XX  $t" -ForegroundColor Red; Stop-Transcript | Out-Null; Read-Host "Press Enter to close"; exit 1 }

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Winget-Install($id, $label) {
  Write-Host "    installing $label (a Windows permission prompt may appear)..."
  & winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements 2>&1 | ForEach-Object { Write-Host "      $_" }
  Refresh-Path
}

# Python 3.10+ that is a real install (not the Microsoft Store stub)
function Find-Python {
  foreach ($c in @('py -3.12','py -3.11','py -3.13','py -3.10','python')) {
    try {
      $parts = $c.Split(' '); $exe = $parts[0]; $args2 = @($parts | Select-Object -Skip 1) + @('-c','import sys;print(sys.executable if sys.version_info>=(3,10) else "")')
      if (-not (Have $exe)) { continue }
      $out = (& $exe @args2 2>$null | Select-Object -First 1)
      if ($out -and (Test-Path $out) -and $out -notmatch 'WindowsApps') { return $out }
    } catch {}
  }
  return $null
}

Write-Host "CrespoBeautify setup" -ForegroundColor White
Write-Host "Install folder: $InstallDir"

# ---- 0. winget
Step '0/7' 'Checking winget (the Windows app installer)'
if (-not (Have 'winget')) { Fail "winget was not found. Install 'App Installer' from the Microsoft Store, then run this setup again." }
Ok 'winget available'

# ---- 1. Python
Step '1/7' 'Python'
$py = Find-Python
if (-not $py) { Winget-Install 'Python.Python.3.12' 'Python 3.12'; $py = Find-Python }
if (-not $py) { Fail 'Python could not be installed. Install Python 3.12 from python.org (tick "Add to PATH") and run this setup again.' }
Ok $py

# ---- 2. LibreOffice
Step '2/7' 'LibreOffice (used to check page numbers)'
function Find-Soffice {
  foreach ($b in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs")) {
    if ($b -and (Test-Path "$b\LibreOffice\program\soffice.exe")) { return "$b\LibreOffice\program\soffice.exe" }
  }
  if (Have 'soffice') { return (Get-Command soffice).Source }
  return $null
}
$soffice = Find-Soffice
if (-not $soffice) { Winget-Install 'TheDocumentFoundation.LibreOffice' 'LibreOffice'; $soffice = Find-Soffice }
if ($soffice) { Ok $soffice } else { Warn 'LibreOffice not found: the tool still works but page numbers will be less certain. Install it from libreoffice.org later.' }

# ---- 3. Poppler (pdftotext)
Step '3/7' 'Poppler (reads the page text)'
function Find-Pdftotext {
  if (Have 'pdftotext') { return (Get-Command pdftotext).Source }
  $hit = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages","$InstallDir\poppler" -Filter pdftotext.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($hit) { return $hit.FullName }
  return $null
}
$pdftotext = Find-Pdftotext
if (-not $pdftotext) { Winget-Install 'oschwartz10612.Poppler' 'Poppler'; $pdftotext = Find-Pdftotext }
if ($pdftotext) { Ok $pdftotext } else { Warn 'Poppler not found: page numbers will be less certain. Install "Poppler" with winget later.' }

# ---- 4. App files + environment
Step '4/7' 'The CrespoBeautify app'
$app = Join-Path $InstallDir 'app'
$srcApp = Join-Path $here 'app'
if (-not (Test-Path $srcApp)) { $srcApp = Split-Path -Parent $here }         # running from the source tree
if ((Resolve-Path $srcApp).Path -ne (Resolve-Path $app -ErrorAction SilentlyContinue).Path) {
  New-Item -ItemType Directory -Force -Path $app | Out-Null
  & robocopy $srcApp $app /E /XD .venv .git data logs __pycache__ tests docs out_test .pytest_cache /XF *.db .env *.docx inspect_output.json /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { Fail "Copying the app failed (robocopy code $LASTEXITCODE)." }
}
$venv = Join-Path $InstallDir 'venv'
if (-not (Test-Path "$venv\Scripts\python.exe")) { & $py -m venv $venv; if ($LASTEXITCODE) { Fail 'Could not create the Python environment.' } }
& "$venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$venv\Scripts\python.exe" -m pip install --quiet -r (Join-Path $app 'requirements-runtime.txt')
if ($LASTEXITCODE) { Fail 'Installing the app libraries failed (is the internet connection on?).' }
Ok 'app and libraries installed'

# ---- 5. AI model
$aiOn = 'false'
Step '5/7' 'Local AI review (Ollama + Qwen model, about 4.7 GB)'
if ($NoAI) { Warn 'Skipped (-NoAI). The QA clean-up works without it; run setup again without -NoAI to add it.' }
else {
  if (-not (Have 'ollama')) { Winget-Install 'Ollama.Ollama' 'Ollama' }
  if (-not (Have 'ollama')) { $o = "$env:LOCALAPPDATA\Programs\Ollama"; if (Test-Path "$o\ollama.exe") { $env:Path += ";$o" } }
  if (-not (Have 'ollama')) { Warn 'Ollama could not be installed: AI review will be unavailable.' }
  else {
    $env:OLLAMA_NO_CLOUD = '1'                       # the model server makes no outside connection
    [Environment]::SetEnvironmentVariable('OLLAMA_NO_CLOUD','1','User')
    try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null }
    catch { Start-Process ollama -ArgumentList 'serve' -WindowStyle Hidden; 1..20 | ForEach-Object { try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 1 | Out-Null; break } catch { Start-Sleep 1 } } }
    $have = (& ollama list 2>$null) -match [regex]::Escape(($Model.Split(':')[0]))
    if (-not $have) { Write-Host "    downloading $Model (one time, large)..."; & ollama pull $Model; if ($LASTEXITCODE) { Warn 'Model download failed: run setup again later.' } }
    if ((& ollama list 2>$null) -match [regex]::Escape(($Model.Split(':')[0]))) { $aiOn = 'true'; Ok "model $Model ready" }
  }
}

# ---- 6. Settings + shortcut
Step '6/7' 'Settings and shortcut'
$envFile = Join-Path $app '.env'
if (-not (Test-Path $envFile)) {
@"
# CrespoBeautify settings (this file stays on this computer)
AI_ENABLED=$aiOn
AI_BASE_URL=http://localhost:11434/v1
AI_MODEL=$Model
AI_TIMEOUT_S=300
CRESPOQA_PORT=8000
# CRESPOQA_SAVE_DIR=C:\Users\you\Downloads   (uncomment to save results back into a folder; the old file is kept in CrespoBeautify_originals)
"@ | Set-Content -Encoding ASCII $envFile
  Ok 'settings written'
} else { Ok 'settings already exist: left unchanged' }
if ($soffice)    { Add-Content $envFile "CRESPOQA_SOFFICE=$soffice" }
if ($pdftotext)  { Add-Content $envFile "CRESPOQA_PDFTOTEXT=$pdftotext" }

$start = Join-Path $app 'windows\Start-CrespoBeautify.cmd'
if (-not (Test-Path $start)) { $start = Join-Path $InstallDir 'Start-CrespoBeautify.cmd' }
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'CrespoBeautify.lnk'
$sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sh.TargetPath = $start; $sh.WorkingDirectory = $app; $sh.Description = 'CrespoBeautify'; $sh.Save()
Ok 'desktop shortcut created'

# ---- 7. Self-test
Step '7/7' 'Self-test'
Push-Location $app
$test = & "$venv\Scripts\python.exe" -c "from crespoqa.core.config import load_settings; from crespoqa.core.pages import find_soffice, find_pdftotext; import crespoqa.api.app; s=load_settings(); print('app ok'); print('soffice', bool(find_soffice(s.soffice))); print('pdftotext', bool(find_pdftotext()))" 2>&1
Pop-Location
$test | ForEach-Object { Write-Host "      $_" }
if (-not ($test -match 'app ok')) { Fail 'The app did not start. Send the log file to the tool owner: ' + $log }
Ok 'self-test passed'

Write-Host ""
Write-Host "Done. Double-click the CrespoBeautify shortcut on your desktop. Log: $log" -ForegroundColor Green
Stop-Transcript | Out-Null
if ($Host.Name -eq 'ConsoleHost') { Read-Host "Press Enter to close" | Out-Null }
