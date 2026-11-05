@echo off
rem Starts CrespoBeautify and opens it in the browser. Close this window to stop it.
setlocal
set "ROOT=%~dp0.."
if not exist "%ROOT%\crespoqa" set "ROOT=%~dp0"
cd /d "%ROOT%"
set "VENV=%LOCALAPPDATA%\CrespoBeautify\venv\Scripts\python.exe"
set OLLAMA_NO_CLOUD=1

rem already running? just open the page
powershell -NoProfile -Command "try{Invoke-WebRequest http://127.0.0.1:8000/api/me -UseBasicParsing -TimeoutSec 2|Out-Null;exit 0}catch{exit 1}"
if %errorlevel%==0 ( start "" http://localhost:8000 & exit /b 0 )

rem start the local AI server if it is installed and not running
where ollama >nul 2>nul
if %errorlevel%==0 (
  powershell -NoProfile -Command "try{Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 1|Out-Null}catch{Start-Process ollama -ArgumentList 'serve' -WindowStyle Hidden}"
)

start "" powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 40;$i++){try{Invoke-WebRequest http://127.0.0.1:8000/api/me -UseBasicParsing -TimeoutSec 1|Out-Null;Start-Process http://localhost:8000;break}catch{Start-Sleep 1}}"
echo CrespoBeautify is running at http://localhost:8000  (close this window to stop)
"%VENV%" -m crespoqa.api.app
pause
