#!/usr/bin/env bash
# SyncFlow security suite - one-command runner.
#
# Starts two fresh backend instances (A: TCP 19974 / WS 18993,
# B: TCP 19975 / WS 18995), runs all six suites against them, prints a
# PASS/FAIL summary and tears everything down. Exit code 0 = all green.
#
# Usage:  ./run_all.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(dirname "$HERE")"
PY="$BACKEND/venv/bin/python3"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi
ART=/tmp/opencode
mkdir -p "$ART"

echo "=== SyncFlow security suite ==="
echo "python: $PY"

# --- free our test ports (numeric pids only; never pattern-kill) -------
for port in 19974 19975 19976 18993 18995 19977; do
  pids=$(ss -ltnp 2>/dev/null | grep -P "[:.]$port\b" | grep -oP 'pid=\K[0-9]+' | sort -u)
  for pid in $pids; do
    kill "$pid" 2>/dev/null
  done
done
sleep 1

# --- fresh state ------------------------------------------------------
rm -rf "$ART/sfA" "$ART/sfB" "$ART/sfT" "$ART/sfOTHER" "$ART/sfM" "$ART/sfATK" "$ART/sfPin" "$ART/sfPinOther"
rm -rf "$HOME/Downloads/SyncFlow-testA" "$HOME/Downloads/SyncFlow-testB"

# --- start instances --------------------------------------------------
env SYNCFLOW_HOME="$ART/sfA" SYNCFLOW_TCP_PORT=19974 SYNCFLOW_WS_PORT=18993 \
  "$PY" -u "$BACKEND/main.py" >"$ART/A.log" 2>&1 &
APID=$!
env SYNCFLOW_HOME="$ART/sfB" SYNCFLOW_TCP_PORT=19975 SYNCFLOW_WS_PORT=18995 \
  "$PY" -u "$BACKEND/main.py" >"$ART/B.log" 2>&1 &
BPID=$!

cleanup() {
  kill "$APID" "$BPID" 2>/dev/null
  wait "$APID" "$BPID" 2>/dev/null
}
trap cleanup EXIT

ready=0
for _ in $(seq 1 60); do
  if ss -ltn 2>/dev/null | grep -q ":19974" \
     && ss -ltn 2>/dev/null | grep -q ":19975" \
     && ss -ltn 2>/dev/null | grep -q ":18993"; then
    ready=1
    break
  fi
  if ! kill -0 "$APID" 2>/dev/null; then
    echo "FATAL: instance A died during startup:"
    cat "$ART/A.log"
    exit 1
  fi
  sleep 0.5
done
if [ "$ready" -ne 1 ]; then
  echo "FATAL: instances did not open their ports"
  cat "$ART/A.log" "$ART/B.log"
  exit 1
fi
sleep 4  # let mDNS register/browse settle

TOTAL_PASS=0
TOTAL_FAIL=0

run_suite() {
  local label="$1"; shift
  echo ""
  echo "########## $label ##########"
  "$PY" -u "$@" 2>&1 | tee "$ART/$label.out"
  local p f
  p=$(grep -c '^PASS ' "$ART/$label.out")
  f=$(grep -c '^FAIL ' "$ART/$label.out")
  TOTAL_PASS=$((TOTAL_PASS + p))
  TOTAL_FAIL=$((TOTAL_FAIL + f))
}

run_suite t_net        "$HERE/t_net.py" "$APID"
run_suite t_proto      "$HERE/t_proto.py"
run_suite mitm2        "$HERE/mitm2.py"
run_suite t_ws         "$HERE/t_ws.py"
run_suite t_mdns_rogue "$HERE/t_mdns_rogue.py"
run_suite t_extra      "$HERE/t_extra.py"

echo ""
echo "======================================"
echo "TOTAL PASS: $TOTAL_PASS   TOTAL FAIL: $TOTAL_FAIL"
if [ "$TOTAL_FAIL" -eq 0 ] && [ "$TOTAL_PASS" -gt 0 ]; then
  echo "ALL GREEN"
  exit 0
fi
echo "FAILURES PRESENT"
exit 1
