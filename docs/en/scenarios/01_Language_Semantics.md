# Language Semantics

## Overview

Stage-Env Scenario Language is a declarative DSL (Domain-Specific Language) for blockchain testing scenarios.

## Core Principles

### 1. Declarative Nature
Describe **what** to test, not **how**:
```yaml
- wait_for_datum: "{{tx_hash}}"  # Declarative
```

### 2. Fail-Fast
Scenarios stop on first error:
```yaml
- cli: "wallet info -w missing"
  expect: success  # Fails here, stops execution
```

### 3. Template-First
All strings support Jinja2:
```yaml
- cli: "tx_create -from {{wallet}}"
```

## Variable Scope

### Global
```yaml
variables:
  network_name: stagenet
```

### Step-Level
```yaml
- cli: "wallet new"
  save_wallet: addr  # Available as {{addr}}
```

### Suite-Level (shared)
```yaml
# suite_setup.yml
suite_setup:
  variables:
    shared_var: value
```

## Best Practices

1. Use semantic names
2. Group related steps
3. Use `print` for debugging
4. Explicit timeouts
5. Fail-fast checks
