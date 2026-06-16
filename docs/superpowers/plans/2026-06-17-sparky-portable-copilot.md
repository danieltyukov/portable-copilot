# Sparky Portable Copilot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A USB-portable, zero-install Claude-Code-style copilot that uses the Claude API online and a bundled local Qwen offline, switching automatically mid-session.

**Architecture:** Pure-Python app (`sparky/`) with a provider router that normalizes Claude Messages API and Ollama behind one interface; a connectivity monitor flips the active backend. Launchers set zero-footprint env, pick a bundled portable Python + Ollama, and start the TUI. Setup pre-bundles runtimes + model onto the stick.

**Tech Stack:** Python 3.11+ (bundled python-build-standalone), stdlib HTTP (`urllib`/`http.client`), `rich` + `prompt_toolkit` (pure-Python), Ollama (`qwen2.5-coder:3b`), bash/batch/powershell launchers.

## Global Constraints
- **No binary-wheel dependencies.** HTTP via stdlib; images via stdlib `base64`. Only pure-Python deps: `rich`, `prompt_toolkit`, `wcwidth`, `pygments`.
- **Zero host footprint:** launcher exports `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `OLLAMA_MODELS`, `OLLAMA_HOME` into stick subfolders.
- **Secrets never committed:** `runtime/` and `data/` are gitignored. Key only in `data/sparky.env` (chmod 600).
- **Default models:** online `claude-sonnet-4-6`; offline `qwen2.5-coder:3b`.
- **Theme:** brand `#FFC61A`; bg `#0d1117`, panel `#161b22`, border `#30363d`, text `#e6edf3`, muted `#7d8590`; accents teal `#34d399`, cyan `#38bdf8`, red `#f87171`. Monospace.
- **Platforms:** Linux fully pre-bundled+tested now; macOS/Windows launchers + first-run bootstrap.

## File structure
```
sparky/__init__.py        version
sparky/__main__.py        entrypoint / arg parsing / self-test
sparky/config.py          load data/sparky.env + paths
sparky/theme.py           palette + mascot + rich console
sparky/providers/base.py  normalized types (Message, ToolSpec, Reply)
sparky/providers/claude.py   Claude Messages API (stdlib http, streaming, tools, images)
sparky/providers/local.py    Ollama /api/chat (stdlib http, tools)
sparky/connectivity.py    background online/offline monitor
sparky/router.py          chooses provider, per-call fallback
sparky/tools.py           filesystem + shell tools (schemas + dispatch)
sparky/context.py         load context/ drop folder
sparky/images.py          path detection + base64 encode
sparky/agent.py           multi-step tool-use loop
sparky/ui.py              TUI: header, input box, render loop
tests/...                 pytest for pure logic
start.sh START.bat start.command   launchers
tools/setup_usb.sh tools/setup_usb.ps1   installers
README.md  docs/          theme assets
```

---

### Task 1: Scaffolding, config, theme
**Files:** Create `sparky/__init__.py`, `sparky/config.py`, `sparky/theme.py`, `tests/test_config.py`.
**Produces:** `config.load() -> Config` with `.anthropic_api_key`, `.model`, `.local_model`, `.yolo`, `.root`, `.data_dir`, `.context_dir`; `theme.console`, `theme.MASCOT`, `theme.C` palette dict.

- [ ] Write `config.py`: resolve stick root (env `SPARKY_ROOT` or parent of package), parse `data/sparky.env` (simple `KEY=VALUE`), env override, defaults from Global Constraints.
- [ ] Write `theme.py`: palette dict, small mascot ASCII, a `rich.Console`.
- [ ] Test: writing a sparky.env and loading it yields the key + model; missing file → defaults, key `None`.
- [ ] Run `pytest tests/test_config.py -v`; commit.

