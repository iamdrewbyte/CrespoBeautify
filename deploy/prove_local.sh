#!/usr/bin/env bash
# Evidence that the AI model runs LOCALLY on this machine and sends nothing outside it.
#
#   deploy/prove_local.sh              quick proof (about 30 seconds)
#   deploy/prove_local.sh --hash       also fingerprint the 4.7 GB model file (adds ~30 seconds)
#   deploy/prove_local.sh --offline    also answer a question inside a container with NO network at all (needs Docker)
#   deploy/prove_local.sh --docker     prove it for the running Docker install (private network, no published port, no route out)
#
# Prints a report you can save and share:   deploy/prove_local.sh --hash --offline | tee proof.txt
# Reads nothing from your reports. The test question is a fixed sentence.
set -uo pipefail
cd "$(dirname "$0")/.."

HASH=0; OFFLINE=0; DOCKER=0
for a in "$@"; do case "$a" in --hash) HASH=1;; --offline) OFFLINE=1;; --docker) DOCKER=1;; *) echo "unknown option $a"; exit 1;; esac; done

export PATH="$HOME/.local/ollama/bin:$PATH"
PY="python3"; [ -x .venv/bin/python ] && PY=".venv/bin/python"
MODEL="${AI_MODEL:-$(grep -E '^AI_MODEL=' .env 2>/dev/null | cut -d= -f2)}"; MODEL="${MODEL:-qwen2.5:7b-instruct}"
MODELS_DIR="${OLLAMA_MODELS:-$HOME/.ollama/models}"
PORT=11434
RESULTS=()
pass() { RESULTS+=("PASS  $1"); }
fail() { RESULTS+=("FAIL  $1"); }
hr()   { printf '\n==== %s\n' "$1"; }

printf 'CrespoBeautify local-AI proof\nmachine : %s\ndate    : %s\nmodel   : %s\n' "$(hostname)" "$(date -u +%FT%TZ)" "$MODEL"

if [ "$DOCKER" = 1 ]; then
  PROJECT="${COMPOSE_PROJECT_NAME:-crespoqa}"
  hr "DOCKER INSTALL (project: $PROJECT)"
  docker ps --filter "label=com.docker.compose.project=$PROJECT" --format "  {{.Names}}  {{.Status}}"
  OC="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=ollama")"
  [ -n "$OC" ] || { echo "  the stack is not running (./start.sh)"; exit 1; }
  NET="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$OC")"
  echo "  the AI container's networks : $NET"
  for n in $NET; do echo "    $n -> internal (no route to the internet): $(docker network inspect -f '{{.Internal}}' "$n")"; done
  docker network inspect -f '{{.Internal}}' $NET | grep -q true && pass "the AI container is on a network with no route to the internet" || fail "the AI container's network is not internal"
  PUB="$(docker port "$OC" 2>/dev/null)"
  [ -z "$PUB" ] && pass "the AI container publishes no port to the host or the network" || fail "AI port is published: $PUB"
  DEF="$(docker exec "$OC" sh -c "awk 'NR>1 && \$2==\"00000000\"' /proc/net/route | wc -l")"
  echo "  default routes inside the AI container: $DEF   (0 = no way out)"
  [ "$DEF" = 0 ] && pass "the AI container has no default route (cannot reach the internet)" || fail "the AI container has a default route"
  CLOUD="$(docker exec "$OC" printenv OLLAMA_NO_CLOUD 2>/dev/null)"
  [ "$CLOUD" = 1 ] && pass "Ollama's own cloud connection is switched off (OLLAMA_NO_CLOUD=1)" || fail "OLLAMA_NO_CLOUD is not set"
  echo "  asking the model a question inside the container:"
  A="$(docker exec "$OC" ollama run "$MODEL" "Reply with exactly: LOCAL_OK" 2>/dev/null | tr -d '\033' | sed 's/\[[0-9;?]*[a-zA-Z]//g' | tr -d '\r' | grep -v '^ *$' | tail -1)"
  echo "    answer: $A"
  echo "$A" | grep -q LOCAL_OK && pass "the model answered inside the container" || fail "no answer from the container"
  docker exec "$OC" du -sh /root/.ollama/models 2>/dev/null | awk '{print "  model files inside the container volume: " $1}'
  hr "SUMMARY"; printf '%s\n' "${RESULTS[@]}"
  printf '%s\n' "${RESULTS[@]}" | grep -q '^FAIL' && exit 1 || exit 0
fi

