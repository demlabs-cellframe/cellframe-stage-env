# Language Constructs

## Variables

### Declaration
```yaml
variables:
  amount: 1000
  wallet: WkojSeUj...
  items: [1, 2, 3]
```

### Assignment (set)
```yaml
- set: total
  value: "{{amount1 + amount2}}"
  eval: true
```

### Extraction (CLI)
```yaml
- cli: "wallet new"
  save_wallet: address  # Extract wallet address
  save_hash: tx_hash    # Extract 0x[hex] hash
  save_token: ticker    # Extract token ticker
  save_node: node_addr  # Extract node address
  save_to: raw_output   # Save raw output
```

### Variable Access
```yaml
# In YAML (Jinja2)
- cli: "wallet info -w {{wallet}}"

# In Python
- python: |
    val = ctx.get_variable('wallet')
    ctx.set_variable('new_var', val + '_suffix')
```

## Loops

### for loop
```yaml
- for: item
  in: ["a", "b", "c"]
  steps:
    - print: "Item: {{item}}"
```

### for with range
```yaml
- for: i
  in: "range(3)"
  steps:
    - print: "Iteration {{i}}"
```

**Note:** String `in` values are automatically evaluated as Python expressions. No `eval: true` is needed (unlike `set` steps).

### for over variables
```yaml
- set: nodes
  value: ["node1", "node2", "node3"]
  
- for: node
  in: "{{nodes}}"
  steps:
    - cli: "node dump"
      node: "{{node}}"
```

### loop (legacy)
```yaml
- loop: 3
  steps:
    - cli: "wallet new -w wallet{{iteration}}"
```

**Note:** `loop` is kept for backward compatibility. Prefer `for` in new code.

### while loop
```yaml
- while: "{{ctx.get_variable('count', 0) < 10}}"
  max_loops: 100
  steps:
    - cli: "check status"
      save_to: status
    - set: count
      value: "{{count + 1}}"
      eval: true
```

## Conditionals

### if-then-else
```yaml
- if: "{{balance > 0}}"
  then:
    - print: "Has balance: {{balance}}"
  else:
    - print: "No balance"
```

### if with ctx
```yaml
- if: "ctx.has_variable('wallet')"
  then:
    - cli: "wallet info -w {{wallet}}"
```

### switch-case
```yaml
- switch: "{{status}}"
  cases:
    "success":
      - print: "Operation succeeded"
    "pending":
      - wait: "5s"
      - cli: "check again"
    "error":
      - print: "Operation failed"
  default:
    - print: "Unknown status: {{status}}"
```

## Groups

Groups bundle related steps under a shared label and optional defaults.
The display name can be specified with either `group:` or `name:` key:

### Basic Group
```yaml
- group: Token Operations
  steps:
    - cli: "token_decl ..."
    - cli: "token_emit ..."

- name: Alternative syntax
  steps:
    - print: "Both 'group' and 'name' are accepted"
```

### Group with Defaults
```yaml
- group: Zerochain Setup
  defaults:
    chain: zerochain
    network: stagenet
  steps:
    - cli: "token_decl -t NEWTOKEN"
```

### Nested Groups
```yaml
- group: Outer
  defaults:
    timeout: 60
  steps:
    - group: Inner
      defaults:
        node: node1
      steps:
        - cli: "command"
          # timeout=60, node=node1
```

## Defaults

### Global Defaults
```yaml
defaults:
  node: node1
  timeout: 60
  cli:
    net: stagenet
    chain: main
    token: TCELL
```

### Section Defaults
```yaml
setup:
  defaults:
    timeout: 120
  steps:
    - cli: "slow command"

test:
  defaults:
    timeout: 30
  steps:
    - cli: "fast command"
```

### Priority Order
1. Global defaults (top level)
2. Section defaults (setup/test)
3. Group defaults
4. Step-level parameters (highest priority)

```yaml
defaults:
  timeout: 60        # Priority 1

test:
  defaults:
    timeout: 30      # Priority 2
  steps:
    - group: G1
      defaults:
        timeout: 10  # Priority 3
      steps:
        - cli: "cmd"
          timeout: 5 # Priority 4 (used)
```

## Helper Functions for set

### join_vars
```yaml
- set: addrs_list
  value: join_vars('addr_', 3, ',')
  eval: true
  # Result: "val0,val1,val2"
```

### regex_extract
Extract first match (single group): `regex_extract(text, pattern, group=1) -> str`
```yaml
- set: hash
  value: regex_extract(output, r'hash:\s*(\w+)', 1)
  eval: true
```

### find_all
Return all matches: `find_all(text, pattern) -> list`
```yaml
- set: _serials
  value: "find_all(raw_output, r'[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}')"
  eval: true

- set: first_serial
  value: "_serials[0]"
  eval: true
```

### concat
```yaml
- set: full_name
  value: concat(first_name, ' ', last_name)
  eval: true
```

### get_var
```yaml
- set: dynamic
  value: get_var('addr_' + str(i), 'default')
  eval: true
```

## Special Variables

### iteration
Available in `loop`:
```yaml
- loop: 3
  steps:
    - print: "Iteration: {{iteration}}"
```

### item/i/key/value
Available in `for`:
```yaml
- for: item
  in: [1, 2, 3]
  steps:
    - print: "{{item}}"
```
