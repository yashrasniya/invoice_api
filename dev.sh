#!/usr/bin/env bash
#
# dev.sh — run the Django backend, the React/Vite frontend and the Expo (Metro) mobile server together.
#
#   ./dev.sh                start all three
#   ./dev.sh --backend      backend only      (flags combine: -b -m = backend + mobile)
#   ./dev.sh --frontend     frontend only
#   ./dev.sh --mobile       mobile (Metro dev-client server) only
#   ./dev.sh --migrate      apply migrations first, then start
#   ./dev.sh --clear        start Metro with a cleared cache (after changing MobileApp/.env*)
#
# Ctrl+C stops everything. If any one dies, the others are shut down too.
#
# The backend listens on 0.0.0.0 whenever mobile runs, so the phone can reach it on your LAN IP.
#
# Override defaults via env:
#   BACKEND_PORT=8000 FRONTEND_PORT=5173 MOBILE_PORT=8081 BACKEND_HOST=127.0.0.1 ./dev.sh
#
set -uo pipefail

# NOTE: deliberately *not* using `set -m`. With job control on, bash hands the
# terminal's foreground process group to each command it runs (e.g. the `sleep`
# in the wait loop below), so Ctrl+C is delivered there instead of to this
# script and the shutdown trap never runs. Without it we stay the foreground
# group, catch SIGINT ourselves, and clean up children explicitly.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKEND_DIR="$ROOT/invoice_api"
FRONTEND_DIR="$ROOT/bill_makeing_sof"
MOBILE_DIR="$ROOT/MobileApp"
VENV_PYTHON="$ROOT/venv/bin/python"

BACKEND_HOST="${BACKEND_HOST:-}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
MOBILE_PORT="${MOBILE_PORT:-8081}"

RUN_BACKEND=0
RUN_FRONTEND=0
RUN_MOBILE=0
RUN_MIGRATE=0
CLEAR_CACHE=0

C_RESET=$'\033[0m'
C_BACKEND=$'\033[36m'   # cyan
C_FRONTEND=$'\033[35m'  # magenta
C_MOBILE=$'\033[33m'    # yellow
C_INFO=$'\033[32m'      # green
C_ERR=$'\033[31m'       # red

info() { printf '%s[dev]%s %s\n' "$C_INFO" "$C_RESET" "$*"; }
fail() { printf '%s[dev]%s %s\n' "$C_ERR" "$C_RESET" "$*" >&2; exit 1; }

# ------------------------------------------------------------------ args ------
while [ $# -gt 0 ]; do
  case "$1" in
    --backend|-b)  RUN_BACKEND=1 ;;
    --frontend|-f) RUN_FRONTEND=1 ;;
    --mobile|-m)   RUN_MOBILE=1 ;;
    --migrate)     RUN_MIGRATE=1 ;;
    --clear|-c)    CLEAR_CACHE=1 ;;
    -h|--help)     sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^#\{1,\} \{0,1\}//'; exit 0 ;;
    *)             fail "unknown option: $1  (try --help)" ;;
  esac
  shift
done

# No service flag given → run everything.
if [ "$RUN_BACKEND$RUN_FRONTEND$RUN_MOBILE" = "000" ]; then
  RUN_BACKEND=1; RUN_FRONTEND=1; RUN_MOBILE=1
fi
# A phone can't reach 127.0.0.1 on this machine, so open the backend to the LAN when mobile is running.
if [ -z "$BACKEND_HOST" ]; then
  if [ "$RUN_MOBILE" = 1 ]; then BACKEND_HOST=0.0.0.0; else BACKEND_HOST=127.0.0.1; fi
fi

# -------------------------------------------------------------- preflight -----
check_port() {
  local port="$1" label="$2" pid upper
  pid="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null | head -1)"
  [ -n "$pid" ] || return 0
  upper="$(printf '%s' "$label" | tr '[:lower:]' '[:upper:]')"
  fail "port $port ($label) is already in use by PID $pid.
      Free it with:   kill $pid
      Or use another: ${upper}_PORT=$((port + 1)) ./dev.sh"
}

if [ "$RUN_BACKEND" = 1 ]; then
  [ -x "$VENV_PYTHON" ] || fail "no virtualenv python at $VENV_PYTHON
      Create it with: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
  [ -f "$BACKEND_DIR/manage.py" ] || fail "no manage.py in $BACKEND_DIR"
  check_port "$BACKEND_PORT" backend
fi

if [ "$RUN_FRONTEND" = 1 ]; then
  [ -f "$FRONTEND_DIR/package.json" ] || fail "no package.json in $FRONTEND_DIR"
  command -v npm >/dev/null 2>&1 || fail "npm not found on PATH"
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    info "node_modules missing — running npm install (one time)…"
    ( cd "$FRONTEND_DIR" && npm install ) || fail "npm install failed"
  fi
  check_port "$FRONTEND_PORT" frontend
fi

if [ "$RUN_MOBILE" = 1 ]; then
  [ -f "$MOBILE_DIR/package.json" ] || fail "no package.json in $MOBILE_DIR"
  command -v npx >/dev/null 2>&1 || fail "npx not found on PATH"
  if [ ! -d "$MOBILE_DIR/node_modules" ]; then
    info "MobileApp/node_modules missing — running npm install (one time)…"
    ( cd "$MOBILE_DIR" && npm install ) || fail "npm install failed"
  fi
  check_port "$MOBILE_PORT" mobile

  # The dev build calls whatever EXPO_PUBLIC_API_URL says (.env.local wins over .env); warn if it isn't this machine.
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
  API_URL="$(grep -h '^EXPO_PUBLIC_API_URL=' "$MOBILE_DIR/.env.local" "$MOBILE_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2-)"
  if [ -n "$LAN_IP" ] && [ -n "$API_URL" ]; then
    case "$API_URL" in
      *"$LAN_IP:$BACKEND_PORT"*) ;;
      *) printf '%s[dev]%s note: the mobile app calls %s but this machine is %s:%s — edit MobileApp/.env.local if you want it to use the local backend.\n' "$C_ERR" "$C_RESET" "$API_URL" "$LAN_IP" "$BACKEND_PORT" ;;
    esac
  fi
