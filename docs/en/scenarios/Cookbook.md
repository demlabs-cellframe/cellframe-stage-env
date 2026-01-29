# Test Scenarios Cookbook

**Ready recipes for common Cellframe Node testing tasks**

This cookbook contains proven solutions for the most common testing tasks. Copy, adapt, and use!

## 📚 Contents

- [Wallet Operations](#wallet-operations)
- [Token Management](#token-management)
- [Transactions & Transfers](#transactions--transfers)
- [UTXO Operations](#utxo-operations)
- [Network & Consensus](#network--consensus)
- [Stress Testing](#stress-testing)
- [Error Scenarios](#error-scenarios)
- [Multi-Node Patterns](#multi-node-patterns)
- [Advanced Patterns](#advanced-patterns)

---

## Wallet Operations

### Recipe 1: Create Single Wallet

```yaml
- cli: wallet new -w my_wallet
  save: wallet_addr
  wait: 1s
```

**When to use:** For any operations requiring a wallet.

**Variables:**
- `{{wallet_addr}}` - created wallet address

---

### Recipe 2: Create Multiple Wallets

```yaml
# Modern approach with for loop
- for: i
  in: [1, 2, 3, 4, 5]
  steps:
    - cli: wallet new -w wallet{{i}}
      save: addr{{i}}
      wait: 500ms
```

**Result:**
- `wallet1`, `wallet2`, ..., `wallet5`
- `{{addr1}}`, `{{addr2}}`, ..., `{{addr5}}`

**Note:** Legacy `loop` syntax still works but `for` is recommended for new tests.

---

### Recipe 3: Conditional Execution

```yaml
variables:
  balance: 5000
  threshold: 1000

test:
  # Conditional execution with if/then/else
  - if: ctx.get_variable('balance') > ctx.get_variable('threshold')
    then:
      - cli: transfer -token TEST -value 500 -to {{receiver}}
        save: tx_hash
    else:
      - cli: balance -addr {{wallet_addr}}
        save: current_balance
```

**Variants:**
```yaml
# Check variable existence
- if: ctx.has_variable('wallet_addr')
  then:
    - cli: balance -addr {{wallet_addr}}

# Check string value
- if: ctx.get_variable('node_role') == 'validator'
  then:
    - cli: srv_stake order create validator ...
```

---

### Recipe 4: Dynamic Node Operations with For Loop

```yaml
variables:
  root_indices: [1, 2, 3]

test:
  # Get addresses from all root nodes
  - for: node_idx
    in: "{{root_indices}}"
    steps:
      - cli: node dump
        node: "node-{{node_idx}}"
        save_node: "root_addr_{{node_idx}}"
```

**Use case:** Dynamic topology scenarios (genesis initialization)

---

### Recipe 5: Config Modifications

```yaml
test:
  # Modify node configuration
  - config: "stagenet/main"
    nodes: ["node-1", "node-2"]
    set:
      validators_addrs: "{{validators_str}}"
      fee_addr: "{{fee_wallet}}"
  
  # Restart nodes to apply config
  - docker_op: restart
    services: ["node-1", "node-2"]
  
  # Wait for nodes to come online
  - wait_network: online
    nodes: ["node-1", "node-2"]
    timeout: 60
```

---

*Note: More recipes available in Russian version. See also real test scenarios in `tests/stage-env/scenarios/`.*

---

## 🎯 Usage Tips

### Combining Recipes

Recipes can be combined:

```yaml
includes:
  - common/network_minimal.yml

setup:
  # Recipe 2: Multiple wallets
  - loop: 3
    steps:
      - cli: wallet new -w wallet{{iteration}}
        save: addr{{iteration}}
  
  # Recipe 6: Create token
  - cli: token_decl -token COMBO -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
    wait: 3s
```

---

## 📚 See Also

- **[Tutorial](Tutorial.md)** - Step-by-step learning
- **[Glossary](Glossary.md)** - Complete reference
- `tests/stage-env/scenarios/features/` - Real test examples

Happy testing! 🎉

---

---

**Last updated:** 2025-12-23  
**Language:** English | [Русский](../../ru/scenarios/Cookbook.md)

---

## 🆕 Recipe 15: Debug with Print

Trace execution and inspect variables.

```yaml
name: Debug Example
description: Using print for debugging

test:
  - print: "=== Starting Test ==="
  
  - cli: "token_decl -token DEBUG -total_supply 1000000 -decimals 18 -certs stagenet.root.pvt.0"
    save_hash: token_hash
  - print: "Token created: {{token_hash}}"
  
  - cli: "mempool proc -datum {{token_hash}}"
    save_to: proc_result
  - print: "Processing result: {{proc_result}}"
  
  - for: node_id
    in: ["node1", "node2", "node3"]
    steps:
      - print: "Checking node {{node_id}}..."
      - cli: "node dump"
        node: "{{node_id}}"
        save_to: node_state
      - print: "Node {{node_id}} state: {{node_state}}"
  
  - print: "=== Test Complete ==="
```

---

## 🆕 Recipe 16: Multi-Node Sync Wait

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
  
  - print: "All nodes synced and ready!"
```

---

## 🆕 Recipe 17: Config Reload Pattern

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

## 🆕 Recipe 18: Genesis Block Creation

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

## 🆕 Recipe 19: Intelligent Datum Waiting

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

- print: "Token processed and propagated!"
```

**Benefits:**
- No wasted time (returns immediately when done)
- Fail-fast if datum rejected
- Automatic network-wide verification
- Detailed status in logs

---

## 🆕 Recipe 20: Loop with Range

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
      - print: "Wallet {{i}}: {{addr_{{i}}}}"
```

---

## 🆕 Recipe 21: Conditional Token Creation

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
      - cli: "token_decl -token MYTOKEN ..."
        save_hash: token_hash
      - wait_for_datum: "{{token_hash}}"
      - print: "Token created!"
    else:
      - print: "Token already exists, skipping."
```

---

## 🆕 Recipe 22: Python Data Processing

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

## 🆕 Recipe 23: Snapshot and Restore

Save/restore network state.

```yaml
name: Snapshot Test
description: Test with state snapshots

test:
  # Setup initial state
  - cli: "wallet new -w test_wallet"
    save_wallet: wallet_addr
  
  - cli: "token_decl -token TEST ..."
    save_hash: token_hash
  
  # Save snapshot
  - snapshot: save
    name: with_token
  
  # Do destructive test
  - cli: "token_decl -token BAD ..."  # May fail
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

*For more examples, see `scenarios/genesis/` in the repository.*