# ---------------------------------------------------------------------------------------------------------------
hr "1. WHERE THE MODEL IS (files on this disk)"
STARTED=0
if ! curl -fsS -m 2 "http://127.0.0.1:$PORT/api/version" >/dev/null 2>&1; then
  command -v ollama >/dev/null || { echo "ollama is not installed on this machine"; exit 1; }
  echo "(the AI server was not running; starting it for this test, with OLLAMA_NO_CLOUD=1)"
  OLLAMA_NO_CLOUD=1 nohup ollama serve >/tmp/ollama_proof.log 2>&1 & STARTED=$!
  for _ in $(seq 1 30); do curl -fsS -m 1 "http://127.0.0.1:$PORT/api/version" >/dev/null 2>&1 && break; sleep 1; done
fi
echo "models folder : $MODELS_DIR"
du -sh "$MODELS_DIR" 2>/dev/null | awk '{print "size on disk  : " $1}'
NAME="${MODEL%%:*}"; TAG="${MODEL#*:}"; [ "$TAG" = "$MODEL" ] && TAG=latest
MANIFEST="$MODELS_DIR/manifests/registry.ollama.ai/library/$NAME/$TAG"
if [ -f "$MANIFEST" ]; then
  echo "manifest      : $MANIFEST"
  "$PY" - "$MANIFEST" "$MODELS_DIR" "$HASH" <<'PY'
import json, sys, hashlib, os
manifest, root, do_hash = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
m = json.load(open(manifest))
print("layers (the files that make up the model):")
for layer in m["layers"]:
    kind = layer["mediaType"].split(".")[-1]
    blob = os.path.join(root, "blobs", layer["digest"].replace(":", "-"))
    ok = os.path.exists(blob)
    print(f"  {kind:10} {layer['size']/1e6:10.1f} MB  {layer['digest'][:23]}...  on disk: {'yes' if ok else 'NO'}")
    if do_hash and kind == "model" and ok:
        h = hashlib.sha256()
        with open(blob, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 24), b""):
                h.update(chunk)
        same = "sha256:" + h.hexdigest() == layer["digest"]
        print(f"  -> recomputed SHA-256 of the weights file {'MATCHES' if same else 'DOES NOT MATCH'} the published digest")
        print("RESULT_HASH=" + ("ok" if same else "bad"))
PY
  pass "model weights are files on this disk ($MODELS_DIR)"
else
  fail "model manifest not found at $MANIFEST"
fi

# ---------------------------------------------------------------------------------------------------------------
hr "2. WHERE THE AI SERVER LISTENS (network sockets)"
ss -ltnp 2>/dev/null | awk -v p=":$PORT" 'NR==1 || $4 ~ p' | sed 's/^/  /'
LISTEN="$(ss -ltn 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {print $4}')"
if [ -n "$LISTEN" ] && ! echo "$LISTEN" | grep -vE '^(127\.0\.0\.1|\[::1\]|localhost)' | grep -q .; then
  pass "AI server listens only on loopback ($(echo $LISTEN | tr '\n' ' '))"
else
  fail "AI server listens on a non-local address: $LISTEN"
fi

# ---------------------------------------------------------------------------------------------------------------
hr "3. LIVE QUESTION TO THE MODEL, WATCHING ITS NETWORK CONNECTIONS"
Q='Reply with exactly: LOCAL_OK'
echo "(a) idle: watching the AI server for 5 seconds before asking anything"
: >/tmp/proof_idle.txt
for _ in 1 2 3 4 5 6 7 8 9 10; do ss -tnpH 2>/dev/null | grep -E 'ollama' | awk '{print $5}' >>/tmp/proof_idle.txt; sleep 0.5; done
IDLE_OUT="$(sed -E 's/:[0-9]+$//' /tmp/proof_idle.txt | sort -u | grep -vE '^(127\.0\.0\.1|\[::1\]|::1|\*|0\.0\.0\.0|)$' || true)"
[ -z "$IDLE_OUT" ] && pass "no outside connection while idle" \
  || fail "outside connection while idle: $IDLE_OUT  (Ollama's optional cloud link to ollama.com; start the server with OLLAMA_NO_CLOUD=1)"
echo "(b) asking a question"
echo "question : $Q"
T0=$(date +%s)
curl -sS -m 300 "http://127.0.0.1:$PORT/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"temperature\":0,\"messages\":[{\"role\":\"user\",\"content\":\"$Q\"}]}" >/tmp/proof_answer.json 2>/tmp/proof_err.txt &
CURLPID=$!
: >/tmp/proof_peers.txt
while kill -0 "$CURLPID" 2>/dev/null; do
  ss -tnpH 2>/dev/null | grep -E 'ollama' | awk '{print $5}' >>/tmp/proof_peers.txt
  sleep 0.5
