# Sparky — Portable Copilot (Design Spec)

**Date:** 2026-06-17
**Status:** Approved (proceed to implementation)

## 1. Summary

Sparky-Portable is a USB-portable AI coding copilot. Plug the **"Sparky"** stick into
*any* Linux / macOS / Windows machine, run one launcher, and get a Claude-Code-style
terminal copilot — with **zero installation, zero authentication, and zero footprint**
on the host machine.

- **Online** → the **Claude API** (`api.anthropic.com`, Messages API) using a key that
  lives on the stick. Default model Sonnet; Opus selectable in-session.
- **Offline, or on any API failure** → a **local `qwen2.5-coder:3b`** served by a
  bundled **Ollama**, switching **automatically mid-session**.
- A live `● online` / `● OFFLINE` marker in the header shows the active backend, and
  any mid-session downgrade is tagged `(fallback)`.

Inspired by `OpenClaude-Portable` (portable runtime, zero-footprint `data/`, local
fallback proxy) and branded as **Sparky** (the pixel-budgie + `#FFC61A` theme from the
user's `interview-copilot`).

## 2. Goals & Non-Goals

**Goals**
- One-step launch on any OS after plug-in; no installs/auth on the host.
- Real agentic coding loop: read/edit/write files, run shell, search — like Claude Code.
- Text **and image** prompts (multimodal) when online.
- Automatic, transparent online↔offline model switching mid-session.
- True offline operation out of the box (model weights pre-bundled on the stick).
- Host machine stays clean (HOME/XDG/config redirected into the stick's `data/`).
- A per-drive `context/` folder the user drops files into; auto-loaded every run.

**Non-Goals (v1)**
- Web dashboard (TUI only, per user choice).
- Offline image understanding by default (text-only Qwen; graceful message instead).
  An optional local vision model is a documented future add-on.
- Bundling the official Claude Code CLI. We talk to the Claude API directly.

## 3. Architecture

```
launcher (start.sh / START.bat / start.command)
  │  detect OS+arch, redirect HOME/XDG/OLLAMA_MODELS → stick, start Ollama
  ▼
python -m sparky                      (bundled portable Python)
  ├── ui/          rich + prompt_toolkit TUI (Sparky theme, header, input box)
  ├── agent.py     tool-use loop (multi-step), session history
  ├── router.py  ★ provider router + connectivity monitor (the switch)
  │     ├── providers/claude.py   Claude Messages API over stdlib http (online)
  │     └── providers/local.py    Ollama /api/chat over stdlib http (offline)
  ├── tools.py     read_file, write_file, edit_file, list_dir, search, run_shell
  ├── context.py   loads the per-drive context/ folder into system context
  ├── config.py    reads data/sparky.env
  └── theme.py     mascot ASCII + palette
```

### 3.1 Provider Router (the heart)
- `Router.chat(messages, tools, *, want_images)` returns a normalized response and the
  backend used.
- A background **connectivity monitor** flips an `online` flag based on: (a) a cheap
  reachability check to `api.anthropic.com`, and (b) a valid API key being present.
- Selection: `online and key` → `ClaudeProvider`. Otherwise, or on a network/HTTP/5xx
  error during a call → fall back to `LocalProvider` (Ollama). The fallback is per-call
  and retried, so a turn that starts online but loses Wi-Fi completes on Qwen.
- The router normalizes both providers to one message/tool schema so `agent.py` is
  backend-agnostic.

### 3.2 Tool-use loop (`agent.py`)
- Online: native Claude **tool use** (function calling) via the Messages API `tools`
  field; loop until no more `tool_use` blocks.
- Offline: Qwen tool calling via Ollama's `tools` support; same loop. If a local model
  emits no structured call, fall back to a lightweight text protocol.
- Tools (working dir = where the launcher was invoked, or a chosen project dir):
  `read_file`, `write_file`, `edit_file` (string replace), `list_dir`, `search` (grep),
  `run_shell` (confirm before run unless `--yolo`/limitless flag set).

### 3.3 Multimodal
- Images are read as bytes and base64-encoded with **stdlib** (no Pillow).
- Attach via `/img <path> [prompt]`, bare image paths in a prompt, or by dropping image
  files into `context/`.
- Online → sent as Claude image content blocks. Offline → user is told images need
  connectivity (text portion still answered by Qwen).

## 4. On-stick layout

```
Sparky/                         (USB root, volume label "Sparky")
├── start.sh                    Linux/macOS launcher
├── start.command               macOS Finder double-click launcher
├── START.bat                   Windows launcher
├── README.md
├── sparky/                     the Python application package
├── context/                    ← user drop folder (auto-loaded). Seeded with README.
├── runtime/        (gitignored, built at setup)
│   ├── python/<os>-<arch>/     portable Python (python-build-standalone)
│   ├── pylib/                  pure-Python deps (rich, prompt_toolkit, wcwidth) — shared across OSes
│   └── ollama/
│       ├── bin/<os>-<arch>/    Ollama binary per OS
│       └── models/             OS-independent GGUF blobs (qwen2.5-coder:3b)
├── data/           (gitignored, runtime state)
│   ├── sparky.env              API key + settings (chmod 600)
│   ├── sessions/               saved conversations (JSON)
│   └── home/ config/ cache/    redirected HOME/XDG_* (zero footprint)
├── tools/
│   ├── setup_usb.sh            installer (Linux/macOS): wipe+label+install+fetch
│   └── setup_usb.ps1           installer (Windows)
└── docs/                       mascot + theme assets
```

## 5. Portability strategy

- **No binary-wheel deps.** All HTTP (Claude + Ollama) uses stdlib `urllib`/`http.client`
  + `json`; images use stdlib `base64`. TUI deps (`rich`, `prompt_toolkit`, `wcwidth`)
  are pure Python → a single `runtime/pylib/` works on all three OSes.
- **Per-OS pieces only:** the Python interpreter (python-build-standalone, relocatable)
  and the Ollama binary. Model blobs are shared.
- **Linux is fully pre-bundled and tested** at setup (interpreter + deps + Ollama + model).
- **macOS/Windows self-bootstrap on first plug-in** (download that OS's portable Python +
  Ollama binary into `runtime/`, reusing the shared `pylib/` and `models/`); cached on the
  stick thereafter. Matches OpenClaude-Portable's first-run download model. Needs internet
  once per new OS; offline works immediately afterward (and immediately on Linux).
- **Zero footprint:** launcher exports `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`,
  `XDG_CACHE_HOME`, `OLLAMA_MODELS`, `OLLAMA_HOME` into stick subfolders before launching.

## 6. Launch flow (`start.sh`)
1. Resolve stick root = script dir.
2. Export zero-footprint env (HOME/XDG/OLLAMA → stick).
3. Detect OS+arch; locate `runtime/python/<os>-<arch>` and `runtime/ollama/bin/<os>-<arch>`
   (bootstrap-download if missing and online).
4. If `data/sparky.env` missing → first-run config (prompt/confirm Claude API key).
5. Start bundled `ollama serve` in background (enables offline + mid-session fallback).
6. `exec python -m sparky` (the TUI).
7. On exit: stop the Ollama subprocess.

## 7. Setup / installer (`tools/setup_usb.sh`)
1. Identify target drive; **confirm** with the user (destructive).
2. Wipe contents and set the volume label to **"Sparky"** (or operate on the
   already-mounted `/media/<user>/Sparky`).
3. Copy the app (`sparky/`, launchers, `tools/`, `docs/`, README) onto the stick.
4. Download portable Python (linux/mac/win) + Ollama binaries; `pip install --target
   runtime/pylib` the pure-Python deps; pull `qwen2.5-coder:3b` into `runtime/ollama/models`.
5. Seed `context/README.txt` and the `data/` skeleton.
6. Print next-step instructions.

## 8. Config & secrets
- `data/sparky.env` (chmod 600): `ANTHROPIC_API_KEY`, `SPARKY_MODEL` (default
  `claude-sonnet`), `SPARKY_LOCAL_MODEL` (`qwen2.5-coder:3b`), `SPARKY_YOLO` (0/1).
- Key created via the Claude dashboard and written only to the stick; **never committed**.
- `.gitignore` excludes `runtime/` and `data/` so weights and the key never reach GitHub.

## 9. Theme
- Reuse the Sparky pixel-budgie mascot and palette: brand `#FFC61A`, bg `#0d1117`,
  panel `#161b22`, border `#30363d`, text `#e6edf3`, muted `#7d8590`; accents teal
  `#34d399`, cyan `#38bdf8`, red `#f87171`. Monospace UI. Mascot ASCII in the TUI header
  and the SVG in the README.

## 10. Testing / acceptance
- Build + fully exercise the **Linux** path on the real stick at `/media/danieltyukov/Sparky`.
- Verify: launch with no args; online Claude answer; a tool-use edit; an image prompt;
  kill connectivity → next turn answers via Qwen with `(fallback)`; restore → back online;
  `context/` file is reflected in answers; host HOME/config untouched after a session.
- `sparky --self-test` reports interpreter, deps, Ollama, model, key, and connectivity.

## 11. Deliverables
- Working app on the Sparky stick (Linux fully bundled; Mac/Win launchers + bootstrap).
- A live Claude API key created via the dashboard, stored on the stick.
- Private GitHub repo `portable-copilot` (runtime/ + data/ gitignored).
