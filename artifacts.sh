#!/bin/bash
set -euo pipefail

# Stage Environment CI wrapper
# Usage: /opt/cellframe-stage-env/artifacts.sh <path-to-cellframe-node.deb>

STAGE_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEB_PATH="$(realpath "$1")"
CI_DIR="$(pwd)"

echo "=== Stage Environment CI ==="
echo "Package: $DEB_PATH"

cd "$STAGE_ENV_DIR"

# Configure node_source to use the provided .deb
cp -f config/stage-env.cfg.default config/stage-env.cfg
sed -i "s|^type = .*|type = local|" config/stage-env.cfg
sed -i "s|^local_path = .*|local_path = $DEB_PATH|" config/stage-env.cfg

# Run: start network, wait for all nodes online, stop
rm -f .stage-env.pid
TEST_EXIT=0
./stage-env start --wait --clean <<< "y" || TEST_EXIT=$?

if [ "$TEST_EXIT" -eq 0 ]; then
    ./stage-env status || true
fi

./stage-env stop 2>/dev/null || true

# Collect artifacts
mkdir -p "$CI_DIR/test_logs"
cp -r cache/artifacts/* "$CI_DIR/test_logs/" 2>/dev/null || true
cp -r cache/logs/*      "$CI_DIR/test_logs/" 2>/dev/null || true

exit $TEST_EXIT
