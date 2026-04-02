#!/bin/bash
# Clean up stage-env test environment
# 
# This script removes Docker-created files that may have root ownership,
# which can cause permission issues with rsync during snapshot restore.
#
# Uses Docker to remove root-owned files (no sudo required).
#
# Usage: ./clean.sh [--all]
#   --all: Also remove snapshots and logs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CACHE_DIR="$PROJECT_ROOT/cache"

echo "🧹 Cleaning stage-env test environment..."

# Stop any running containers first
echo "📦 Stopping Docker containers..."
cd "$SCRIPT_DIR"
docker compose -f docker-compose.generated.yml down --remove-orphans 2>/dev/null || true
docker compose down --remove-orphans 2>/dev/null || true

# Use Docker to remove root-owned files (no sudo needed)
echo "🗑️  Removing data directories via Docker..."

USER_ID=$(id -u)
GROUP_ID=$(id -g)

if [ "$1" = "--all" ]; then
    # Full cleanup including snapshots, logs, and artifacts
    docker run --rm \
        -v "${CACHE_DIR}:/cache" \
        alpine sh -c "
            rm -rf /cache/data /cache/configs /cache/snapshots /cache/artifacts /cache/logs /cache/certs /cache/crash-artifacts
            mkdir -p /cache/data /cache/configs /cache/logs
            chown -R ${USER_ID}:${GROUP_ID} /cache/data /cache/configs /cache/logs
        " 2>/dev/null || {
            echo "⚠️  Docker cleanup failed, trying direct removal..."
            rm -rf "${CACHE_DIR}/data" "${CACHE_DIR}/configs" \
                   "${CACHE_DIR}/snapshots" "${CACHE_DIR}/artifacts" \
                   "${CACHE_DIR}/certs" "${CACHE_DIR}/crash-artifacts" 2>/dev/null || true
        }
    echo "🗑️  Removed data, configs, snapshots, artifacts, certs, crash-artifacts, and logs"
else
    # Basic cleanup - data and configs (always needed for clean restart)
    docker run --rm \
        -v "${CACHE_DIR}:/cache" \
        alpine sh -c "
            rm -rf /cache/data /cache/configs
            mkdir -p /cache/data /cache/configs
            chown -R ${USER_ID}:${GROUP_ID} /cache/data /cache/configs
        " 2>/dev/null || {
            echo "⚠️  Docker cleanup failed, trying direct removal..."
            rm -rf "${CACHE_DIR}/data" "${CACHE_DIR}/configs" 2>/dev/null || true
        }
fi

# Remove generated docker-compose file
if [ -f "${SCRIPT_DIR}/docker-compose.generated.yml" ]; then
    rm -f "${SCRIPT_DIR}/docker-compose.generated.yml"
fi

# Remove CLI cache
if [ -d "${CACHE_DIR}/cli_cache" ]; then
    rm -rf "${CACHE_DIR}/cli_cache"
fi

# Ensure directories exist with correct permissions
echo "📁 Ensuring directories exist..."
mkdir -p "${CACHE_DIR}/data" 2>/dev/null || true
mkdir -p "${CACHE_DIR}/configs" 2>/dev/null || true
mkdir -p "${CACHE_DIR}/logs" 2>/dev/null || true

echo "✅ Cleanup complete!"
echo ""
echo "To start fresh, run:"
echo "  ./stage-env start"
