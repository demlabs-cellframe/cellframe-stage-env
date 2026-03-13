#!/bin/bash
set -euo pipefail

# Stage Environment CI wrapper
# Usage: /opt/cellframe-stage-env/artifacts.sh <path-to-cellframe-node.deb>

STAGE_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEB_PATH="$(realpath "$1")"
CI_DIR="$(pwd)"
WORK_DIR="${CI_DIR}/.stage-env-run"
CACHE_DIR="${WORK_DIR}/cache"
CFG="$WORK_DIR/stage-env.cfg"

cleanup() {
    echo "=== Stage Environment: cleanup ==="
    cd "$STAGE_ENV_DIR"
    ./stage-env --config "$CFG" stop 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Stage Environment CI ==="
echo "Package: $DEB_PATH"

# Prepare writable work config with all paths pointing to CI work dir
mkdir -p "$WORK_DIR"
sed \
  -e "s|^type = .*|type = local|" \
  -e "s|^local_path = .*|local_path = $DEB_PATH|" \
  -e "s|^log_dir = .*|log_dir = $CACHE_DIR/logs|" \
  -e "s|^cache_dir = .*|cache_dir = $CACHE_DIR|" \
  -e "s|^artifacts_dir = .*|artifacts_dir = $CACHE_DIR/artifacts|" \
  -e "s|^snapshots_dir = .*|snapshots_dir = $CACHE_DIR/snapshots|" \
  "$STAGE_ENV_DIR/config/stage-env.cfg.default" > "$CFG"

cd "$STAGE_ENV_DIR"

# Run
TEST_EXIT=0
./stage-env --config "$CFG" start --wait --clean -y || TEST_EXIT=$?

if [ "$TEST_EXIT" -eq 0 ]; then
    ./stage-env --config "$CFG" status || true
fi

# Collect artifacts
mkdir -p "$CI_DIR/test_logs"
cp -r "$CACHE_DIR/artifacts"/* "$CI_DIR/test_logs/" 2>/dev/null || true
cp -r "$CACHE_DIR/logs"/*      "$CI_DIR/test_logs/" 2>/dev/null || true

exit $TEST_EXIT
