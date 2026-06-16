:; # =====================================================================
:; # Sparky — ONE universal launcher for Linux, macOS, and Windows.
:; #   macOS / Linux :   ./sparky.cmd
:; #   Windows       :   sparky.cmd   (or double-click)
:; # This file is a polyglot: a POSIX shell script AND a Windows batch file.
:; # On Unix the shell runs the line below and exec's start.sh, never reaching
:; # the @echo-off section. On Windows, cmd ignores every ":;" line (they are
:; # labels) and runs the batch section.
:; # =====================================================================
:; DIR="$(cd "$(dirname "$0")" && pwd)"
:; exec "$DIR/start.sh" "$@"

@echo off
call "%~dp0START.bat" %*
