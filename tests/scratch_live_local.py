"""Manual live check (not a unit test): exercise the local Ollama path + agent
tool loop against whatever model the host has. Run:
  SPARKY_MAX_MODEL=<tag> SPARKY_TIER=max python3 tests/scratch_live_local.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sparky import config
from sparky.agent import Agent
from sparky.router import Router

root = Path("/tmp/sparky-live")
(root / "data").mkdir(parents=True, exist_ok=True)
cfg = config.load(root=root)

router = Router(cfg)
work = Path("/tmp/sparky-live/work"); work.mkdir(parents=True, exist_ok=True)
(work / "hello.py").write_text("print('hi from sparky test')\n")
agent = Agent(cfg, router, cwd=work)

def on_event(kind, data):
    if kind == "tool_start":
        print(f"  [tool] {data['name']} {data.get('input')}")
    elif kind == "tool_result":
        print(f"  [result] {str(data['output'])[:120]}")

print("tier:", cfg.tier, "model:", cfg.model)
ans = agent.run_turn(
    "List the files in the current directory using the list_dir tool, then tell me what hello.py prints.",
    on_event=on_event,
)
print("\n=== FINAL ANSWER ===\n", ans)
