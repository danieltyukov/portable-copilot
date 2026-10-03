#!/usr/bin/env bash
# End-to-end check on a real, throwaway stick (macOS or Linux).
#
#   tools/e2e.sh                        build one in a temp folder, test it, delete it
#   tools/e2e.sh --stick /media/me/Sparky   test a stick that is already set up
#   KEEP=1 tools/e2e.sh                 keep the temp stick afterwards
#
# Needs the internet the first time (about 1.5 GB on Linux, 0.4 GB on macOS,
# plus the model); downloads are cached in .cache/downloads. The model is
# qwen3.5:0.8b unless E2E_MODEL says otherwise: it is small, and it can use
# tools, so the code-mode check means something.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${E2E_MODEL:-qwen3.5:0.8b}"
STICK=""
[ "${1:-}" = "--stick" ] && STICK="${2:?--stick needs a path}"
FAILS=0

pass() { echo "[PASS] $*"; }
fail() { echo "[FAIL] $*"; FAILS=$((FAILS + 1)); }

if [ -z "$STICK" ]; then
  TMP="$(mktemp -d)"
  STICK="$TMP/Sparky"
  [ "${KEEP:-0}" = 1 ] || trap 'rm -rf "$TMP"' EXIT
  echo "Setting up a throwaway stick in $STICK"
  if "$ROOT/setup.sh" --target "$STICK" --for everyday --models "$MODEL" --os this --yes >"$TMP/setup.log" 2>&1; then
    pass "setup"
  else
    fail "setup (see $TMP/setup.log)"; tail -20 "$TMP/setup.log"; exit 1
  fi
fi
L="$STICK/sparky.cmd"
WORK="$(mktemp -d)"

out="$("$L" doctor 2>&1)" && pass "doctor" || { fail "doctor"; echo "$out"; }

out="$(cd "$WORK" && "$L" ask "What is the capital of France? One short sentence." 2>&1)"
echo "$out" | grep -qi "paris" && pass "ask answers" || fail "ask: $out"

out="$(printf 'apples\nbananas\ncherries\n' | "$L" ask "How many fruits are listed? Answer with a number." 2>&1)"
echo "$out" | grep -Eq "3|three" && pass "ask reads piped text" || fail "ask with stdin: $out"

# Tools: the answer is only in a file, so getting it right means the model
# called read_file and the result came back through the whole stack.
echo "The secret word is marmalade." > "$WORK/secret.txt"
# A model this small fumbles now and then, so it gets a second try.
for _ in 1 2; do
  out="$(cd "$WORK" && "$L" ask --mode code "Read the file secret.txt with the read_file tool and tell me the secret word." 2>&1)"
  echo "$out" | grep -qi "marmalade" && break
done
echo "$out" | grep -qi "marmalade" && pass "code mode reads a file with a tool" || fail "code mode tool use: $out"

# Writing is checked loosely: a model this small sometimes picks an odd path.
(cd "$WORK" && "$L" ask --mode code --yolo \
  "Use the write_file tool to create hello.py with the content: print('hi from sparky')" >/dev/null 2>&1)
[ -f "$WORK/hello.py" ] && pass "code mode writes a file" || echo "[NOTE] the model did not write hello.py here (it may have chosen another path)"

out="$(cd "$WORK" && "$L" ask --mode code "Run the shell command: ls" 2>&1)"
echo "$out" | grep -q "not allowed without --yolo" && pass "shell commands need approval" \
  || fail "a shell command ran without approval"

"$L" models 2>&1 | grep -q "$MODEL" && pass "models lists $MODEL" || fail "models list"

# Background launchers get their own process group (set -m), so they can be
# sent a Ctrl-C the way a terminal would: to the whole group.
set -m

# model server for other apps
"$L" serve >"$WORK/serve.log" 2>&1 &
SPID=$!
for _ in $(seq 1 60); do grep -q "OpenAI-compatible" "$WORK/serve.log" 2>/dev/null && break; sleep 0.5; done
out="$(curl -s -m 120 http://127.0.0.1:11500/v1/chat/completions -H 'Content-Type: application/json' \
  -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"Say hello.\"}]}")"
echo "$out" | grep -q '"choices"' && pass "serve: /v1/chat/completions" || fail "serve: $out"
kill -INT -- "-$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null

# browser UI API
PORT=18765
"$L" web --no-browser --port "$PORT" >"$WORK/web.log" 2>&1 &
WPID=$!
for _ in $(seq 1 60); do grep -q "token=" "$WORK/web.log" 2>/dev/null && break; sleep 0.5; done
TOKEN="$(sed -n 's/.*token=\([A-Za-z0-9_-]*\).*/\1/p' "$WORK/web.log" | head -1)"
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")"
[ "$code" = 403 ] && pass "web: the page needs the link" || fail "web: page served without the link ($code)"
page="$(curl -s -L -c "$WORK/jar" -b "$WORK/jar" "http://127.0.0.1:$PORT/?token=$TOKEN")"
echo "$page" | grep -q "sparky-token" && pass "web: the link opens the page" || fail "web: link did not open the page"
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/state")"
[ "$code" = 403 ] && pass "web: API refuses calls without the token" || fail "web: API answered without token ($code)"
out="$(curl -s -N -m 180 -H "X-Sparky-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text": "Reply with the word ready."}' "http://127.0.0.1:$PORT/api/chat")"
echo "$out" | grep -q '"type": "done"' && pass "web: a reply streams to the end" || fail "web: $out"
kill -INT -- "-$WPID" 2>/dev/null; wait "$WPID" 2>/dev/null
set +m

# terminal UI
if python3 -c "import pexpect" 2>/dev/null; then
  python3 "$ROOT/tools/e2e_tui.py" "$STICK" || FAILS=$((FAILS + 1))
else
  echo "[SKIP] terminal UI (pip install pexpect to include it)"
fi

sleep 1
if pgrep -f "$STICK/runtime/ollama/pkg" >/dev/null; then
  fail "a model server was left running"
  pkill -f "$STICK/runtime/ollama/pkg"
else
  pass "no model server left running"
fi
rm -rf "$WORK"

echo
[ "$FAILS" = 0 ] && echo "All end-to-end checks passed." || echo "$FAILS check(s) failed."
exit $((FAILS > 0))
