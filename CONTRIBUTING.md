# Contributing

Bug reports and patches are welcome. There is no CLA and no style bikeshed;
match the code that is already there. Model suggestions have their own issue
form.

## Layout

    sparky.cmd             one launcher for every OS: a shell script and a batch file at once
    setup.sh, setup.bat    first-time setup from a clone or a zip
    start.sh               what sparky.cmd runs on macOS and Linux
    START.bat              what sparky.cmd runs on Windows
    start.command          a Finder double-click on macOS, which runs start.sh
    sparky/                the app (Python >= 3.10, standard library plus rich and prompt_toolkit)
      cli.py               subcommands and flags
      config.py            settings from data/sparky.env and the environment
      catalog.py           the curated open-weight models, tagged by purpose
      hardware.py          RAM, CPU, drives, free space, filesystem checks
      ollama.py            client for the bundled model server: list, pull, show, delete
      models.py            installed models, names, which to open with, which to fall back to
      modes.py             chat, code, write, study
      engine.py            wires a conversation together for this computer
      router.py            sends each request to the active model, retrying on a smaller one
      agent.py             the turn loop: tools, history trimming, cancel
      manage.py            `models ...` and `doctor`
      oneshot.py           `ask` and `serve`
      providers/local.py   chat requests and streaming
      context.py           the context/ folder, budgeted to the model's context window
      runtime.py           fetches portable Python, Ollama and the Python libraries for each OS
      wizard.py            the setup wizard
      ui.py, theme.py      the terminal UI
      web/server.py        the browser UI server (standard library, 127.0.0.1 only)
      web/static/          index.html, app.js, style.css, icon.svg
      tools.py             file, search and shell tools for the code and study modes
      sessions.py          saved conversations in data/sessions/
      images.py            image attachments (/img, /paste)
      clipboard.py         reading an image off the clipboard on each OS
    tools/                 scripts for setup, the Windows launch, testing and the artwork
      e2e.sh               the end-to-end check (see below)
      e2e_tui.py           drives the terminal UI for e2e.sh
      fetch_python.sh      a portable Python for setup.sh when the computer has none
      fetch_python.ps1     the same for setup.bat
      start_server.ps1     starts the model server for START.bat, unless one is running
      format_exfat.sh      converts a FAT32 stick to exFAT on Linux, so the model server can run
      sparky_assets.py     the pixel budgie and the icons drawn from it
      banner.html          the README banner, docs/logo.png and docs/logo-dark.png
      render_assets.sh     regenerates the icons and the banner (needs Chrome)
    site/                  the project site, static, no build step
    docs/                  the logo pair, screenshots, ARCHITECTURE.md
    tests/                 pytest for the Python package

`engine.py`, `router.py`, `agent.py`, `models.py` and `modes.py` know nothing
about the terminal or the browser. `ui.py`, `web/server.py` and `ask` are front
ends over the same conversation, which `engine.py` puts together, and that is
what lets a turn be tested without any of them. A change to what a turn can do
goes in `agent.py` once; a new in-session command goes in both `ui.py` and
`web/server.py`. The tests run with no model server and no network, and should
stay that way: where a test needs a server, give it a fake one.

`sparky.cmd` is read by two interpreters. On macOS and Linux, sh runs the `:;`
lines and hands over to `start.sh` before it reaches the batch half; on Windows,
cmd treats each `:;` line as a label and skips it. Keep the file's LF line
endings (`.gitattributes` holds them), because a carriage return breaks the
shell half. Keep `goto` and `call :label` out of the batch half too: cmd finds
labels unreliably in a file with LF endings.

## Running the tests

```
python -m pip install rich prompt_toolkit pytest    # once; Python >= 3.10
python -m pytest
ruff check sparky tests tools                       # the lint CI runs
```

CI runs the tests on Windows, macOS and Linux with Python 3.10 and 3.12. A
separate lint job runs ruff, shellcheck on the shell scripts, and a check that
no em dash, en dash or emoji has crept into the docs or the code.

Before a release, and after any change to the launchers, setup, `runtime.py` or
`ollama.py`, run the end-to-end check:

```
tools/e2e.sh
```

It builds a throwaway stick in a temporary folder, downloads the portable
runtime and a tiny model into it, and drives `ask`, `web` and `serve` against
the real model server, and the terminal UI through `tools/e2e_tui.py`. It needs
internet and several minutes, which is why it is not in CI.

## Running the app

From a checkout you do not need a stick. `python -m sparky` runs on whatever
Python you have, against an Ollama you start yourself:

