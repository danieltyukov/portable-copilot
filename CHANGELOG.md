# Changelog

All notable changes to Sparky are listed here. The format follows Keep a
Changelog and the project uses semantic versioning.

## [Unreleased]

## [0.4.0] - 2026-10-04

Sparky is now for any purpose and any open-weight model, not a coding copilot
with two Qwen tiers. Sticks made with 0.3 keep working; run setup on them once
to upgrade the runtime.

### Added
- A setup wizard (`setup.sh`, `setup.bat`, or `sparky.cmd setup`) that works on
  Windows, macOS and Linux and needs no Python on the computer. It finds the USB
  drive, refuses FAT32 with steps to reformat, asks what the stick is for and
  how much memory its computers have, recommends models that fit, and puts a
  runtime for Windows, macOS (Apple Silicon and Intel) and Linux on the stick.
- A curated model catalog across Qwen, Gemma, Llama, Mistral, Phi, gpt-oss,
  DeepSeek, Granite and others, each with its size, speed on a CPU, licence and
  what it is good for. `sparky.cmd models recommend --for <purpose>` and
  `models catalog` show it.
- `sparky.cmd models` to list, add, remove and choose models, with download
  progress. Any Ollama tag or Hugging Face GGUF (`hf.co/...`) works. In a
  conversation, `/models` and `/pull`.
- Modes: chat, code, write and study (`/mode`, `--mode`). Only code and study
  get file tools, so small models answer the others faster.
- `sparky.cmd web`, a browser chat with streaming replies, model and mode
  pickers, image attachments and approval cards for commands. It listens on
  127.0.0.1 only, and the page opens only from the link printed in the
  terminal.
- `sparky.cmd ask` for one answer, with piped text added to the question.
- `sparky.cmd serve`, the stick's model server on its own, with an
  OpenAI-compatible API for other apps.
- `sparky.cmd doctor` reports the computer's memory, the stick's filesystem,
  the runtimes on the stick and whether each model fits.
- `Ctrl-C` stops a reply instead of quitting, `/think` shows the reasoning of
  models that think first, and each reply ends with its speed in tokens per
  second.
- When a model will not load on a computer (usually too little memory), the
  reply comes from the next smaller model on the stick.
- `tools/e2e.sh`, an end-to-end check on a real throwaway stick, and CI on
  Windows, macOS and Linux.

### Changed
- The context window is set on every request (8192 tokens, or 16384 with 24 GB
  of memory). Ollama's default on a CPU is 4096, which silently cut off long
  conversations and the context folder.
- The context folder is budgeted to the window, and long conversations are
  trimmed from the oldest turn, so neither can crowd out the other.
- Code mode asks before writing or editing outside the folder it was started
  in, as well as before every shell command.
- Ollama v0.35.1 (from v0.30.8), which can run Gemma 4 and Qwen 3.8, and
  Python 3.12.15. The Linux and Windows Ollama builds are fetched without their
  GPU libraries: on Windows only the CPU files are downloaded (24 MB instead of
  1.5 GB). Downloads are checked against each release's checksums and cached.
- The launchers start the model server in its own process group, share one
  that is already running, and stop only the one they started.
- The terminal UI and site follow the Sparky look shared with meeting-copilot.

### Removed
- `tools/setup_usb.*` and `tools/set_models.*`, replaced by the setup wizard and
  `sparky.cmd models`. The fast and max tiers are gone; `SPARKY_FAST_MODEL`,
  `SPARKY_MAX_MODEL` and `SPARKY_TIER` are still read, and `/model fast` and
  `/model max` pick the smallest and largest model on the stick.

### Fixed
- The bundled Ollama no longer contacts ollama.com on its own: it is started
  with `OLLAMA_NO_CLOUD=1`, which stops its "model recommendations" fetch at
  start-up and every few hours. Downloading models is unaffected.
- With thinking on, a model gets three times the reply budget, and a reply
  that was all reasoning and no answer says so.
- In the browser, `/pull`, `/context`, `/sessions`, `/resume` and `/yolo` are
  handled by Sparky instead of being sent to the model.
- `python -m sparky` failed when the launcher was started from any folder but
  the stick's own.
- The Python libraries are installed in isolation, so a package the setup
  computer happens to have can no longer be left off the stick.
- The folder Sparky is started in is no longer on Python's import path, and an
  empty library path no longer points the model server at it.

## [0.3.0] - 2026-06-18

Fully local: the Claude API is gone, and Sparky runs Qwen through a bundled
Ollama with fast and max tiers, switched with `Ctrl-T`.

## [0.2.0] - 2026-06-17

A streaming terminal UI, image paste, saved sessions and the Windows runtime.

## [0.1.0] - 2026-06-17

The first portable build: one launcher for every OS, a runtime on the stick,
and a coding agent that falls back from the Claude API to a local model.