fi

if [ "$RUN_MIGRATE" = 1 ] && [ "$RUN_BACKEND" = 1 ]; then
  info "applying migrations…"
  ( cd "$BACKEND_DIR" && "$VENV_PYTHON" manage.py migrate ) || fail "migrate failed"
fi

# --------------------------------------------------------------- plumbing -----
BACKEND_PID=""
FRONTEND_PID=""
MOBILE_PID=""
SHUTTING_DOWN=0

alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

# Every descendant of $1, deepest first.
descendants() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do
    descendants "$child"
    printf '%s\n' "$child"
  done
}

# Signal a process and everything it spawned (Django's autoreload child, the
# node processes vite runs under). Descendants are collected before the parent
# is signalled, so nothing gets orphaned by reparenting.
signal_tree() {
  local sig="$1" pid="${2:-}" child
  alive "$pid" || return 0
  for child in $(descendants "$pid"); do
    kill "-$sig" "$child" 2>/dev/null || true
  done
  kill "-$sig" "$pid" 2>/dev/null || true
}

shutdown() {
  [ "$SHUTTING_DOWN" = 1 ] && return 0
  SHUTTING_DOWN=1
  trap - INT TERM EXIT
  printf '\n'
  info "shutting down…"

  signal_tree TERM "$MOBILE_PID"
  signal_tree TERM "$FRONTEND_PID"
  signal_tree TERM "$BACKEND_PID"

  local i
  for i in $(seq 1 25); do
    alive "$BACKEND_PID" || alive "$FRONTEND_PID" || alive "$MOBILE_PID" || break
    sleep 0.2
  done

  signal_tree KILL "$MOBILE_PID"
  signal_tree KILL "$FRONTEND_PID"
  signal_tree KILL "$BACKEND_PID"
  info "stopped."
  exit 0
}
trap shutdown INT TERM EXIT

# Tag each line so the two log streams stay tellable apart.
prefix_stream() {
  local color="$1" label="$2" line
  while IFS= read -r line; do
    printf '%s[%s]%s %s\n' "$color" "$label" "$C_RESET" "$line"
  done
  # Emit a trailing fragment that had no newline.
  [ -n "${line:-}" ] && printf '%s[%s]%s %s\n' "$color" "$label" "$C_RESET" "$line"
  return 0
}

# ------------------------------------------------------------------ start -----
# Output goes through a process substitution rather than a pipeline so that $!
# is the server itself; a pipeline's $! is its *last* stage, which would leave
# the actual server process unreachable.
if [ "$RUN_BACKEND" = 1 ]; then
  info "backend  → http://$BACKEND_HOST:$BACKEND_PORT/api/"
  (
    cd "$BACKEND_DIR" || exit 1
    export PYTHONUNBUFFERED=1
    exec "$VENV_PYTHON" manage.py runserver "$BACKEND_HOST:$BACKEND_PORT"
  ) > >(prefix_stream "$C_BACKEND" backend) 2>&1 &
  BACKEND_PID=$!
fi

if [ "$RUN_FRONTEND" = 1 ]; then
  info "frontend → http://localhost:$FRONTEND_PORT/app/"
  (
    cd "$FRONTEND_DIR" || exit 1
    exec npm run dev -- --port "$FRONTEND_PORT" --strictPort
  ) > >(prefix_stream "$C_FRONTEND" frontend) 2>&1 &
  FRONTEND_PID=$!
fi

if [ "$RUN_MOBILE" = 1 ]; then
  MOBILE_ARGS=(start --dev-client --port "$MOBILE_PORT")
  [ "$CLEAR_CACHE" = 1 ] && MOBILE_ARGS+=(--clear)
  info "mobile   → Metro on http://${LAN_IP:-<this-machine>}:$MOBILE_PORT (open the dev-build app on the phone)"
  (
    cd "$MOBILE_DIR" || exit 1
    exec npx expo "${MOBILE_ARGS[@]}"
  ) > >(prefix_stream "$C_MOBILE" mobile) 2>&1 &
  MOBILE_PID=$!
fi

alive "$BACKEND_PID" || alive "$FRONTEND_PID" || alive "$MOBILE_PID" || fail "nothing to run"
info "running — press Ctrl+C to stop"

# Wait for either side to exit, then tear down the other. (`wait -n` would be
# tidier but needs bash 4.3+; macOS ships bash 3.2.)
while :; do
  if [ -n "$BACKEND_PID" ] && ! alive "$BACKEND_PID"; then
    info "backend exited — stopping the rest"
    BACKEND_PID=""
    break
  fi
  if [ -n "$FRONTEND_PID" ] && ! alive "$FRONTEND_PID"; then
    info "frontend exited — stopping the rest"
    FRONTEND_PID=""
    break
  fi
  if [ -n "$MOBILE_PID" ] && ! alive "$MOBILE_PID"; then
    info "mobile exited — stopping the rest"
    MOBILE_PID=""
    break
  fi
  sleep 1
done
