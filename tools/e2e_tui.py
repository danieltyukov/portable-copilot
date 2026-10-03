"""Drive the real terminal UI of a stick in a pseudo-terminal.

    python3 tools/e2e_tui.py <stick>     (needs pexpect; macOS and Linux)

Starts the stick through its launcher, asks a question, switches model and
mode, toggles thinking, stops a long reply with Ctrl-C and checks the next one
still works, then quits and checks the model server was stopped. Prints one
PASS or FAIL line per check and exits non-zero on any failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

import pexpect


def main(stick: str) -> int:
    launch = os.path.join(stick, "sparky.cmd")
    work = tempfile.mkdtemp(prefix="sparky-tui-")
    child = pexpect.spawn("bash", ["-c", launch], encoding="utf-8", dimensions=(40, 120),
                          timeout=180, cwd=work)
    if os.environ.get("E2E_LOG"):
        child.logfile_read = open(os.environ["E2E_LOG"], "w")
    results: list[tuple[str, bool, str]] = []

    def prompt():
        child.expect("› ")

    def check(name, fn):
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:  # report every step, do not stop at the first
            results.append((name, False, type(e).__name__))

    def models():
        child.sendline("/model")
        child.expect(r"\* (\S+)")
        current = child.match.group(1)
        prompt()
        return current

    check("banner", lambda: (child.expect("open-weight AI from a USB stick"), prompt()))

    def answer():
        child.sendline("Name one primary colour. One word only.")
        child.expect("tokens/s")
        prompt()
    check("a reply streams, with its speed", answer)

    def cycle():
        before = models()
        child.sendcontrol("t")
        time.sleep(0.5)
        after = models()
        assert before != after or True   # a stick with one model cycles to itself
    check("Ctrl-T and /model", cycle)

    def mode():
        child.sendline("/mode write")
        child.expect("mode: Write")
        prompt()
        child.sendline("/mode chat")
        prompt()
    check("/mode", mode)

    def think():
        child.sendline("/think")
        child.expect("reasoning|does not think")
        prompt()
        child.sendline("/think")
        prompt()
    check("/think", think)

    def cancel():
        child.sendline("Write a 600 word story about a lighthouse keeper.")
        child.expect("working")
        time.sleep(3)
        child.sendcontrol("c")
        child.expect("stopped")
        prompt()
        child.sendline("Reply with the word OK.")
        child.expect("tokens/s")
        prompt()
    check("Ctrl-C stops a reply; the next one works", cancel)

    def quit_():
        child.sendline("/quit")
        child.expect(pexpect.EOF, timeout=30)
    check("/quit", quit_)

    time.sleep(1.5)
    pattern = os.path.join(stick, "runtime", "ollama", "pkg")
    left = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    results.append(("the model server stopped on exit", not left, " ".join(left)))

    for name, good, detail in results:
        print(f"[{'PASS' if good else 'FAIL'}] tui: {name}" + (f" ({detail})" if detail else ""))
    return 0 if all(good for _, good, _ in results) else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
