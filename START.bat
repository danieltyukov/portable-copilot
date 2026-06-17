@echo off
REM Sparky launcher (Windows). Plug in the stick, run `sparky.cmd` (or double-click).
REM Plug-and-play: if the Windows runtime isn't on the stick yet, it auto-fetches it
REM ADDITIVELY (no wipe, no re-setup) and launches. Works in PowerShell and cmd.
setlocal enabledelayedexpansion

REM UTF-8 console + Python I/O so ✓ ● ⚙ etc. render instead of crashing.
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "SPARKY_ROOT=%ROOT%"
set "RT=%ROOT%\runtime"

REM ---- zero-footprint env: keep state on the stick --------------------------
set "HOME=%ROOT%\data\home"
set "USERPROFILE=%ROOT%\data\home"
set "APPDATA=%ROOT%\data\appdata"
set "LOCALAPPDATA=%ROOT%\data\localappdata"
set "OLLAMA_HOME=%RT%\ollama"
set "OLLAMA_MODELS=%RT%\ollama\models"
set "OLLAMA_HOST=127.0.0.1:11500"
for %%D in ("%HOME%" "%APPDATA%" "%LOCALAPPDATA%" "%ROOT%\data\sessions" "%ROOT%\context" "%OLLAMA_MODELS%") do (
  if not exist "%%~D" mkdir "%%~D" >nul 2>&1
)

set "PY=%RT%\python\windows-x86_64\python.exe"
set "PYTHONPATH=%RT%\pylib"
set "OLLAMA_BIN=%RT%\ollama\pkg\windows-x86_64\ollama.exe"

REM ---- first run on this PC: auto-fetch the Windows runtime (additive) ------
if not exist "%PY%" (
  echo Sparky: setting up the Windows runtime ^(first run on this PC^)...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\tools\fetch_runtime.ps1" -Root "%ROOT%"
)
if not exist "%PY%" (
  echo Sparky: could not set up the Windows runtime ^(need internet on the first Windows run^).
  pause
  exit /b 1
)

REM ---- start Ollama in the background (offline + mid-session fallback) -------
if exist "%OLLAMA_BIN%" (
  start "" /b "%OLLAMA_BIN%" serve > "%ROOT%\data\ollama.log" 2>&1
)

REM ---- launch the TUI ------------------------------------------------------
"%PY%" -m sparky %*

REM ---- stop Ollama on exit -------------------------------------------------
taskkill /f /im ollama.exe >nul 2>&1
endlocal
