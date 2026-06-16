@echo off
REM Sparky launcher (Windows). Plug in the stick, double-click this file.
REM Redirects HOME/config/Ollama into the stick, starts Ollama, launches the TUI.
setlocal enabledelayedexpansion

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

if not exist "%PY%" (
  echo Sparky: runtime not set up for Windows yet.
  echo Run the one-time setup in PowerShell:
  echo     powershell -ExecutionPolicy Bypass -File "%ROOT%\tools\setup_usb.ps1" -InPlace
  pause
  exit /b 1
)

REM ---- start Ollama in the background (for offline + fallback) --------------
if exist "%OLLAMA_BIN%" (
  start "" /b "%OLLAMA_BIN%" serve > "%ROOT%\data\ollama.log" 2>&1
)

REM ---- launch --------------------------------------------------------------
"%PY%" -m sparky %*

REM ---- stop Ollama on exit -------------------------------------------------
taskkill /f /im ollama.exe >nul 2>&1
endlocal