### Task 2: Provider base + Claude provider
**Files:** Create `sparky/providers/base.py`, `sparky/providers/claude.py`, `tests/test_claude_payload.py`.
**Consumes:** Config.
**Produces:** `base.Reply(text, tool_calls, raw)`, `base.ToolCall(id, name, input)`; `ClaudeProvider(cfg).chat(messages, tools, system) -> Reply` and `.reachable() -> bool`. Builds Anthropic Messages API JSON; supports text + image blocks + tool definitions; uses stdlib `urllib.request`.

- [ ] Define normalized dataclasses in `base.py`.
- [ ] `claude.py`: `_build_payload` converting normalized messages (incl. image blocks) → Anthropic schema; `chat()` POSTs to `https://api.anthropic.com/v1/messages` with `x-api-key`, `anthropic-version: 2023-06-01`; parse `content` into text + `tool_use` → ToolCalls.
- [ ] Test `_build_payload` only (no network): text msg, image msg, tool defs produce correct dict shape.
- [ ] Run pytest; commit.

### Task 3: Local (Ollama) provider
**Files:** Create `sparky/providers/local.py`, `tests/test_local_payload.py`.
**Produces:** `LocalProvider(cfg).chat(messages, tools, system) -> Reply`, `.reachable()`, `.ensure_model()`. Talks to `http://127.0.0.1:11434/api/chat`; maps normalized messages → Ollama `messages`/`tools`; parses `message.tool_calls` → ToolCalls; drops images with a note.

- [ ] Implement payload builder + `chat()` + `reachable()` (GET `/api/tags`).
- [ ] Test payload builder shape (no network).
- [ ] Run pytest; commit.

### Task 4: Connectivity monitor + router
**Files:** Create `sparky/connectivity.py`, `sparky/router.py`, `tests/test_router.py`.
**Consumes:** providers, Config.
**Produces:** `Monitor(cfg).online` (bool, background-refreshed) ; `Router(cfg).chat(messages, tools, system) -> (Reply, backend_str)`. Router picks Claude when `online and key`; on any exception or offline, falls back to Local and marks `(fallback)`.

- [ ] `connectivity.py`: thread pinging `api.anthropic.com:443` every N s; `online` property; manual `refresh()`.
- [ ] `router.py`: selection + try/except fallback; expose `.backend` label and `.last_fallback` flag.
- [ ] Test with fake providers: online→claude; raise in claude→local; offline→local. (Inject providers.)
- [ ] Run pytest; commit.

### Task 5: Tools (filesystem + shell)
**Files:** Create `sparky/tools.py`, `tests/test_tools.py`.
**Produces:** `TOOL_SPECS` (list of ToolSpec dicts: read_file, write_file, edit_file, list_dir, search, run_shell), and `run_tool(name, input, *, cwd, confirm) -> str`.

- [ ] Implement tools with safe path handling, sized reads, `edit_file` (unique string replace), `search` (recursive substring/regex), `run_shell` (subprocess, capture, timeout, confirm hook).
- [ ] Tests in a tmp dir: write→read roundtrip; edit replaces; list_dir lists; search finds; run_shell echo.
- [ ] Run pytest; commit.

### Task 6: Context loader + images
**Files:** Create `sparky/context.py`, `sparky/images.py`, `tests/test_context.py`, `tests/test_images.py`.
**Produces:** `context.load_context(dir) -> str` (tree + budgeted text file contents); `images.find_image_paths(text) -> list[str]`, `images.encode_image(path) -> dict` (normalized image block).

- [ ] Implement context loader (skip large/binary, cap total bytes) and image helpers (detect by extension + existence; base64 + media type).
- [ ] Tests: context includes a dropped text file's content; encode_image returns base64 + media_type; find detects a path.
- [ ] Run pytest; commit.

### Task 7: Agent loop
**Files:** Create `sparky/agent.py`, `tests/test_agent.py`.
**Consumes:** Router, tools, context.
**Produces:** `Agent(cfg, router).run_turn(user_text, images, on_event) -> str`. Maintains message history + system prompt (incl. context); loops: call router → if tool_calls, run tools, append results, repeat; else return text. Emits events for UI (assistant text, tool start/result, backend).

