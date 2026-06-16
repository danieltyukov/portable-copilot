"""Live end-to-end check (manual, not a unit test): one online Claude turn and
one offline Qwen turn, both with tool use, against the real bundled runtime.
Run via the bundled python with SPARKY_ROOT pointing at an exec-capable copy.
"""
import os
import sys
from pathlib import Path

ROOT = Path(os.environ["SPARKY_ROOT"])
sys.path.insert(0, str(ROOT))

from sparky import config
from sparky.agent import Agent
from sparky.router import Router
from sparky.connectivity import Monitor

cfg = config.load(root=ROOT)
work = Path("/tmp/sparky-e2e-work"); work.mkdir(parents=True, exist_ok=True)
for f in work.glob("*"):
    f.unlink()

def show(tag):
    def on_event(kind, data):
        if kind == "tool_start": print(f"  [{tag} tool] {data['name']} {data.get('input')}")
        elif kind == "tool_result": print(f"  [{tag} result] {str(data['output'])[:80]}")
        elif kind == "backend": print(f"  [{tag} backend] {data['backend']}")
    return on_event

class ForcedMonitor(Monitor):
    def __init__(self, online): self._val = online
    @property
    def online(self): return self._val
    def refresh(self): return self._val
    def start(self): return self

print("=== ONLINE (Claude API) — tool use ===")
r_on = Router(cfg, monitor=ForcedMonitor(True))
a_on = Agent(cfg, r_on, cwd=work)
ans_on = a_on.run_turn(
    "Use your write_file tool to create a file named claude_demo.txt containing exactly: hello from claude. Then confirm in one short sentence.",
    on_event=show("on"),
)
print("ONLINE answer:", ans_on.strip()[:200])
print("file created:", (work / "claude_demo.txt").exists(), "->",
      (work / "claude_demo.txt").read_text().strip() if (work / "claude_demo.txt").exists() else "MISSING")

print("\n=== OFFLINE (local Qwen) — tool use ===")
r_off = Router(cfg, monitor=ForcedMonitor(False))
a_off = Agent(cfg, r_off, cwd=work)
ans_off = a_off.run_turn(
    "Use the list_dir tool to list the files in the current directory, then in one sentence tell me which files you see.",
    on_event=show("off"),
)
print("OFFLINE answer:", ans_off.strip()[:200])
print("\nE2E DONE")
