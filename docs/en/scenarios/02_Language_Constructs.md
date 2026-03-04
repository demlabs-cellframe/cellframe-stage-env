# Language Constructs

## Variables

### Declaration
```yaml
variables:
  amount: 1000
  wallet: WkojSeUj...
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
  save_wallet: address  # Extract wallet
  save_hash: tx_hash    # Extract hash
  save_to: raw_output   # Save raw output
```

### Regex Helpers
```yaml
# First match (string)
- set: hash
  value: regex_extract(output, r'hash:\s*(\w+)', 1)
  eval: true

# All matches (list)
- set: _keys
  value: "find_all(output, r'[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}')"
  eval: true

- set: first_key
  value: "_keys[0]"
  eval: true
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
  eval: true
  steps:
    - print: "Iteration {{i}}"
```

### loop (legacy)
```yaml
- loop: 3
  steps:
    - cli: "wallet new -w wallet{{iteration}}"
```

## Conditionals

### if-then-else
```yaml
- if: "{{balance > 0}}"
  then:
    - print: "Has balance"
  else:
    - print: "No balance"
```

### switch-case
```yaml
- switch: "{{status}}"
  cases:
    "success":
      - print: "OK"
    "error":
      - print: "Failed"
  default:
    - print: "Unknown"
```

## Groups

Groups bundle related steps under a shared label and optional defaults.
The display name can be specified with either `group:` or `name:` key:

```yaml
- group: Token Operations
  defaults:
    chain: zerochain
  steps:
    - cli: "token_decl ..."

- name: Alternative syntax
  steps:
    - print: "Both 'group' and 'name' are accepted"
```

## Defaults
```yaml
defaults:
  node: node1
  timeout: 60
  cli:
    net: stagenet
    chain: main
```