- [ ] Implement loop with max-iteration guard; persist/append history; `on_event` callbacks.
- [ ] Test with a fake router scripted to return one tool_call then text; assert tool executed and final text returned.
- [ ] Run pytest; commit.

### Task 8: TUI
**Files:** Create `sparky/ui.py`, `sparky/__main__.py`.
**Consumes:** Agent, theme, config, connectivity.
**Produces:** `ui.run(cfg)` REPL: header w/ mascot + `● online/OFFLINE` + model; prompt_toolkit input (multiline, history, `/img`, `/model`, `/help`, `/quit`); renders markdown + tool cards via rich; `__main__` handles `--self-test`, first-run key setup.

- [ ] Implement REPL + slash commands + event rendering + first-run key capture (writes data/sparky.env chmod 600).
- [ ] `--self-test`: report python, deps, ollama, model, key presence, connectivity → exit 0/1.
- [ ] Manual smoke (host python): `python -m sparky --self-test`.
- [ ] Commit.

### Task 9: Launchers
**Files:** Create `start.sh`, `start.command`, `START.bat`.
**Produces:** one-step launch; export zero-footprint env; detect OS/arch; locate/bootstrap `runtime/python` + `runtime/ollama`; start `ollama serve`; `exec` the TUI; cleanup on exit.

- [ ] `start.sh` (Linux/macOS): resolve `SPARKY_ROOT`, export env, pick `runtime/python/<os>-<arch>/bin/python3`, set `PYTHONPATH=runtime/pylib`, start bundled ollama, run `python -m sparky "$@"`, trap to kill ollama. Bootstrap-download if runtime missing & online.
- [ ] `start.command`: thin wrapper that `cd`s to its dir and runs `start.sh` (Finder double-click).
- [ ] `START.bat`: Windows equivalent.
- [ ] Commit.

### Task 10: setup_usb.sh installer
**Files:** Create `tools/setup_usb.sh`.
**Produces:** wipe+label target → copy app → download portable Python (linux/mac/win) + Ollama binaries → `pip install --target runtime/pylib` deps → pull `qwen2.5-coder:3b` into `runtime/ollama/models` → seed `context/` + `data/`.

- [ ] Implement with explicit confirm before wipe; idempotent (skip existing downloads); progress echoes.
- [ ] Commit.

### Task 11: Windows installer
**Files:** Create `tools/setup_usb.ps1`.
- [ ] PowerShell equivalent of Task 10. Commit.

### Task 12: README + theme assets
**Files:** Create `README.md`; copy mascot SVG/PNG to `docs/`.
- [ ] Sparky-branded README: what/why, quick start, offline behavior table, layout, security note. Commit.

### Task 13: Deploy to stick + create key + end-to-end test
- [ ] Create Claude API key via Chrome at platform.claude.com; write to `data/sparky.env`.
- [ ] Back up + wipe `/media/danieltyukov/Sparky`; run `tools/setup_usb.sh` against it.
- [ ] Run `start.sh` from the stick: self-test, online answer, tool edit, image prompt, offline fallback, context use; verify host HOME/config untouched.

### Task 14: GitHub
- [ ] Create private repo `portable-copilot`; push (runtime/ + data/ excluded). Verify key/weights absent.

## Self-Review
- **Spec coverage:** router/switch (T2-4), multimodal (T2,6,8), tools/agent (T5,7), context folder (T6), zero-footprint+portable (T9), pre-bundle model (T10-11), TUI+self-test (T8), installer/wipe (T10,13), key via Chrome (T13), repo (T14), theme (T1,12). All spec sections mapped.
- **Placeholder scan:** none; each task names exact files + concrete behavior.
- **Type consistency:** `Reply`/`ToolCall`/`ToolSpec`/`Router.chat() -> (Reply, str)`/`Agent.run_turn(...) -> str` used consistently across tasks.