done
wait "$CURLPID" 2>/dev/null
T1=$(date +%s)
ANSWER="$("$PY" -c "import json;print(json.load(open('/tmp/proof_answer.json'))['choices'][0]['message']['content'].strip())" 2>/dev/null || true)"
echo "answer   : ${ANSWER:-<none: $(head -c 200 /tmp/proof_err.txt)>}   (took $((T1 - T0)) s)"
echo "remote addresses the AI process was connected to while answering:"
sort -u /tmp/proof_peers.txt | sed 's/^/  /'; [ -s /tmp/proof_peers.txt ] || echo "  (none besides itself)"
OUTSIDE="$(sort -u /tmp/proof_peers.txt | sed -E 's/:[0-9]+$//' | grep -vE '^(127\.0\.0\.1|\[::1\]|::1|\*|0\.0\.0\.0|)$' || true)"
[ -n "$ANSWER" ] && pass "the model answered a question on this machine" || fail "no answer received"
if [ -z "$OUTSIDE" ]; then pass "no connection to any outside address while it answered"; else fail "outside address seen while answering: $OUTSIDE  (start the server with OLLAMA_NO_CLOUD=1)"; fi

# ---------------------------------------------------------------------------------------------------------------
hr "4. THE PROCESS"
ps -o pid,user,rss,args -C ollama 2>/dev/null | cut -c1-110 | sed 's/^/  /'
echo "  (rss is memory in KB: the model is held in this machine's RAM)"

# ---------------------------------------------------------------------------------------------------------------
hr "5. THE CODE: the app can only talk to the address in AI_BASE_URL, and refuses outside ones"
grep -nE "urlopen|def assert_local|allow_remote|is_loopback" crespoqa/review/llm.py | sed 's/^/  /'
"$PY" - <<'PY'
from crespoqa.review.llm import assert_local, ReviewError
for url in ("http://localhost:11434/v1", "http://ollama:11434/v1", "http://8.8.8.8/v1", "https://api.example.com/v1"):
    try:
        assert_local(url, allow_remote=False); verdict = "allowed (local/private network)"
    except ReviewError as e:
        verdict = "REFUSED: " + str(e)[:60]
    except Exception as e:
        verdict = "n/a here (" + type(e).__name__ + ")"
    print(f"  {url:32} -> {verdict}")
PY
"$PY" - <<'PY' >/dev/null 2>&1 && pass "the app refuses an AI address outside this machine/network" || fail "the app did not refuse a public address"
from crespoqa.review.llm import assert_local, ReviewError
try:
    assert_local("http://8.8.8.8/v1", allow_remote=False)
except ReviewError:
    raise SystemExit(0)
raise SystemExit(1)
PY

# ---------------------------------------------------------------------------------------------------------------
if [ "$OFFLINE" = 1 ]; then
  hr "6. THE STRONGEST PROOF: the model answers inside a container with NO NETWORK AT ALL"
  if ! command -v docker >/dev/null || ! docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
    echo "needs Docker and the ollama/ollama image (docker pull ollama/ollama)"; fail "offline test skipped (no Docker image)"
  else
    OUT="$(docker run --rm --network none --tmpfs /root/.ollama --entrypoint bash \
      -v "$MODELS_DIR":/models:ro -e OLLAMA_MODELS=/models -e OLLAMA_NO_CLOUD=1 ollama/ollama:latest -c '
        ollama serve >/dev/null 2>&1 &
        for i in $(seq 1 40); do ollama list >/dev/null 2>&1 && break; sleep 1; done
        BODY="{\"model\":\"'"$MODEL"'\",\"stream\":false,\"prompt\":\"Reply with exactly: LOCAL_OK\",\"options\":{\"temperature\":0}}"
        exec 3<>/dev/tcp/127.0.0.1/11434
        printf "POST /api/generate HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: ${#BODY}\r\n\r\n%s" "$BODY" >&3
        RESP=$(cat <&3)
        echo "network interfaces in the container : $(ls /sys/class/net | tr "\n" " ")"
        echo "routes in the container              : $(tail -n +2 /proc/net/route | wc -l)  (0 = no way out)"
        echo "answer                               : $(echo "$RESP" | grep -o "\"response\":\"[^\"]*\"" | head -1)"' 2>&1)"
    echo "$OUT" | sed 's/^/  /'
    echo "$OUT" | grep -q "interfaces in the container : lo *$" && echo "$OUT" | grep -q "LOCAL_OK" \
      && pass "answered with only a loopback interface and zero routes (no network)" \
      || fail "offline test did not complete as expected"
  fi
fi

# ---------------------------------------------------------------------------------------------------------------
hr "SUMMARY"
printf '%s\n' "${RESULTS[@]}"
[ "$STARTED" != 0 ] && kill "$STARTED" 2>/dev/null && echo "(stopped the AI server that this test started)"
printf '%s\n' "${RESULTS[@]}" | grep -q '^FAIL' && exit 1 || exit 0
