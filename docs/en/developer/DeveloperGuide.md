# Stage-Env Developer Guide

## Installation

### Requirements
- Docker & Docker Compose
- Python 3.13+
- Git

### Setup
```bash
cd your-project/tests
git submodule add https://gitlab.demlabs.net/cellframe/cellframe-stage-env.git stage-env
cd stage-env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Project Integration

### 1. Create Test Structure
```bash
cd tests
mkdir -p scenarios/{common,features}
mkdir -p testing/{cache,artifacts}
```

### 2. Create run.sh
```bash
#!/bin/bash
cd "$(dirname "$0")"

# Link to stage-env
STAGE_ENV="stage-env/src/main.py"

case "$1" in
    --e2e)
        python3 "$STAGE_ENV" --config stage-env.cfg start --wait
        python3 "$STAGE_ENV" --config stage-env.cfg run-tests scenarios/e2e
        ;;
    --functional)
        python3 "$STAGE_ENV" --config stage-env.cfg start --wait
        python3 "$STAGE_ENV" --config stage-env.cfg run-tests scenarios/functional
        ;;
    --regression)
        python3 "$STAGE_ENV" --config stage-env.cfg start --wait
        python3 "$STAGE_ENV" --config stage-env.cfg run-tests scenarios/regression
        ;;
    *)
        echo "Usage: $0 {--e2e|--functional|--regression}"
        exit 1
        ;;
esac
```

### 3. Create clean.sh
```bash
#!/bin/bash
cd "$(dirname "$0")"

# Clean artifacts
rm -rf testing/artifacts/*
rm -rf testing/cache/*

# Stop containers
cd stage-env
docker compose -p cellframe-stage down -v --remove-orphans
```

### 4. Create Config
Configuration uses INI format (`stage-env.cfg`) with sections like `[network]`, `[topology]`, `[node_source]`:

```ini
# tests/stage-env.cfg
[network]
name = stagenet
network_id = 0x1234

[topology]
root_nodes_count = 3
master_nodes_count = 3
full_nodes_count = 2

[node_source]
type = local
local_path = ../../build/cellframe-node.deb

[paths]
project_root = ../..
cache_dir = ../../cache
artifacts_dir = ../../cache/artifacts
```

Copy from `stage-env/config/stage-env.cfg.default` as template.

## Creating Scenarios

### Minimal Scenario
```yaml
name: My Test
description: Test description

test:
  - cli: "version"
    contains: "5."
```

### With Network
```yaml
name: Network Test
description: Multi-node test

network:
  topology: default
  root_nodes: 3

test:
  - wait_network: online
    nodes: "{{all_nodes}}"
  
  - for: node
    in: "{{all_nodes}}"
    steps:
      - cli: "node dump"
        node: "{{node}}"
```

## Common Problems

### Docker Permission Denied
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Port Already in Use
```bash
# Check ports
docker compose -p cellframe-stage ps

# Clean up
docker compose -p cellframe-stage down -v
```

### Submodule Not Initialized
```bash
git submodule update --init --recursive
```

### Python Dependencies
```bash
cd stage-env
source .venv/bin/activate
pip install -r requirements.txt --upgrade
```

## Development Workflow

### 1. Write Scenario
```yaml
# scenarios/features/my_test.yml
name: My Feature Test
test:
  - cli: "my_command"
```

### 2. Run Locally
```bash
cd tests
./run.sh --e2e
```

### 3. Debug
```bash
# Check logs
tail -f testing/artifacts/run_*/logs/node-1.log

# Enter container
docker exec -it cellframe-stage-node-1 bash
```

### 4. Commit
```bash
git add scenarios/features/my_test.yml
git commit -m "test: add my feature test"
```

## CI/CD Integration

### GitLab CI
```yaml
# .gitlab-ci.yml
test:
  stage: test
  script:
    - cd tests
    - git submodule update --init
    - ./run.sh --functional
  artifacts:
    paths:
      - tests/testing/artifacts/
    reports:
      junit: tests/testing/artifacts/*/reports/junit.xml
```

### GitHub Actions
```yaml
# .github/workflows/test.yml
name: Tests
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
        with:
          submodules: true
      - name: Run tests
        run: |
          cd tests
          ./run.sh --functional
```

## Examples

### Real-World Project Structure
```
cellframe-node/
├── tests/
│   ├── run.sh
│   ├── clean.sh
│   ├── stage-env/          # Submodule
│   ├── scenarios/
│   │   ├── genesis/
│   │   ├── functional/
│   │   └── regression/
│   └── testing/
│       ├── cache/
│       └── artifacts/
```

See: https://gitlab.demlabs.net/cellframe/cellframe-node/-/tree/develop/tests
