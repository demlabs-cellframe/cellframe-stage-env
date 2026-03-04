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

# Enable core dumps — they land in cwd (/opt/cellframe-node) which is bind-mounted via var/
ulimit -c unlimited
mkdir -p /opt/cellframe-node/var/coredumps
cd /opt/cellframe-node/var/coredumps

# Start cellframe-node with maximum debug level
echo "Starting cellframe-node..."
exec /opt/cellframe-node/bin/cellframe-node -D 5

