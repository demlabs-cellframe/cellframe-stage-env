# Debugging Scenarios

## Print Operand

### Basic
```yaml
- print: "Starting test"
```

### With Variables
```yaml
- cli: "wallet new"
  save_wallet: addr
- print: "Created wallet: {{addr}}"
```

### Complex Data
```yaml
- python: |
    data = {"key": "value"}
    ctx.set_variable('result', data)
- print: "Result: {{result}}"
```

## Logging Levels

Set in environment:
```bash
export STAGE_ENV_LOG_LEVEL=DEBUG
./stage-env start
```

## Common Issues

### 1. Template Not Substituted
```yaml
# BAD: quotes prevent substitution
- cli: '{{command}}'

# GOOD
- cli: "{{command}}"
```

### 2. Variable Not Found
```yaml
# Check variable exists
- if: "{{var|default('missing')}} == 'missing'"
  then:
    - print: "Variable not set!"
```

### 3. CLI Not Ready
```yaml
# OLD: manual wait
- wait: "5s"

# NEW: automatic retry
- cli: "node dump"
  # Retries automatically
```

## Artifacts

Logs collected in:
```
tests/testing/artifacts/run_YYYYMMDD_HHMMSS/
├── logs/
│   ├── cellframe-stage-node-1.log
│   └── ...
└── reports/
    └── report.md
```

## Interactive Debugging

```bash
# Enter node container
docker exec -it cellframe-stage-node-1 bash

# Check logs
tail -f /opt/cellframe-node/var/log/cellframe-node.log

# Run CLI manually
cellframe-node-cli wallet list
```
