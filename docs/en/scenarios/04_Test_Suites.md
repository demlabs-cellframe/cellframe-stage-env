# Test Suites

## Suite Structure

```yaml
# suite_setup.yml
suite_name: Token Tests
suite_description: Comprehensive token testing

suite_setup:
  variables:
    network_name: stagenet
    native_ticker: TCELL
    
  steps:
    - cli: "wallet new -w shared_wallet"
      save_wallet: suite_wallet
    # Available in all scenarios

scenarios:
  - token/001_token_decl.yml
  - token/002_token_emit.yml
```

## Suite Variables

### Definition
```yaml
suite_setup:
  variables:
    shared_var: value
```

### Usage in Scenarios
```yaml
# Any scenario in suite
test:
  - cli: "wallet info -w {{suite_wallet}}"
```

## Suite Lifecycle

1. Parse suite_setup.yml
2. Execute suite_setup steps
3. Save suite variables
4. For each scenario:
   - Load scenario
   - Merge suite variables
   - Execute scenario
   - Collect results
5. Generate suite report

## Suite Configuration

### Network Topology
```yaml
suite_setup:
  network:
    topology: custom
    root_nodes: 3
    master_nodes: 3
```

### Packages
```yaml
suite_setup:
  packages:
    - name: vim
      nodes: all
```

### Files
```yaml
suite_setup:
  files:
    - src: config.txt
      dst: /opt/config.txt
      nodes: all
```

## Best Practices

1. Share common setup in suite
2. Use suite variables for shared data
3. Keep scenarios independent
4. Use meaningful suite names
