<p align="center">
  <img src="docs/sparky-logo.svg" width="760" alt="Sparky — portable copilot">
</p>

<p align="center">
  <b>Sparky</b> is a <b>fully-local</b>, Claude-Code-style AI coding copilot that runs from a
  USB stick on <b>any computer</b> — Linux, macOS, or Windows — with <b>no install, no login,
  and no internet</b>. Plug it in, run one command, and you have a real agentic copilot that
  reads and edits files, runs commands, and searches code — entirely offline.
</p>

<p align="center">
  🔒 <b>100% local Qwen.</b>  ⚡ <b>Switch tiers for speed vs. accuracy</b> — the local
  analogue of Haiku ↔ Opus — with <b>Ctrl-T</b>, mid-session. Nothing ever leaves the machine.
</p>

---

## One command, every device

Sparky ships a single self-detecting launcher — the same file runs on all three
operating systems:

```bash
# macOS / Linux
./sparky.cmd

# Windows (or just double-click it)
sparky.cmd
```

`sparky.cmd` is a polyglot: a POSIX shell script *and* a Windows batch file at once.
It detects the OS, picks the right bundled runtime, starts the local model in the
background, and launches the copilot. Nothing is installed on the host machine.

## What it does

- 🧠 **Local Qwen, two tiers** — switch between **`fast`** (snappy, runs on any laptop)
  and **`max`** (a 30B MoE — the best CPU agentic coder that fits a stick) with **Ctrl-T**
  or `/model`. Aliases `haiku`/`sonnet`/`opus` work too. The header shows the active tier.
- 🛟 **Graceful tier fallback** — if a host doesn't have the RAM for `max`, the turn
  auto-downgrades to `fast` instead of erroring, tagged `⚠ downgraded`.
- 🛠 **Real coding agent** — tools for read / write / edit files, list dirs, search, and
  run shell commands (with an approval prompt unless you `/yolo`).
- ✨ **Live, Claude-Code-style TUI** — responses **stream** as they're generated (you see it
  think and watch each tool run as a card), markdown-formatted output, a clear `›` input with
  a bottom toolbar showing the active tier.
- 🖼 **Text *and* image prompts** — attach a screenshot with `/img shot.png what's this?` or
  paste from the clipboard with `/paste` (images pass to the local model; to *understand*
  them, use a vision tag like `qwen3-vl` — see swapping below).
- 📂 **Per-drive context folder** — drop notes, specs, or code into `context/` on the
  stick and Sparky loads them into every session automatically.
- 🔌 **Swap models per stick size** — one command re-tiers the stick for an 8 GB or a
  64 GB drive (see below).
- 🔒 **Zero footprint, zero network** — `HOME`, config, caches, and the models all live on
  the stick; your host machine stays untouched and nothing is ever sent anywhere.

### Tiers

| Tier | Model (default) | Download | RAM to run | Feel |
|---|---|---|---|---|
| `fast` | `qwen3.5:4b` | ~3.4 GB | ~5 GB | quick; runs on any laptop |
| **`max`** (default) | `qwen3-coder:30b` | ~19 GB | ~20 GB | a3b MoE — best CPU agentic coder (~10 tok/s) |

> Why not GLM-5.2 / DeepSeek V4 / Kimi K2.6? Those top the open-weights leaderboard but are
> 240 GB–900 GB and need server-class RAM — impossible on a USB stick + a laptop CPU. The
> practical ceiling for "any laptop + a ~30 GB stick" is ~30B params, and the `max` tier is
> the strongest model that fits there.

## Set up a stick

Plug in a USB drive and name its volume **`Sparky`**. **Format it as exFAT**: exFAT is
cross-platform, supports files >4GB, and — unlike FAT32 — mounts executable on Linux, which
the local model needs. If your stick is FAT32, run `sudo tools/format_exfat.sh` once to
convert it (it backs up, reformats, and restores). Then:

```bash
# macOS / Linux — wipes the stick, installs Sparky, fetches the runtime + models
tools/setup_usb.sh                       # default: large preset (~32 GB stick)
tools/setup_usb.sh --preset medium       # size the models to a 16 GB stick
tools/setup_usb.sh --cross               # also bundle macOS+Windows runtimes
```
```powershell
# Windows
powershell -ExecutionPolicy Bypass -File tools\setup_usb.ps1 -Preset large
```

