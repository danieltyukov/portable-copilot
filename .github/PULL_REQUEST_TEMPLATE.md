## What this changes

<!-- What the change is and why it is right. One or two paragraphs. -->

## How it was checked

<!--
CI runs these on every push, on Windows, macOS and Linux:

  python -m pytest
  ruff check sparky tests tools
  shellcheck -S warning *.sh start.command tools/*.sh

A note here is about what CI cannot see: a real stick (exFAT or FAT32), a
launch from the stick on Windows or macOS, a laptop with 8 GB of RAM, a
computer with no network. A change to the launchers, setup, runtime.py or
ollama.py needs tools/e2e.sh run at least once; say on which OS.
-->

## Notes

<!--
Anything a reviewer would otherwise have to work out: a new catalog entry and
the computer you ran it on, a prompt change in modes.py and how the answers
read afterwards, a new dependency and why it earns its place (it must be pure
Python, because runtime/pylib is shared by every OS on the stick).

Things the review will check for, because each is easy to break by accident:
the code mode still asks before every shell command and before any write
outside the launch folder, unless /yolo is on; the browser UI still listens
on 127.0.0.1 only, wants the token for the page and for every API call,
checks the Host header, and sends no CORS headers; sparky.cmd keeps its LF
line endings; and nothing new reaches the network without the person asking
for it.

No emojis, and no em or en dashes as punctuation, in code, comments,
documentation or the commit message.
-->
