@echo off
REM Sparky launcher for Windows (sparky.cmd calls this; double-clicking either works).
REM   - keeps every file Sparky writes on the stick (profile folders, models)
REM   - uses the stick's portable Python and Ollama, fetching them the first
REM     time the stick meets a Windows PC
REM   - starts the model server unless one is already running, and stops it on
REM     exit only if it started it
setlocal

REM UTF-8 for the console and Python, so the interface draws instead of crashing
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONNOUSERSITE=1"
REM the folder you start in must not be able to stand in for Sparky's own modules
set "PYTHONSAFEPATH=1"

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "SPARKY_ROOT=%ROOT%"
set "RT=%ROOT%\runtime"

REM ---- keep state on the stick -----------------------------------------------
set "HOME=%ROOT%\data\home"
set "USERPROFILE=%ROOT%\data\home"
set "APPDATA=%ROOT%\data\appdata"
set "LOCALAPPDATA=%ROOT%\data\localappdata"
set "OLLAMA_MODELS=%RT%\ollama\models"
if not defined OLLAMA_HOST set "OLLAMA_HOST=127.0.0.1:11500"
REM Without this, Ollama fetches "model recommendations" from ollama.com when it
REM starts and every few hours after. Downloading models is not affected.
if not defined OLLAMA_NO_CLOUD set "OLLAMA_NO_CLOUD=1"
for %%D in ("%HOME%" "%APPDATA%" "%LOCALAPPDATA%" "%ROOT%\data\sessions" "%ROOT%\context" "%OLLAMA_MODELS%") do (
  if not exist "%%~D" mkdir "%%~D" >nul 2>&1
)

REM ---- this PC: ARM64 uses its own runtime when the stick has one, else x64 ---
set "KEY=windows-x86_64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
  if exist "%RT%\python\windows-aarch64\python.exe" set "KEY=windows-aarch64"
)
set "PY=%RT%\python\%KEY%\python.exe"
set "OLLAMA_BIN=%RT%\ollama\pkg\%KEY%\ollama.exe"
set "PYTHONPATH=%ROOT%;%RT%\pylib"

REM ---- runtime: Python first, then the rest ----------------------------------
if not exist "%PY%" (
  echo Sparky: first run on this PC, fetching the Windows runtime ^(needs the internet once^).
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\tools\fetch_python.ps1" -Root "%ROOT%"
  if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" if exist "%RT%\python\windows-aarch64\python.exe" (
    set "KEY=windows-aarch64"
  )
)
set "PY=%RT%\python\%KEY%\python.exe"
set "OLLAMA_BIN=%RT%\ollama\pkg\%KEY%\ollama.exe"
if not exist "%PY%" (
  echo Sparky: could not set up the Windows runtime. Connect to the internet and try again.
  goto :fail
)
if not exist "%OLLAMA_BIN%" "%PY%" -m sparky runtime --os %KEY%
if not exist "%RT%\pylib\rich" "%PY%" -m sparky runtime --os %KEY%

REM ---- model server ------------------------------------------------------------
set "OPID=0"
for /f "usebackq delims=" %%p in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\tools\start_server.ps1"`) do set "OPID=%%p"

REM ---- the app -------------------------------------------------------------------
"%PY%" -m sparky %*
set "RC=%ERRORLEVEL%"

if not "%OPID%"=="0" taskkill /f /t /pid %OPID% >nul 2>&1
if not "%RC%"=="0" goto :fail
endlocal
exit /b 0

:fail
REM keep a double-clicked window open long enough to read what went wrong
echo %cmdcmdline% | find /i "/c" >nul && pause
endlocal
exit /b 1
