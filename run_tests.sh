#!/usr/bin/env bash
# Wrapper для tests/run_tests.sh
cd "$(dirname "$0")/tests" && ./run_tests.sh "$@"
