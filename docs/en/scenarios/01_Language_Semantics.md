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

### Predefined (ScenarioGlobalContext)
Automatically available topology variables:

**Topology:**
- `{{all_nodes}}` — all nodes list
- `{{root_nodes}}` / `{{master_nodes}}` / `{{full_nodes}}` — by role
- `{{first_root}}` / `{{last_root}}` — first/last root node
- `{{first_master}}` / `{{last_master}}` — first/last master node
- `{{seed_nodes}}` / `{{validator_nodes}}` — seed/validator lists
- `{{root_indices}}` / `{{master_indices}}` / `{{full_indices}}` / `{{all_indices}}` — index lists

**Counts:**
- `{{node_count}}` / `{{root_count}}` / `{{master_count}}` / `{{full_count}}`

**Network:**
- `{{network_name}}` / `{{topology_name}}` / `{{native_ticker}}`
- `{{node_port}}` / `{{node_ip}}` / `{{node_ips}}`
- `{{node_ip_root-1}}` / `{{node_ip_master-2}}` — per-node IPs

**Per-node IPs (auto-generated):**
- `{{node_ip_full-1}}` / `{{node_ip_full-2}}` — full node IPs

**Version (auto-detected from DEB):**
- `{{cf_version}}` / `{{cf_version_major}}` / `{{cf_version_minor}}`

**Internal:**
- `{{_service_node_ids}}` — map of service name to numeric node ID
- `{{project_root}}` — absolute path to project root

**CLI parameters** (`-P KEY=VALUE`) are available as `{{KEY}}`.

## Best Practices

1. Use semantic names
2. Group related steps
3. Use `print` for debugging
4. Explicit timeouts
5. Fail-fast checks
