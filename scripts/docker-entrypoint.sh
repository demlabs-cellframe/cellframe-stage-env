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

# Ensure directories exist
mkdir -p /opt/cellframe-node/var/log
mkdir -p /opt/cellframe-node/var/run

# Start cellframe-node
echo "Starting cellframe-node..."
exec /opt/cellframe-node/bin/cellframe-node -D 4

