#!/bin/bash
# Docker entrypoint for Cellframe Node
# Runs node as a child process (NOT exec) so the kernel can write core dumps.
# PID 1 processes don't generate core dumps on Linux.
#
# NOTE: do NOT use `set -e` here — it interacts badly with `wait` + signal
# traps: when SIGTERM interrupts `wait`, the non-zero return (128+signum)
# triggers errexit BEFORE the trap handler runs, causing false exit code 1.

NODE_ID=${NODE_ID:-1}
NODE_ROLE=${NODE_ROLE:-root}
NETWORK_NAME=${NETWORK_NAME:-stagenet}

echo "=== Cellframe Node Docker Entrypoint ==="
echo "Node ID: $NODE_ID"
echo "Node Role: $NODE_ROLE"
echo "Network: $NETWORK_NAME"

ulimit -c unlimited
CRASH_DIR="/crash-artifacts/node-${NODE_ID}"
mkdir -p "$CRASH_DIR"
cd "$CRASH_DIR"

if ldd /opt/cellframe-node/bin/cellframe-node 2>/dev/null | grep -q libasan; then
    export ASAN_OPTIONS="detect_leaks=0:halt_on_error=0:abort_on_error=0:print_stacktrace=1:detect_odr_violation=0"
    echo "ASAN enabled: $ASAN_OPTIONS"
fi

cleanup() {
    if [ -n "$NODE_PID" ]; then
        kill -TERM "$NODE_PID" 2>/dev/null
        wait "$NODE_PID" 2>/dev/null
    fi
    exit 0
}
trap cleanup SIGTERM SIGINT SIGHUP SIGQUIT

echo "Starting cellframe-node..."
if [ "${DEBUG_GDB:-0}" = "1" ] && command -v gdb >/dev/null 2>&1; then
    # GDB batch mode: only `run`, no post-mortem commands.
    # In -batch mode any failing -ex command (e.g. `bt` on a dead process after
    # clean SIGTERM exit) causes immediate exit with code 1 — a false crash.
    # Crash analysis relies on core dumps processed by stage-env's gdb_helper.
    echo "Running under gdb (DEBUG_GDB=1) — core dumps enabled for crash analysis"
    gdb -batch -q \
        -ex 'set pagination off' \
        -ex 'set confirm off' \
        -ex 'handle SIGPIPE nostop noprint pass' \
        -ex 'handle SIGTERM nostop noprint pass' \
        -ex 'run -D 5' \
        /opt/cellframe-node/bin/cellframe-node &
else
    /opt/cellframe-node/bin/cellframe-node -D 5 &
fi
NODE_PID=$!
wait "$NODE_PID"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "=== NODE EXITED ABNORMALLY (exit_code=$EXIT_CODE, node_id=$NODE_ID) ==="
    if [ -f "$CRASH_DIR/core" ]; then
        CORE_SIZE=$(stat -c %s "$CRASH_DIR/core" 2>/dev/null || stat -f %z "$CRASH_DIR/core" 2>/dev/null)
        echo "Core dump saved: $CRASH_DIR/core ($CORE_SIZE bytes)"
    else
        echo "No core dump at $CRASH_DIR/core"
    fi
fi

exit $EXIT_CODE

