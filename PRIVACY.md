# Privacy

Sparky has no server of its own. The model runs on the computer the stick is
plugged into, and nothing you type is sent anywhere. This page lists
everything that does go over the network, and everything Sparky keeps on the
stick.

## What is sent, and where

| Data | Where it goes |
| --- | --- |
| Your questions and the answers | Nowhere. The model runs on this computer, in the model server Sparky starts on 127.0.0.1. Unplug the network and it still answers. |
| Files in `context/`, images you attach, files the code and study modes read | Nowhere. They go to the same local model. |
| Shell commands you approve in the code mode | Wherever the command goes. If you approve `curl` or `pip install`, that reaches the network because you said yes to it. |
| Setup, a first launch on a new OS, `models add` and `/pull` | Downloads only: portable Python and Ollama from their GitHub releases, a few Python libraries from PyPI, model weights from the Ollama registry or Hugging Face. Those services see what any download shows them: your IP address and what was fetched. |
| Anything to the author | Nothing. |

There is no analytics, no telemetry, no crash reporting and no update check.
Sparky asks the model server to go online only to download a model you chose.
Left to itself, the bundled Ollama would also ask ollama.com for "model
recommendations" when it starts and every few hours, so Sparky starts it with
`OLLAMA_NO_CLOUD=1`, which turns that off along with Ollama's cloud-hosted
models. Downloading models works as before.
The browser page is served from the stick and loads nothing from the internet;
a link in an answer opens only if you click it, in a new tab, and the page
sends no referrer with it.

The project website is a different matter: it is hosted on GitHub Pages and
loads its fonts from Google Fonts, so GitHub and Google see a visit to it as
they would a visit to any site. Sparky itself never opens the website.

## What is stored on the stick

All of it is in the `Sparky` folder, unencrypted, and nothing else is written
to `data/`.

| Path | What it holds |
| --- | --- |
| `data/sessions/` | One file per conversation, saved after every turn: your messages, the answers, and what the tools passed back (command output, the contents of files the model read). Images are not kept; a marker stands in for each one. |
| `data/history` | The lines you typed at the terminal prompt, for the up arrow. |
| `data/sparky.env` | Your settings: which models, which mode, and so on. No keys or passwords. |
| `data/home/`, `data/config/`, `data/share/`, `data/cache/` (macOS and Linux); `data/home/`, `data/appdata/`, `data/localappdata/` (Windows) | Stand-ins for your home and app-data folders. The launcher points the computer's home folder settings here, so whatever the runtime would have written to your home folder stays on the stick. |
| `data/ollama.log` (and `data/ollama.err.log` on Windows) | The model server's log: requests and timings, not the text of the conversation. |
| `context/` | Whatever you put there. |
| `runtime/` | Python, Ollama and the model weights. Nothing personal. |

## What the computer may keep

Sparky installs nothing on the computer, but a few things are outside its
control:

- The shell you launched from keeps its own history, so `sparky.cmd ask "..."`
  leaves the question in it.
- On macOS and Windows, `/paste` saves the clipboard image as
  `sparky_clip_*.png` in the system's temporary folder and deletes it as soon
  as it has been read.
- `sparky.cmd web` opens your default browser, which may keep the 127.0.0.1
  address in its history. The token in that address stops working when Sparky
  stops.
- The setup wizard, on the computer you run it on, keeps a download cache in
  `.cache/` inside the folder you ran it from, so that making a second stick
  does not download everything again. It tells you where the cache is and how
  big it is, and you can delete it whenever you like.
- The operating system may record that a USB drive was connected and what ran
  from it. Windows does, in several places.

## Wiping it

- One conversation: delete its file from `data/sessions/`. `/clear` starts a new
  conversation and leaves the old one saved.
- Every conversation and everything you typed: delete `data/sessions/` and
  `data/history`.
- Everything personal, keeping the models: delete `data/` and the contents of
  `context/`. The next launch makes fresh, empty folders and your settings go
  back to the defaults; the models stay installed.
- The lot: delete the `Sparky` folder, or reformat the stick.

Deleting a file on a USB stick does not overwrite it, and recovery tools can
often get it back. A full format (not a quick one) overwrites the whole stick,
which is the most you can do from an ordinary computer. If a conversation must
not survive at all, do not have it on a stick you might lend or lose.