Setup downloads a relocatable Python, the pure-Python deps, the Ollama binary, and pulls
the Qwen weights **onto the stick** — so a brand-new *offline* machine works on first
plug-in (after the one-time per-OS setup while you have internet). The first time you launch
on a new OS, Sparky auto-fetches that OS's runtime if it's missing (needs internet once);
afterwards it's cached on the stick and works fully offline.

## Swapping models (bigger / smaller sticks)

Re-tier any stick in one command — pull a different model set and rewrite the stick's
`data/sparky.env` so the app picks it up next launch:

```bash
tools/set_models.sh --preset small       # ~8 GB  : fast qwen3.5:0.8b · max qwen3.5:4b
tools/set_models.sh --preset medium      # ~16 GB : fast qwen3.5:4b   · max qwen3.5:9b
tools/set_models.sh --preset large       # ~32 GB : fast qwen3.5:4b   · max qwen3-coder:30b
tools/set_models.sh --preset xl          # ~64 GB+: fast qwen3.5:9b   · max qwen3.6:35b-a3b

tools/set_models.sh --max qwen3.6:27b    # pick any Ollama tag for either tier
tools/set_models.sh --preset small --rm-old   # also delete the old weights to reclaim space
tools/set_models.sh --list               # show what's on the stick
```
```powershell
powershell -ExecutionPolicy Bypass -File tools\set_models.ps1 -Preset xl
```

Or just hand-edit `data/sparky.env` on the stick:

```
SPARKY_FAST_MODEL=qwen3.5:4b
SPARKY_MAX_MODEL=qwen3-coder:30b
SPARKY_TIER=max          # which tier to open on
```

## In-session commands

| Command | Action |
|---|---|
| `/help` | list commands |
| `/model [fast\|max\|<tag>]` | switch tier (aliases `haiku`/`sonnet`/`opus`) — or **Ctrl-T** |
| `/img <path> [message]` | attach an image file to the next message |
| `/paste` · **Ctrl-V** | paste an image from the clipboard |
| `/resume` · `/sessions` | resume your last conversation · list saved ones |
| `/context` | show what's loaded from `context/` |
| `/yolo` | toggle auto-approval of shell commands |
| `/clear` · `/quit` | clear history · exit |

Conversations auto-save to `data/sessions/` after every turn; `./sparky.cmd --resume`
re-opens the most recent one on launch.

Run `python -m sparky --self-test` (or `sparky.cmd --self-test`) to check the runtime,
Ollama, and that both tier models are pulled.

## On-stick layout

```
Sparky/
├── sparky.cmd          ← the one launcher (Linux/macOS/Windows)
├── start.sh START.bat start.command   per-OS entry points it dispatches to
├── sparky/             the Python app (tier router, local provider, agent, tools, TUI)
├── context/            ← drop files here; auto-loaded every session
├── runtime/            bundled portable Python + Ollama + Qwen weights (gitignored)
├── data/               sparky.env (tier settings), sessions, redirected HOME (gitignored)
└── tools/              setup_usb · set_models · fetch_runtime · format_exfat
```

## How it works

```
        you type / drop an image
                 │
                 ▼
      agent loop (tool use: read·write·edit·search·run)
                 │
                 ▼
        ┌──── tier router ────┐
        │  fast        max    │   ← Ctrl-T / /model
        ▼                     ▼
   qwen3.5:4b          qwen3-coder:30b
   (snappy)            (best; a3b MoE)
        │                     │
        └──────── reply ──────┘   max→fast auto-downgrade if RAM is short
                 │
                 ▼   served by a bundled Ollama, 100% offline
```

The router holds the active tier, points the bundled Ollama at that tier's model, and serves
the call locally. If `max` can't be loaded on a host, the turn finishes on `fast` so you're
never stuck.

Built on the principles of
[OpenClaude-Portable](https://github.com/techjarves/OpenClaude-Portable); themed after
the author's `interview-copilot` (Sparky 🐤). Tests: `python -m pytest` (40 passing).
