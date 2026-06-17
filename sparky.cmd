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
:; case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) exec cmd //c "$(cygpath -w "$DIR/START.bat" 2>/dev/null || echo "$DIR\\START.bat")" "$@" ;; esac
:; exec bash "$DIR/start.sh" "$@"

@echo off
call "%~dp0START.bat" %*
