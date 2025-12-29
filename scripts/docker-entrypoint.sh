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

# Ensure all required directories exist
mkdir -p /opt/cellframe-node/var/log
mkdir -p /opt/cellframe-node/var/run
mkdir -p /opt/cellframe-node/var/lib
mkdir -p /opt/cellframe-node/var/lib/wallet
mkdir -p /opt/cellframe-node/var/lib/global_db
mkdir -p /opt/cellframe-node/var/lib/ca

# WORKAROUND для MDBX bug (mdbx:18610: dbi_update: Assertion failed)
# Удаляем БД только при первом старте контейнера
MDBX_CLEAN_FLAG="/opt/cellframe-node/var/.mdbx_cleaned"
if [ ! -f "$MDBX_CLEAN_FLAG" ]; then
    echo "First start: cleaning MDBX database (workaround for mdbx:18610 assertion failure)..."
    rm -rf /opt/cellframe-node/var/lib/global_db/gdb-mdbx/* 2>/dev/null || true
    touch "$MDBX_CLEAN_FLAG"
else
    echo "MDBX database already cleaned on first start, keeping data for restart"
fi

# Fix permissions for mounted volumes
chmod -R 755 /opt/cellframe-node/var 2>/dev/null || true

# Start cellframe-node with maximum debug level
echo "Starting cellframe-node..."
exec /opt/cellframe-node/bin/cellframe-node -D 5