```
ollama serve                                         # in another terminal, if it is not running
ollama pull qwen3.5:0.8b                             # any small model will do
OLLAMA_HOST=127.0.0.1:11434 python -m sparky --model qwen3.5:0.8b
```

Sparky's own default is 127.0.0.1:11500, a port chosen so that the server on
the stick never collides with an Ollama the computer already runs on 11434.
Point `OLLAMA_HOST` at yours (on Windows, `set OLLAMA_HOST=127.0.0.1:11434` in
cmd or `$env:OLLAMA_HOST = "127.0.0.1:11434"` in PowerShell). Settings and
conversations go to `data/` in the checkout, which git ignores.

To run it the way a stick does, with the bundled runtime, run `./setup.sh` (or
`setup.bat` on Windows) and give the repository folder as the target. The
runtime and the models land in `runtime/`, which git also ignores, and
`./sparky.cmd` then behaves exactly as it would from a stick. Setup keeps its
downloads in `.cache/downloads/` so that the next stick does not fetch them
again; delete the folder whenever you like. `sparky.cmd doctor` checks the
hardware, the runtime and the models.

## Adding a model to the catalog

The catalog in `sparky/catalog.py` is what the wizard and `models recommend`
choose from, so a model in a purpose's pick list is a promise that it does that
job on an ordinary laptop with no GPU. Adding one takes two edits:

1. An `Entry` in `ENTRIES`, under the memory band it belongs to: the Ollama
   tag, a display name, the maker, the download size in GB, the total and
   active parameters in billions, the licence, a one-line note for people
   choosing, and whether it reads images, calls tools and thinks before
   answering. Check that the tag exists at <https://ollama.com/library> at the
   exact size you mean, and take the size from that page or from `ollama pull`.
   The active parameter count matters most, because it decides speed on a CPU:
   a 30B mixture-of-experts model with 3B active feels quicker than a dense 14B
   one.
2. The tag in the `PICKS` list of each purpose it is good at (`everyday`,
   `code`, `write`, `study`, `vision`, `translate`, `reason`), in order of
   preference. Only the purposes it is really good at: the wizard trusts these
   lists. A model that is only good with a GPU can have an entry but stays out
   of `PICKS`, like the dense large models at the end of `ENTRIES`.

Write the licence the way the model card names it. People choose models on
this, so do not shorten a model's own licence to "open".

Sparky works out the memory a model needs from its size (`Entry.ram_gb`), and
the wizard will not offer a model that does not fit. Check that figure against
reality: watch the model server's memory while the model answers a long
question, and say in the pull request if it needs more.

Then run it through Sparky on a CPU-only laptop, in the modes its purposes
imply: a coding model in the code mode making a real edit, a vision model
reading a screenshot, a study model answering from a few files in `context/`.
Put the computer, the speed Sparky reports and one sample answer in the pull
request.

## Style

- Match the code around your change. Comments say why, not what.
- Plain prose in docs, comments, UI copy and commit messages. No emojis, and no
  em or en dashes as punctuation; use a comma, a colon, brackets or a new
  sentence. CI fails on either in the docs and the code.
- British spelling in docs and UI copy: licence (the noun), colour, organise,
  behaviour. Identifiers follow the library they talk to, so `color` stays
  `color` in CSS and in rich.
- The Python libraries on a stick live in one folder, `runtime/pylib/`, shared
  by every OS. Anything the app imports must therefore be pure Python: a
  library with compiled parts would work on the OS that installed it and
  nowhere else. Today that means the standard library, rich and prompt_toolkit.
- Code runs on Python 3.10. The stick bundles 3.12, but setup and a checkout
  use whatever Python the computer has.
- The code mode asks before every shell command, and before any write or edit
  outside the folder Sparky was started in, unless the person has turned that
  off with `/yolo`. Nothing that weakens either will be merged, and nothing
  that reaches the network without being asked to: no telemetry, no update
  check, no account.
- Conventional commit prefixes: `feat:`, `fix:`, `docs:`, `test:`, `chore:`,
  `ci:`. Add a line under Unreleased in `CHANGELOG.md`.

## Pull requests

One change per pull request, with a test for anything in `sparky/`. Say in the
description what you ran and what CI cannot see: a real stick (exFAT or FAT32),
a launch from the stick on Windows or macOS, a laptop with 8 GB of RAM, a
computer with no network. A change to the launchers, setup or `runtime.py`
needs `tools/e2e.sh` run at least once; say on which OS.
