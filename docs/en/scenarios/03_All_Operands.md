# All Available Operands

## Core Operands

### cli
Execute CLI command:
```yaml
- cli: "wallet info"
  node: node1
  save_wallet: addr
  save_hash: hash
  save_to: output
  contains: "success"
  not_contains: "error"
  timeout: 30
```

### rpc
JSON-RPC call:
```yaml
- rpc: get_balance
  params:
    address: "{{addr}}"
  save: balance
```

### bash
Execute bash script:
```yaml
- bash: |
    cat /opt/cellframe-node/var/log/*.log | grep ERROR
  node: node1
  save: errors
```

### python
Execute Python code:
```yaml
- python: |
    result = ctx.get_variable('amount') * 2
    ctx.set_variable('doubled', result)
```

### print
Debug output:
```yaml
- print: "Value: {{variable}}"
```

## Wait Operands

### wait (duration)
```yaml
- wait: "5s"
```

### wait: global_db_sync
```yaml
- wait: global_db_sync
  nodes: "{{all_nodes}}"
  timeout: 60
```

### wait: block_created
```yaml
- wait: block_created
  node: "{{first_master}}"
  chain: main
  min_blocks: 1
```

### wait_for_datum
```yaml
- wait_for_datum: "{{hash}}"
  timeout_total: 300
```

### wait_network
```yaml
- wait_network: online
  nodes: "{{all_nodes}}"
  timeout: 60
```

## Control Flow

### set
```yaml
- set: var
  value: "{{expr}}"
  eval: true
```

### if
```yaml
- if: "{{condition}}"
  then: [...]
  else: [...]
```

### for
```yaml
- for: item
  in: "{{list}}"
  steps: [...]
```

### while
```yaml
- while: "{{condition}}"
  steps: [...]
  max_iterations: 10
```

### switch
```yaml
- switch: "{{value}}"
  cases:
    case1: [...]
  default: [...]
```

## Network Operations

### docker_op
```yaml
- docker_op: restart
  services: "{{nodes}}"
```

Operations: start, stop, restart, down

### config
```yaml
- config: "{{network}}/main"
  nodes: "{{all_nodes}}"
  set:
    key: value
```

### snapshot
```yaml
- snapshot: save
  name: my_snapshot
```

Operations: save, restore
