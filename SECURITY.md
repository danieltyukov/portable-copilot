# Security

## Reporting

Use GitHub's private vulnerability reporting: the Security tab of
<https://github.com/danieltyukov/portable-copilot>, then "Report a
vulnerability". That opens a private thread visible only to the maintainers,
which is the right place for anything you would not want in a public issue.

This is one person's side project with no service behind it and no on-call
rotation. Expect a reply in days, not hours. There is no bounty.

If the problem is a stick you have lost rather than this code, there is nothing
to revoke: Sparky holds no keys, passwords or accounts. Whoever finds the stick
gets what is on it, which is described under "The stick" below.

## The code mode runs commands

In the code mode the model can read, write and edit files and run shell
commands on the computer the stick is plugged into, with your user's
permissions. Two things need your approval, one at a time:

- every shell command: Sparky shows the exact command and runs it only if you
  say yes
- any write or edit outside the folder you launched Sparky from

Writes and edits inside that folder go ahead without asking, and reads never
ask, wherever the file is. `/yolo` turns all approval off for the rest of the
session, and `--yolo` (or `SPARKY_YOLO=1` in `data/sparky.env`) starts with it
off. Use either only on a computer and in a folder you could afford to lose.

The study mode can only read files, list folders and search, and the chat and
write modes have no tools at all.

Anything the model reads can contain instructions aimed at it: a file in
`context/`, a page saved into the project, the output of a command it ran. A
local model is no better than a hosted one at ignoring them. The approval
prompt is what stands between such text and your shell, so read each command
before you approve it, including whatever comes after the first `&&` or `;`.

## The browser UI

`sparky.cmd web` serves the chat page on 127.0.0.1 only, so it cannot be
reached from the network. A token made fresh at each launch guards it in three
ways:

- The page itself needs the token. Sparky prints a link that carries it and
  opens the link in your browser; the server swaps the token for a cookie
  (HttpOnly, SameSite=Strict) and takes it out of the address bar. Without the
  link or the cookie the page answers 403, so another user or program on the
  computer cannot open it.
- Every API call must also carry the token in an `X-Sparky-Token` header,
  which only the page knows. A site open in another tab can send requests to
  127.0.0.1, but the browser will not let it read Sparky's page, so it cannot
  drive Sparky. The server sends no CORS headers, which is what keeps that
  browser rule in force; a change that adds one undoes this check.
- The server refuses any request whose Host header is not `127.0.0.1` or
  `localhost` with its own port. That stops DNS rebinding, where a site points
  its own domain name at 127.0.0.1 to get around the browser's rule.

The page's Content-Security-Policy lets it load scripts, styles, images and
connections only from Sparky itself, so an answer that contains an image or a
script cannot make the page fetch anything from elsewhere, and no other site
can show the page inside a frame. A link in an answer opens only when you
click it, in a new tab, with no referrer.

The limit is a program running as you. It can read the terminal where the link
was printed, or the cookie in your browser profile, and nothing on the same
computer can stop that. The link is also on the browser's command line for the
moment it takes to start, where other users of the computer may be able to see
it in the process list. The token changes at every launch, so a link left in
the terminal's scrollback or the browser's history is useless once Sparky has
stopped.

## The model server

Sparky starts Ollama on 127.0.0.1:11500, a port of its own so that it never
collides with an Ollama the computer already runs on 11434. `sparky.cmd serve`
starts only that server and prints its `/v1` address for other programs to
use. Ollama has no authentication: while it runs, any program on the computer
can use it, including to download and delete models. It does not listen on the
network unless you change `OLLAMA_HOST`. If you set that to `0.0.0.0` to share
a model with another machine, everyone on that network can use it too.

## The stick

Everything on the stick is readable by whoever holds it. Sparky encrypts
nothing: the conversations in `data/sessions/` (one file each, in full), the
lines you typed in `data/history`, your settings, and whatever you put in
`context/`. Treat the stick like a notebook. Keep it with you, and keep off it
what you would not write in one. `PRIVACY.md` lists what is stored where and
how to wipe it.

It works the other way round as well. A stick that has been out of your hands
may not hold the code you put on it, and running `sparky.cmd` runs that code
as you. If you have lost track of a stick for a while, wipe it and set it up
again from a fresh download. And any computer you plug the stick into can read
all of it while it is plugged in.

## What gets downloaded

Setup, the first launch on a new OS, `models add` and `/pull` download the
following, all over HTTPS:

| What | From |
| --- | --- |
| Portable Python | The official python-build-standalone releases on GitHub (`astral-sh/python-build-standalone`) |
| Ollama | The official Ollama releases on GitHub (`ollama/ollama`) |
| rich, prompt_toolkit and what they depend on, plus zstandard when setup needs it to unpack the Linux Ollama archive | PyPI, through pip |
| Model weights | The Ollama registry, or Hugging Face for `hf.co/...` names |

The Python and Ollama versions are pinned in `sparky/runtime.py`, so a new
upstream release changes nothing on your stick until it has been tested here
and the pin moved. Each Python and Ollama archive is checked against the
SHA-256 list its release publishes, and setup stops if one does not match.

Two limits. The checksum list comes from the same GitHub release as the
archive, so it catches a download that was damaged or altered on the way, but
not a release that was compromised at the source. And on Windows, setup takes
only the files it needs out of the Ollama zip rather than downloading all
1.3 GB of it, so those files are checked with the zip's own CRC-32, which
catches corruption but is not a cryptographic check; they still come straight
from the GitHub release over HTTPS. pip checks each package from PyPI against
the hash the index lists for it, and Ollama checks each layer of a model
against its SHA-256 digest as it downloads.

A model file is data rather than a program, but Ollama has to parse it, and a
deliberately malformed one is a risk in the way a malformed image file is. Add
models from sources you would trust with any other download.

## What leaves the computer

See `PRIVACY.md`. In short: your conversations never do. The only network
traffic is the downloads above, and whatever a shell command you approved does.
