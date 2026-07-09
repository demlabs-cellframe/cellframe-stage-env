#!/bin/bash
set -euo pipefail

# Stage Environment CI wrapper
# Usage: /opt/cellframe-stage-env/artifacts.sh <path-to-cellframe-node.deb>

STAGE_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEB_PATH="$(realpath "$1")"
CI_DIR="$(pwd)"
TEST_DIR="$CI_DIR/tests/e2e"
PROJECT_ROOT="$(cd "$CI_DIR/../.." && pwd)"
WORK_DIR="${CI_DIR}/.stage-env-run"
CACHE_DIR="${WORK_DIR}/cache"
CFG="$WORK_DIR/stage-env.cfg"

cleanup() {
    trap '' INT TERM
    echo "=== Stage Environment: cleanup ==="
    # Kill direct children (python stage_env.py, etc.) without killing ourselves
    jobs -p 2>/dev/null | xargs -r kill 2>/dev/null || true
    pkill -P $$ 2>/dev/null || true
    sleep 2
    cd "$STAGE_ENV_DIR"
    timeout 30 ./stage-env --config "$CFG" stop 2>/dev/null || true
    # Docker containers create files as root; fix ownership so gitlab-runner
    # (and git clean) can remove them on the next job run.
    sudo chown -R "$(id -u):$(id -g)" "$WORK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Fix root-owned files left by Docker from previous runs.
# Prevents git clean failures when cleanup didn't run (kill -9, OOM, etc.)
sudo chown -R "$(id -u):$(id -g)" "$WORK_DIR" 2>/dev/null || true

echo "=== Stage Environment CI ==="
echo "Package:  $DEB_PATH"
echo "Tests:    $TEST_DIR"

# Prepare work config with all paths pointing to CI work dir
mkdir -p "$WORK_DIR"
mkdir -p "$(dirname "$PROJECT_ROOT/tests/stage-env.cfg")"
sed \
  -e "s|^type = .*|type = local|" \
  -e "s|^local_path = .*|local_path = $DEB_PATH|" \
  -e "s|^log_dir = .*|log_dir = $CACHE_DIR/logs|" \
  -e "s|^cache_dir = .*|cache_dir = $CACHE_DIR|" \
  -e "s|^artifacts_dir = .*|artifacts_dir = $CACHE_DIR/artifacts|" \
  -e "s|^snapshots_dir = .*|snapshots_dir = $CACHE_DIR/snapshots|" \
  "$STAGE_ENV_DIR/config/stage-env.cfg.default" > "$CFG"

# Copy to tests/stage-env.cfg
cp "$CFG" "$PROJECT_ROOT/tests/stage-env.cfg"
echo "Copied config to $PROJECT_ROOT/tests/stage-env.cfg"

cd "$STAGE_ENV_DIR"

# Start network
TEST_EXIT=0
./stage-env --config="$CFG" start --wait --clean --rebuild -y || TEST_EXIT=$?

if [ "$TEST_EXIT" -eq 0 ]; then
    ./stage-env --config="$CFG" status || true

    echo "=== Running E2E tests ==="
    ./stage-env --config "$CFG" run-tests --no-start-network --keep-running "$TEST_DIR" || TEST_EXIT=$?
fi

# Collect artifacts (always, regardless of test outcome)
mkdir -p "$CI_DIR/test_logs"
cp -r "$CACHE_DIR/artifacts"/* "$CI_DIR/test_logs/" 2>/dev/null || true
cp -r "$CACHE_DIR/logs"/*      "$CI_DIR/test_logs/" 2>/dev/null || true

exit $TEST_EXIT
