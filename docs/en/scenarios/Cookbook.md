# Test Scenarios Cookbook

**Ready recipes for common Cellframe Node testing tasks**

> **Version:** 2.1.0  
> **Last updated:** 2026-01-29  
> **Language:** English | [Русский](../../ru/scenarios/Cookbook.md)

This cookbook contains proven solutions for the most common testing tasks. Copy, adapt, and use!

## 📚 Contents

- [Wallet Operations](#wallet-operations)
- [Token Management](#token-management)
- [Debugging & Monitoring](#debugging-monitoring)
- [Network Operations](#network-operations)
- [Advanced Patterns](#advanced-patterns)
- [Performance Tips](#performance-tips)

---

## Wallet Operations

### Recipe 1: Create Single Wallet

```yaml
- cli: "wallet new -w my_wallet"
  save_wallet: wallet_addr
```

**Variables:**
- `{{wallet_addr}}` - created wallet address

---

### Recipe 2: Create Multiple Wallets

```yaml
# Modern approach with for loop
- for: i
  in: "range(5)"
  eval: true
  steps:
    - cli: "wallet new -w wallet_{{i}}"
      save_wallet: "addr_{{i}}"
    - print: "Wallet {{i}}: {{addr_{{i}}}}"
```

**Result:**
- `wallet_0`, `wallet_1`, ..., `wallet_4`
- `{{addr_0}}`, `{{addr_1}}`, ..., `{{addr_4}}`

**Note:** Legacy `loop` syntax still works but `for` is recommended for new tests.

---

## Token Management

### Recipe 3: Create Token with Auto-Processing

```yaml
- cli: "token_decl -t NEWTOKEN -total_supply 1e+27 -decimals 18 -certs stagenet.root.pvt.0"
  save_hash: token_hash

# Automatically processes: mempool → block → propagation
- wait_for_datum: "{{token_hash}}"
  timeout_total: 120

- print: "✓ Token created and finalized!"
```

---

### Recipe 4: Token Emission

```yaml
- cli: "token_emit -t {{token_ticker}} -value 1e+24 -addr {{recipient}}"
  save_hash: emission_hash

- wait_for_datum: "{{emission_hash}}"
  timeout_total: 120
```

---

## Debugging & Monitoring

### Recipe 5: Debug with Print

Trace execution and inspect variables.

```yaml
name: Debug Example
description: Using print for debugging

test:
  - print: "=== Starting Test ==="
  
  - cli: "token_decl -t DEBUG -total_supply 1e+27 -decimals 18 -certs stagenet.root.pvt.0"
    save_hash: token_hash
  - print: "Token created: {{token_hash}}"
  
  - cli: "mempool list -chain zerochain"
    save_to: mempool_state
  - print: "Mempool state: {{mempool_state}}"
  
  - for: node_id
    in: ["node-1", "node-2", "node-3"]
    steps:
      - print: "Checking {{node_id}}..."
      - cli: "node dump"
        node: "{{node_id}}"
        save_node: node_addr
      - print: "Node {{node_id}} address: {{node_addr}}"
  
  - print: "=== Test Complete ==="
```

---

### Recipe 6: Multi-Node Sync Wait

Wait for Global DB synchronization across all nodes efficiently.

**Old Way (slow - sequential):**
```yaml
# 6 nodes × 30s = 180s maximum
- for: node
  in: "{{all_nodes}}"
  steps:
    - wait: global_db_sync
      node: "{{node}}"
      timeout: 30
```

**New Way (fast - parallel):**
```yaml
# All nodes in 60s maximum
- wait: global_db_sync
  nodes: "{{all_nodes}}"
  timeout: 60
```

**Complete Example:**
```yaml
name: Multi-Node Sync
description: Efficient parallel sync check

test:
  # Restart all nodes
  - docker_op: restart
    services: "{{_active_nodes}}"
  
  # Wait for network
  - wait_network: online
    nodes: "{{_active_nodes}}"
  
  # Wait for Global DB sync on ALL nodes (parallel!)
  - wait: global_db_sync
    nodes: "{{_active_nodes}}"
    timeout: 60
  
  - print: "✓ All nodes synced and ready!"
```

---

## Network Operations

### Recipe 7: Config Reload Pattern

Properly apply configuration changes.

**Wrong Way:**
```yaml
- config: "{{network_name}}/main"
  set:
    is_add_directly: "true"
- docker_op: restart  # ❌ Config NOT reloaded!
```

**Right Way:**
```yaml
- config: "{{network_name}}/main"
  nodes: "{{_active_nodes}}"
  set:
    is_add_directly: "true"

# Use stop + start instead of restart
- docker_op: stop
  services: "{{_active_nodes}}"

- docker_op: start
  services: "{{_active_nodes}}"
  wait_for_ip: true

- wait_network: online
  nodes: "{{_active_nodes}}"

# Config now applied!
```

**Why?**
- `docker_op: restart` signals Docker to restart container
- But node process inside doesn't reload config files from disk
- `stop` + `start` ensures clean reload

---

### Recipe 8: Genesis Block Creation

Real-world ESBocs genesis pattern.

```yaml
name: ESBocs Genesis
description: Create mainchain genesis block

test:
  # Create genesis transaction
  - cli: "tx_create -chain_emission zerochain -from_emission {{emission_hash}} -value 10.0e+54 -to_addr {{fee_addr}} -fee 5.0e+18 -cert stagenet.root.pvt.0"
    save_hash: genesis_tx
  - print: "Genesis TX: {{genesis_tx}}"
  
  # Process through mempool
  - cli: "mempool proc -datum {{genesis_tx}}"
  
  # Wait for Global DB sync
  - wait: global_db_sync
    node: "{{first_root}}"
    timeout: 60
  
  # Wait for ESBocs consensus (validators need time to sign)
  - wait: "120s"
  - print: "Waiting for block creation (ESBocs consensus)..."
  
  # Wait for block to propagate to all nodes
  - wait: global_db_sync
    nodes: "{{_active_nodes}}"
    timeout: 60
  
  # Verify block created
  - cli: "block list -chain main"
    node: "{{first_master}}"
    expect_output: "have blocks: [1-9]"
  
  - print: "✓ Genesis block created and synced!"
```

---

## Advanced Patterns

### Recipe 9: Intelligent Datum Waiting

Replace fixed waits with intelligent monitoring.

**Old Way (wasteful):**
```yaml
- cli: "token_decl ..."
  save_hash: token_hash
- wait: "3s"  # Hope it's in mempool

- cli: "mempool proc -datum {{token_hash}}"
- wait: "30s"  # Hope it's processed

- cli: "dag event last"  # Check if it worked
```

**New Way (efficient):**
```yaml
- cli: "token_decl ..."
  save_hash: token_hash

# Automatically waits for:
# 1. Datum in mempool
# 2. Inclusion in block
# 3. Propagation to network
- wait_for_datum: "{{token_hash}}"
  timeout_total: 120

- print: "✓ Token processed and propagated!"
```

**Benefits:**
- No wasted time (returns immediately when done)
- Fail-fast if datum rejected
- Automatic network-wide verification
- Detailed status in logs

---

### Recipe 10: Loop with Range

Iterate over numeric range.

```yaml
name: Create Multiple Wallets
description: Generate N wallets

variables:
  wallet_count: 5

test:
  - for: i
    in: "range({{wallet_count}})"
    eval: true
    steps:
      - cli: "wallet new -w wallet_{{i}}"
        save_wallet: "addr_{{i}}"
      
      - python: |
          i = {{i}}
          addr = ctx.get_variable(f'addr_{i}')
          print(f"Wallet {i}: {addr}")
```

---

### Recipe 11: Conditional Token Creation

Create token only if it doesn't exist.

```yaml
name: Conditional Token
description: Create token if not exists

test:
  - cli: "ledger list coins -chain zerochain"
    save_to: coin_list
  
  - if: "'MYTOKEN' not in '{{coin_list}}'"
    then:
      - print: "Token not found, creating..."
      - cli: "token_decl -t MYTOKEN -total_supply 1e+27 -decimals 18 -certs stagenet.root.pvt.0"
        save_hash: token_hash
      - wait_for_datum: "{{token_hash}}"
      - print: "✓ Token created!"
    else:
      - print: "Token already exists, skipping."
```

---

### Recipe 12: Python Data Processing

Process CLI output with Python.

```yaml
name: Parse and Analyze
description: Extract data from CLI output

test:
  - cli: "wallet list"
    save_to: wallet_list
  
  - python: |
      import re
      output = ctx.get_variable('wallet_list')
      
      # Extract all wallet addresses
      addresses = re.findall(r'(Wkoj\w+)', output)
      
      # Save for later use
      ctx.set_variable('wallet_addresses', addresses)
      ctx.set_variable('wallet_count', len(addresses))
  
  - print: "Found {{wallet_count}} wallets"
  
  - for: addr
    in: "{{wallet_addresses}}"
    steps:
      - cli: "wallet info -w {{addr}}"
        contains: "balance"
```

---

### Recipe 13: Snapshot and Restore

Save/restore network state.

```yaml
name: Snapshot Test
description: Test with state snapshots

test:
  # Setup initial state
  - cli: "wallet new -w test_wallet"
    save_wallet: wallet_addr
  
  - cli: "token_decl -t TEST -total_supply 1e+27 -decimals 18 -certs stagenet.root.pvt.0"
    save_hash: token_hash
  
  # Save snapshot
  - snapshot: save
    name: with_token
  
  # Do destructive test
  - cli: "token_decl -t BAD ..."  # May fail
    expect: any
  
  # Restore clean state
  - snapshot: restore
    name: with_token
  
  - print: "State restored, continuing..."
```

---

## Performance Tips

### 1. Use Intelligent Waiters
❌ **Bad:** `wait: "30s"`  
✅ **Good:** `wait_for_datum: "{{hash}}"`

### 2. Parallel Operations
❌ **Bad:** Sequential `for` loop for sync checks  
✅ **Good:** `wait: global_db_sync` with `nodes` list

### 3. Fail-Fast
❌ **Bad:** `expect: any` everywhere  
✅ **Good:** Explicit `expect: success` or `contains`

### 4. Reuse Variables
❌ **Bad:** Hardcoded values  
✅ **Good:** `variables` section

### 5. Group Related Steps
❌ **Bad:** Flat list of 100 steps  
✅ **Good:** Grouped with `group`

---

## Troubleshooting Guide

### "Pattern not found in output"
```yaml
# Add print to see actual output
- cli: "some command"
  save_to: output
- print: "Output was: {{output}}"
```

### "Timeout waiting for datum"
```yaml
# Check mempool first
- cli: "mempool list -chain {{chain}}"
  save_to: mempool
- print: "Mempool: {{mempool}}"

# Then check processing
- cli: "mempool proc -datum {{hash}}"
  save_to: proc_result
- print: "Proc result: {{proc_result}}"
```

### "Node not ready"
```yaml
# Don't add manual waits!
# CLI has automatic retry mechanism
- cli: "node dump"  # Retries automatically
  save_node: addr
```

### "Config not applied"
```yaml
# Use stop + start, not restart
- config: ...
- docker_op: stop
- docker_op: start
```

---

## 📚 See Also

- **[Tutorial](Tutorial.md)** - Step-by-step learning
- **[Glossary](Glossary.md)** - Complete reference
- **[Language Semantics](01_Language_Semantics.md)** - Core principles
- **[All Operands](03_All_Operands.md)** - Complete operand reference
- **[Debugging](05_Debugging_Scenarios.md)** - Debugging techniques
- **[Developer Guide](../developer/DeveloperGuide.md)** - Integration guide
- `tests/stage-env/scenarios/` - Real test examples

Happy testing! 🎉
