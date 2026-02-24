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
```yaml
- group: Token Operations
  defaults:
    chain: zerochain
  steps:
    - cli: "token_decl ..."
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
