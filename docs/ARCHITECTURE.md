# Architecture

One idea: everything an open-weight model needs to run, for every common
computer, on one drive. The launcher picks the right runtime for the computer
it finds itself on, starts the model server against weights that every OS
shares, and hands over to a terminal or browser front end. Nothing is
installed on the host and nothing it writes leaves the stick.

## Launching

```
  sparky.cmd                  one file for every OS: a POSIX shell script that
        |                     is also a Windows batch file (the ":;" lines are
        |                     labels to cmd and no-ops to sh)
        |-- start.sh          macOS and Linux (start.command is the Finder double-click)
        '-- START.bat         Windows
        |
        |   HOME, XDG_*, APPDATA, USERPROFILE -> data/ on the stick
        |   OLLAMA_MODELS -> runtime/ollama/models, OLLAMA_HOST -> 127.0.0.1:11500
        v
  runtime/python/<os-arch>    missing? tools/fetch_python.{sh,ps1} fetches it
        |                     (checksummed), then `python -m sparky runtime`
        |                     fetches Ollama and the libraries
        v
  runtime/ollama/pkg/<os-arch>  `ollama serve`, unless one is already listening
        |                       (a second window shares it; only the window that
        |                       started it stops it)
        v
  python -m sparky [command]  (cli.py)
```

On Linux a FAT stick mounts without permission to run programs. The launchers
then start Python and Ollama through the dynamic loader (`ld-linux`), which
reads the binary instead of executing it. Ollama still has to spawn its own
`llama-server`, which the loader trick cannot reach, so FAT is refused at setup
and exFAT recommended: it holds files over 4 GB and mounts executable on every
OS.

## The stick

```
  Sparky/
    sparky.cmd START.bat start.sh start.command setup.sh setup.bat
    sparky/                       the app
    tools/                        fetch_python.sh/.ps1, start_server.ps1, format_exfat.sh
    context/                      the user's reference files
    runtime/
      python/<os-arch>/           python-build-standalone, pruned (no tests, Tk, headers)
      pylib/                      rich, prompt_toolkit: pure Python, shared by every OS
      ollama/pkg/<os-arch>/       Ollama, CPU libraries only; macos/ is one universal build
      ollama/models/              the weights, shared by every OS
    data/
      sparky.env                  settings
      sessions/                   saved conversations
      home/ config/ cache/ ...    the redirected profile folders
```

Each runtime folder carries a `SPARKY_VERSION` stamp. Setup replaces a folder
whose stamp does not match the pinned release, which is how sticks made by
older versions get upgraded, and never touches the Python it is running from.

## Setup

```
  setup.sh / setup.bat        fetch a portable Python into the checkout
        v
  wizard.py                   where? (hardware.list_drives: /proc/mounts + lsblk,
        |                      /Volumes + mount, GetLogicalDrives + GetDriveTypeW)
        |                     what for? which computers? -> catalog.plan()
        |                     which systems? (default: Windows, both Macs, Linux)
        |-- copy_app          the app files only; data, context and models are kept
        |-- runtime.ensure    per target: Python, then Ollama; pylib with the host's Python
        '-- models            a fresh `ollama serve` on a free port, pointed at the
                              stick, so setup never pulls into another stick's server
```

`runtime.py` downloads from pinned GitHub releases and checks each archive
against the release's published SHA-256 list. The Linux and Windows Ollama
builds are over 1.3 GB, nearly all of it GPU libraries a portable CPU build does
not use. For Windows, `RangeFile` gives `zipfile` a seekable view of the remote
zip over HTTP range requests, so only the central directory and the CPU files
(about 24 MB) are fetched; zip's per-file CRC-32 checks them. The Linux
`.tar.zst` has no index, so it is downloaded once, verified, cached in
`.cache/downloads`, and streamed through a zstd decoder (Python 3.14's, the
`zstandard` module, the `zstd` command, or `zstandard` installed for setup
only) with the GPU folders skipped. Everything is unpacked in a temporary
folder and then copied with links resolved, because FAT and exFAT cannot store
them.

## A conversation

```
  front end                   ui.py (terminal) or web/server.py (browser) or oneshot.py (ask)
        |  run_turn(text, images, on_event)
        v
  Agent                       (agent.py) system prompt = mode prompt + context folder,
        |                     budgeted to 40% of the window; history trimmed by
        |                     fit_history; tools limited to the mode's set
        v
  Router                      (router.py) the active model; offers tools and `think`
        |                     only to models whose /api/show lists them; when a model
        |                     will not load, retries once on the next smaller one
        v
  LocalProvider               (providers/local.py) /api/chat, streamed NDJSON:
        |                     message.thinking, message.content, tool_calls, then
        |                     eval_count/eval_duration for tokens per second
        v
  Ollama on 127.0.0.1:11500
```

`modes.py` holds four modes: `chat` and `write` have no tools (small models
answer faster and more reliably without them), `study` can read and search,
and `code` can also write files and run commands. Shell commands, and writes
outside the folder Sparky was started in, go through a `confirm` callback that
each front end implements: a y/N prompt, an approval card in the page, or a
refusal in `ask` (which has no one to ask) unless `--yolo`.

The context window is always set explicitly (`options.num_ctx`), because
Ollama's default on a CPU-only computer is 4096 tokens and it truncates
silently. `config.context_window` picks 8192, or 16384 with 24 GB of memory or
more; `SPARKY_CTX` overrides it.

Stopping a reply sets the agent's cancel event and shuts the streaming socket
down. Closing the response is not enough: a read already blocked in `recv()`
(a large model still loading, say) only wakes when the socket is shut. The
unfinished turn is removed from history so the next question is not sent after
a dangling one.

## The model catalog

`catalog.py` lists models that run from a stick on a normal computer, each with
its download size, total and active parameters, licence and a one-line note.
Speed on a CPU follows the active parameters, so a 30B mixture-of-experts model
with 3B active is "quick" while a dense 14B one is "slow". `PICKS` orders, per
purpose, the models worth recommending; `recommend` takes the first that fit the
memory (installed memory less what the OS keeps) and the free space, and `plan`
chooses one model per purpose, sharing where one covers several, plus a quick
small one when the main pick is large.

## The browser UI

`web/server.py` is a `ThreadingHTTPServer` on 127.0.0.1 with one page and a
JSON API. Each turn runs on a worker thread and its events go through a queue
to a server-sent-events response. A per-launch token, written only into the
page, must accompany every API call, and the Host header must be 127.0.0.1 or
localhost; together they stop other websites and DNS rebinding from reaching
the API. The page itself (`web/static`) has no build step and loads nothing
from the network.
