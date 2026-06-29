#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

show_usage() {
  cat <<'EOF'
Usage: ./start_receiver.sh [-r] [-u] [-q] [-h]

Start the UDP receiver and USB bridge together.

Output selection:
  no option  show UDP receiver output only (same as -r)
  -r         show UDP receiver output
  -u         show USB bridge output
  -r -u      show both outputs
  -q         show neither output; overrides -r and -u
  -h         show this help

Hidden output is written to:
  log/runtime/udp_receiver.log
  log/runtime/usb_node.log
EOF
}

SHOW_UDP=false
SHOW_USB=false
QUIET=false

if [ "$#" -eq 0 ]; then
  SHOW_UDP=true
fi

while getopts ":ruqh" option; do
  case "$option" in
    r) SHOW_UDP=true ;;
    u) SHOW_USB=true ;;
    q) QUIET=true ;;
    h)
      show_usage
      exit 0
      ;;
    :)
      echo "Option -$OPTARG requires an argument." >&2
      show_usage >&2
      exit 2
      ;;
    \?)
      echo "Unknown option: -$OPTARG" >&2
      show_usage >&2
      exit 2
      ;;
  esac
done

shift $((OPTIND - 1))
if [ "$#" -ne 0 ]; then
  echo "Unexpected argument: $1" >&2
  show_usage >&2
  exit 2
fi

if "$QUIET"; then
  SHOW_UDP=false
  SHOW_USB=false
fi

LOG_DIR="$PWD/log/runtime"
mkdir -p "$LOG_DIR"
UDP_LOG="$LOG_DIR/udp_receiver.log"
USB_LOG="$LOG_DIR/usb_node.log"
: >"$UDP_LOG"
: >"$USB_LOG"

PIDS=()

cleanup() {
  trap - EXIT INT TERM
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if "$SHOW_UDP"; then
  ./start_single_udp_receiver.sh &
else
  ./start_single_udp_receiver.sh >>"$UDP_LOG" 2>&1 &
fi
UDP_PID=$!
PIDS+=("$UDP_PID")

if "$SHOW_USB"; then
  ./start_usb_bridge.sh &
else
  ./start_usb_bridge.sh >>"$USB_LOG" 2>&1 &
fi
USB_PID=$!
PIDS+=("$USB_PID")

set +e
wait -n "$UDP_PID" "$USB_PID"
STATUS=$?
set -e

exit "$STATUS"
