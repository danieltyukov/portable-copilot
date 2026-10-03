@echo off
REM First-time setup on Windows, from a downloaded copy: double-click this file.
REM Fetches a portable Python into this folder (the PC needs no Python of its
REM own), then runs the setup wizard with it. Options: setup.bat --help
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONNOUSERSITE=1"
REM the folder you start in must not be able to stand in for Sparky's own modules
set "PYTHONSAFEPATH=1"

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\tools\fetch_python.ps1" -Root "%ROOT%"
set "ARCH=x86_64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=aarch64"
set "PY=%ROOT%\runtime\python\windows-%ARCH%\python.exe"
if not exist "%PY%" (
  echo Could not fetch Python. Check the internet connection and try again.
  set "RC=1"
  goto :end
)

set "PYTHONPATH=%ROOT%"
"%PY%" -m sparky setup %*
set "RC=%ERRORLEVEL%"

:end
REM a double-clicked window would close before the result could be read
echo %cmdcmdline% | find /i "/c" >nul && pause
endlocal & exit /b %RC%
