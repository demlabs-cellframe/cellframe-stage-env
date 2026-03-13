#!/bin/bash
set -euo pipefail

# Stage Environment CI wrapper
# Usage: /opt/cellframe-stage-env/artifacts.sh <path-to-cellframe-node.deb>

STAGE_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEB_PATH="$(realpath "$1")"
CI_DIR="$(pwd)"
WORK_DIR="${CI_DIR}/.stage-env-run"

echo "=== Stage Environment CI ==="
echo "Package: $DEB_PATH"

# Prepare a writable work config (never touch /opt/)
mkdir -p "$WORK_DIR"
sed \
  -e "s|^type = .*|type = local|" \
  -e "s|^local_path = .*|local_path = $DEB_PATH|" \
  "$STAGE_ENV_DIR/config/stage-env.cfg.default" > "$WORK_DIR/stage-env.cfg"

cd "$STAGE_ENV_DIR"
rm -f .stage-env.pid

# Run
TEST_EXIT=0
./stage-env --config "$WORK_DIR/stage-env.cfg" start --wait || TEST_EXIT=$?

if [ "$TEST_EXIT" -eq 0 ]; then
    ./stage-env --config "$WORK_DIR/stage-env.cfg" status || true
fi

./stage-env --config "$WORK_DIR/stage-env.cfg" stop 2>/dev/null || true

# Collect artifacts
mkdir -p "$CI_DIR/test_logs"
cp -r cache/artifacts/* "$CI_DIR/test_logs/" 2>/dev/null || true
cp -r cache/logs/*      "$CI_DIR/test_logs/" 2>/dev/null || true

exit $TEST_EXIT
