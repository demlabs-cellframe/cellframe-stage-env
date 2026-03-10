#!/bin/bash
# Docker entrypoint for Cellframe Node
# Minimal wrapper that delegates to Python modules

set -e

NODE_ID=${NODE_ID:-1}
NODE_ROLE=${NODE_ROLE:-root}
NETWORK_NAME=${NETWORK_NAME:-stagenet}

echo "=== Cellframe Node Docker Entrypoint ==="
echo "Node ID: $NODE_ID"
echo "Node Role: $NODE_ROLE"
echo "Network: $NETWORK_NAME"

# Directory structure under /opt/cellframe-node/var/ is created by the .deb
# package at image build time. Only individual subdirectories are bind-mounted
# from the host (log/, lib/ca/, lib/global_db/, lib/wallet/, lib/network/),
# so directories like var/run/ and var/lib/plugins/ remain from the image.

# Enable core dumps — save to crash-artifacts mount that survives snapshot restores
ulimit -c unlimited
CRASH_DIR="/crash-artifacts/node-${NODE_ID}"
mkdir -p "$CRASH_DIR"
cd "$CRASH_DIR"

# ASAN support: if the binary was built with -fsanitize=address, configure runtime
if ldd /opt/cellframe-node/bin/cellframe-node 2>/dev/null | grep -q libasan; then
    export ASAN_OPTIONS="detect_leaks=0:halt_on_error=0:abort_on_error=0:print_stacktrace=1:detect_odr_violation=0"
    echo "ASAN enabled: $ASAN_OPTIONS"
fi

# Start cellframe-node with maximum debug level
echo "Starting cellframe-node..."
exec /opt/cellframe-node/bin/cellframe-node -D 5

