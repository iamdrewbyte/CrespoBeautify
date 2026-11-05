# CrespoBeautify for Windows: setup for your team

## For a teammate (no technical steps)
1. Double-click **CrespoBeautify-Setup.exe**. Say yes to the Windows permission prompts.
2. Wait. It installs Python, LibreOffice, Poppler, Ollama and downloads the Qwen model (about 4.7 GB, once).
3. When it says *Done*, double-click the **CrespoBeautify** shortcut on the desktop. The tool opens in the browser.

No internet is used after setup. Reports never leave the computer. AI review is optional; the formatting works without it.

## Without the .exe
Copy the project folder, then:
`powershell -ExecutionPolicy Bypass -File windows\Setup-CrespoBeautify.ps1` (add `-NoAI` to skip the model).

## For you: building the .exe (once, on a Windows PC)
1. Install Inno Setup 6 (free).
2. In the project folder run `iscc windows\CrespoBeautify.iss`.
3. Give your team `windows\Output\CrespoBeautify-Setup.exe`.

## Notes
- Needs Windows 10/11 with **winget** (App Installer, present on current Windows). Without it the setup tells you what to install by hand.
- Re-running the setup is safe: finished steps are skipped and the settings file is not overwritten.
- Settings: `%LOCALAPPDATA%\CrespoBeautify\app\.env`. Set `CRESPOQA_SAVE_DIR` there to write results back into a folder (the replaced file is kept in `CrespoBeautify_originals`).
- Setup log: `%TEMP%\CrespoBeautify-setup.log`.
- **Untested on Windows**: this was written on Linux. First run on one clean PC and report any step that fails.
