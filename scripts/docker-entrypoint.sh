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
    echo "=== ENTRYPOINT: received signal, cleanup started (NODE_PID=$NODE_PID) ==="
    if [ -n "$NODE_PID" ]; then
        # When running under GDB, NODE_PID is GDB's PID.
        # kill -TERM on GDB itself makes GDB interrupt `run` and quit
        # WITHOUT forwarding SIGTERM to cellframe-node.
        # Send SIGTERM directly to all cellframe-node processes.
        pkill -TERM -x cellframe-node 2>/dev/null || kill -TERM "$NODE_PID" 2>/dev/null
        wait "$NODE_PID" 2>/dev/null
    fi
    echo "=== ENTRYPOINT: cleanup finished, exiting 0 ==="
    exit 0
}
trap cleanup SIGTERM SIGINT SIGHUP SIGQUIT

# Remove stale MDBX lock files — may remain from snapshot restore or
# data cloning and prevent the database from opening.
find /opt/cellframe-node/var/lib -name "mdbx.lck" -delete 2>/dev/null

echo "Starting cellframe-node..."
if [ "${DEBUG_GDB:-0}" = "1" ] && command -v gdb >/dev/null 2>&1; then
    echo "Running under gdb (DEBUG_GDB=1) — core dumps enabled for crash analysis"
    GDB_INIT="/tmp/gdb-init-${NODE_ID}"
    cat > "$GDB_INIT" << 'GDBEOF'
set pagination off
set confirm off
handle SIGPIPE nostop noprint pass
handle SIGTERM nostop noprint pass
run -D 5
printf "\n=== GDB: inferior stopped/exited ===\n"
info inferiors
printf "\n=== CRASH BACKTRACE ===\n"
thread apply all bt full
printf "\n=== END BACKTRACE ===\n"
quit
GDBEOF
    GDB_LOG="/tmp/gdb-output-${NODE_ID}.log"
    gdb -q -x "$GDB_INIT" /opt/cellframe-node/bin/cellframe-node </dev/null 2>&1 | tee "$GDB_LOG" &
else
    /opt/cellframe-node/bin/cellframe-node -D 5 &
fi
NODE_PID=$!
echo "=== ENTRYPOINT: child started, NODE_PID=$NODE_PID, waiting... ==="
wait "$NODE_PID"
EXIT_CODE=$?

echo "=== ENTRYPOINT: wait returned, EXIT_CODE=$EXIT_CODE, NODE_PID=$NODE_PID ==="

GDB_LOG="/tmp/gdb-output-${NODE_ID}.log"
if [ -f "$GDB_LOG" ]; then
    echo "=== GDB OUTPUT (exit info) ==="
    grep -E "exited|signal|killed|stopped|Inferior|Program" "$GDB_LOG" 2>/dev/null || echo "(no exit info found)"
    echo "=== END GDB OUTPUT ==="
fi

NODE_LOG="/opt/cellframe-node/var/log/cellframe-node.log"
if [ -f "$NODE_LOG" ]; then
    echo "=== LAST 200 LINES OF NODE LOG ==="
    tail -200 "$NODE_LOG"
    echo "=== END NODE LOG ==="
fi

if [ $EXIT_CODE -ne 0 ]; then
    echo "=== NODE EXITED ABNORMALLY (exit_code=$EXIT_CODE, node_id=$NODE_ID) ==="
    if [ -f "$CRASH_DIR/core" ]; then
        CORE_SIZE=$(stat -c %s "$CRASH_DIR/core" 2>/dev/null || stat -f %z "$CRASH_DIR/core" 2>/dev/null)
        echo "Core dump saved: $CRASH_DIR/core ($CORE_SIZE bytes)"
    else
        echo "No core dump at $CRASH_DIR/core"
    fi
else
    echo "=== NODE EXITED NORMALLY (exit_code=0, node_id=$NODE_ID) — THIS IS UNEXPECTED ==="
fi

exit $EXIT_CODE

