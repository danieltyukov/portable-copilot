"""`ask` (one answer, for scripts and pipes) and `serve` (just the model
server, for other apps)."""

from __future__ import annotations

import sys
import time

from . import engine
from .ollama import OllamaClient
from .providers.base import Cancelled, ProviderError


def ask(cfg, prompt: str) -> int:
    """Print one answer. Text piped in is appended to the question, so
    `cat notes.txt | sparky.cmd ask "summarise this"` works."""
    piped = ""
    if not sys.stdin.isatty():
        piped = sys.stdin.read()
    question = "\n\n".join(p for p in (prompt.strip(), piped.strip()) if p)
    if not question:
        print('Usage: sparky.cmd ask "your question"   (or pipe text in)', file=sys.stderr)
        return 2
    agent = engine.build(cfg)
    if not agent.router.model:
        print(engine.no_models_message(cfg), file=sys.stderr)
        return 1

    def on_event(kind, data):
        if kind == "assistant_delta":
            sys.stdout.write(data["text"])
            sys.stdout.flush()
        elif kind == "tool_start":
            print(f"\n[{data['name']}]", file=sys.stderr)
        elif kind == "notice":
            print(f"\n({data['text']})", file=sys.stderr)
        elif kind == "confirm":
            # no one to ask in a pipe: risky actions need --yolo
            print(f"\n[not allowed without --yolo: {data['command']}]", file=sys.stderr)
            data["holder"]["approved"] = False

    try:
        agent.run_turn(question, on_event=on_event)
    except Cancelled:
        return 130
    except ProviderError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    print()
    return 0


def serve(cfg) -> int:
    """Keep the stick's model server running and say how to reach it."""
    client = OllamaClient(cfg.ollama_host)
    if not client.reachable():
        print("The model server is not running. Start this through the launcher:\n"
              "  sparky.cmd serve", file=sys.stderr)
        return 1
    names = [m.get("name") for m in client.models()]
    host = cfg.ollama_host.rstrip("/")
    print("Sparky model server is running on this computer only.\n")
    print(f"  OpenAI-compatible:  {host}/v1      (any API key works)")
    print(f"  Ollama API:         {host}/api")
    print(f"  Models:             {', '.join(names) or 'none yet'}\n")
    print("Example:")
    print(f'  curl {host}/v1/chat/completions -H "Content-Type: application/json" \\')
    first = names[0] if names else "MODEL"
    print(f'    -d \'{{"model": "{first}", "messages": [{{"role": "user", "content": "Hello"}}]}}\'\n')
    print("Press Ctrl-C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0
