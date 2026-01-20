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
TESTING_DIR="${SCRIPT_DIR}/../testing"

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
        -v "${TESTING_DIR}:/testing" \
        alpine sh -c "
            rm -rf /testing/cache/data /testing/cache/configs /testing/snapshots /testing/artifacts /testing/logs
            mkdir -p /testing/cache/data /testing/cache/configs /testing/logs
            chown -R ${USER_ID}:${GROUP_ID} /testing/cache/data /testing/cache/configs /testing/logs
        " 2>/dev/null || {
            echo "⚠️  Docker cleanup failed, trying direct removal..."
            rm -rf "${TESTING_DIR}/cache/data" "${TESTING_DIR}/cache/configs" \
                   "${TESTING_DIR}/snapshots" "${TESTING_DIR}/artifacts" 2>/dev/null || true
        }
    echo "🗑️  Removed data, configs, snapshots, artifacts, and logs"
else
    # Basic cleanup - data and configs (always needed for clean restart)
    docker run --rm \
        -v "${TESTING_DIR}:/testing" \
        alpine sh -c "
            rm -rf /testing/cache/data /testing/cache/configs
            mkdir -p /testing/cache/data /testing/cache/configs
            chown -R ${USER_ID}:${GROUP_ID} /testing/cache/data /testing/cache/configs
        " 2>/dev/null || {
            echo "⚠️  Docker cleanup failed, trying direct removal..."
            rm -rf "${TESTING_DIR}/cache/data" "${TESTING_DIR}/cache/configs" 2>/dev/null || true
        }
fi

# Remove generated docker-compose file
if [ -f "${SCRIPT_DIR}/docker-compose.generated.yml" ]; then
    rm -f "${SCRIPT_DIR}/docker-compose.generated.yml"
fi

# Remove CLI cache
if [ -d "${TESTING_DIR}/cache/cli_cache" ]; then
    rm -rf "${TESTING_DIR}/cache/cli_cache"
fi

# Ensure directories exist with correct permissions
echo "📁 Ensuring directories exist..."
mkdir -p "${TESTING_DIR}/cache/data" 2>/dev/null || true
mkdir -p "${TESTING_DIR}/cache/configs" 2>/dev/null || true
mkdir -p "${TESTING_DIR}/logs" 2>/dev/null || true

echo "✅ Cleanup complete!"
echo ""
echo "To start fresh, run:"
echo "  ./stage-env start"
