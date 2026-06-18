# Sparky → Fully-Local, Multi-Tier Qwen (design)

**Date:** 2026-06-18
**Status:** Approved
**Supersedes the online/offline split in:** `2026-06-17-sparky-portable-copilot-design.md`

## Goal

Remove every dependency on the Claude / Anthropic API. Sparky becomes a **100%
local** AI coding copilot powered by Ollama-served Qwen models, with two
user-switchable **tiers** that trade speed for accuracy — the local analogue of
switching between Haiku and Opus.

## Why

- True offline-first: no API key, no network, nothing leaves the machine.
- The previous "Claude online / Qwen offline" split is gone; there is no
  "online" path anymore.
- The leaderboard's best open-weight models (GLM-5.2, DeepSeek V4, Kimi K2.6)
  are 240 GB–900 GB and need server-class RAM — impossible on a USB stick + a
  laptop CPU. The practical ceiling for "any laptop + ~29 GB stick" is ~30 B
  total params, so the tiers are chosen within that envelope.

## Model tiers

| Tier | Ollama model | Download | RAM to run | Notes |
|---|---|---|---|---|
| `fast` | `qwen3.5:4b` | ~3.4 GB | ~5 GB | Snappy; runs on any laptop. |
| `max` (default) | `qwen3-coder:30b` | ~19 GB | ~20 GB | a3b MoE (~3 B active) → best CPU agentic coder; ~10 tok/s on CPU. |

- **Default tier: `max`.** Sparky opens on the strongest model.
- **Switching:** `Ctrl-T` cycles; `/model fast|max` sets it directly; aliases
  `haiku`→fast, `sonnet`/`opus`→max are accepted for muscle memory.
- **Tier fallback (replaces the old online→offline fallback):** if the `max`
  model fails to load on a host (typically not enough RAM), the turn
  auto-degrades to `fast` and emits a `⚠ tier downgraded` note rather than
  failing the turn.

Env overrides: `SPARKY_FAST_MODEL`, `SPARKY_MAX_MODEL`, `SPARKY_TIER`,
`OLLAMA_HOST`, `SPARKY_YOLO`.

## Architecture changes

### Removed
- `sparky/providers/claude.py` (Claude provider).
- `sparky/connectivity.py` (api.anthropic.com online/offline monitor).
- API-key handling: `Config.anthropic_api_key`, `model`, `opus_model`;
  first-run key capture in `__main__.py`; key writing in `config.write_env`.
- Tests: `tests/test_claude_payload.py`, `tests/scratch_live_e2e.py`.

### Changed
- **`router.py`** — slims from an online/offline switch to a thin **tier
  selector** over `LocalProvider`. Keeps the `chat()`/`chat_stream()` interface
  the agent depends on. Tracks the active tier, swaps the local model on tier
  change, and downgrades `max`→`fast` on a load error. Backend label like
  `qwen:qwen3-coder:30b`.
- **`config.py`** — replaces key/Claude fields with tier config
  (`fast_model`, `max_model`, `tier`, `tiers` map) and the matching env
  overrides. `write_env` keeps generic settings only.
- **`providers/local.py`** — gains a small `set_model()` and a clearer
  load-error message; payload translation unchanged.
- **`ui.py`** — toolbar/banner show `‹tier› · ● local` instead of online/offline;
  `Ctrl-T` and `/model` cycle tiers; help text updated.
- **`__main__.py`** — `--self-test` checks Ollama reachability + that both tier
  models are pulled; drops the key/internet checks and first-run key prompt.
- **`agent.py`** — system prompt reworded for always-local operation.
- **`theme.py`** — tagline → `portable copilot · fully local · qwen`.
- **`__init__.py`** — docstring rewritten; version → `0.3.0` (breaking).
- **Tests** — `test_router.py` and `test_config.py` rewritten for tiers;
  remaining tests scrubbed of Claude/online references.

### Setup & USB
- **`tools/setup_usb.sh` / `.ps1`** — pull *both* tier models
  (`qwen3.5:4b`, `qwen3-coder:30b`). `fetch_runtime.*` unchanged (it only
  fetches a portable Python + Ollama).
- **Stick at `/media/danieltyukov/Sparky`** — sync the new app + README,
  `ollama rm qwen2.5-coder:3b`, then pull the two tier models into the stick's
  model store.

### Docs / GitHub
- README rewritten around "fully local, switchable tiers" (pitch, tables, ASCII
  flow, commands).
- Repo description updated; pushed to `main`; repo made **public**.

## Kept as-is

Agent loop + tools, sessions/resume, clipboard & image paste (images still pass
through to the local model; vision needs a `qwen3-vl` model — noted in README),
the `context/` folder, the cross-platform polyglot launcher, and exFAT handling.

## Testing

`python -m pytest` must pass. New unit tests cover: tier defaults + env
overrides in config; router tier selection, tier switching, and max→fast
load-failure fallback. Existing tool/session/image/agent tests must stay green.
