"""Manual live check (not a unit test): exercise the local Ollama path + agent
tool loop against whatever model the host has. Run:
  SPARKY_LOCAL_MODEL=<tag> python3 tests/scratch_live_local.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sparky import config
from sparky.agent import Agent
from sparky.router import Router
from sparky.connectivity import Monitor

root = Path("/tmp/sparky-live")
(root / "data").mkdir(parents=True, exist_ok=True)
cfg = config.load(root=root)  # no API key -> forces local backend

class OfflineMonitor(Monitor):
    @property
    def online(self):
        return False

router = Router(cfg, monitor=OfflineMonitor())
work = Path("/tmp/sparky-live/work"); work.mkdir(parents=True, exist_ok=True)
(work / "hello.py").write_text("print('hi from sparky test')\n")
agent = Agent(cfg, router, cwd=work)

def on_event(kind, data):
    if kind == "tool_start":
        print(f"  [tool] {data['name']} {data.get('input')}")
    elif kind == "tool_result":
        print(f"  [result] {str(data['output'])[:120]}")

print("local model:", cfg.local_model)
ans = agent.run_turn(
    "List the files in the current directory using the list_dir tool, then tell me what hello.py prints.",
    on_event=on_event,
)
print("\n=== FINAL ANSWER ===\n", ans)
