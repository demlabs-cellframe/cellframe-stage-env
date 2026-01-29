# All Available Operands

Complete reference of all operands verified against source code.

## Core Operands

### cli
Execute CLI command with comprehensive extraction options.

**Fields:**
```yaml
- cli: "command"              # Required: CLI command
  node: node1                 # Target node (default: node1)
  save: var                   # Save full output
  save_hash: hash_var         # Extract 0x[hex] hash
  save_wallet: wallet_var     # Extract and validate wallet address
  save_node: node_var         # Extract node address (0x::format)
  save_token: token_var       # Extract token ticker
  save_to: output_var         # Save raw output
  contains: "success"         # Expected substring
  not_contains: "error"       # Unexpected substring
  expect: success             # success | error | any
  wait: "5s"                  # Wait after command
  timeout: 30                 # Command timeout (default: 30s)
```

### rpc
JSON-RPC call.

```yaml
- rpc: method_name
  params: [arg1, arg2]        # RPC parameters
  node: node1                 # Target node
  save: result_var            # Save result
  wait: "1s"                  # Wait after
  expect: success             # Expected result
```

### bash
Execute bash script in container.

```yaml
- bash: |
    cat /path/to/log | grep ERROR
  node: node1
  save: errors
  expect: success
  timeout: 30
```

### python
Execute Python with context access.

**API:**
- `ctx.get_variable(name)` - get variable
- `ctx.set_variable(name, value)` - set variable  
- `ctx.has_variable(name)` - check existence
- `ctx.variables` - dict of all variables

```yaml
- python: |
    val = ctx.get_variable('amount')
    result = val * 2
    ctx.set_variable('doubled', result)
```

### print
Debug output with Jinja2 templating.

```yaml
- print: "Value: {{variable}}"
```

## Wait Operands

### wait (duration)
Simple time-based wait.

```yaml
- wait: "5s"   # 5 seconds
- wait: "500ms" # 500 milliseconds
```

### wait: global_db_sync
Wait for Global DB synchronization.

**Single node:**
```yaml
- wait: global_db_sync
  node: "{{first_root}}"
  timeout: 60
```

**Multiple nodes (parallel check):**
```yaml
- wait: global_db_sync
  nodes: "{{all_nodes}}"
  timeout: 60
```

### wait: block_created
Wait for block(s) on chain.

```yaml
- wait: block_created
  node: "{{first_master}}"
  chain: main
  network: stagenet
  min_blocks: 1
  timeout: 120
```

**Note:** Currently disabled due to MDBX SDK bug.

### wait: cli_ready
Wait for CLI to be ready (automatic in CLI steps).

```yaml
- wait: cli_ready
  node: node1
  timeout: 30
```

### wait: wallet_balance
Wait for wallet balance condition.

```yaml
- wait: wallet_balance
  wallet: my_wallet
  token: TCELL
  balance: "> 1000"
  timeout: 60
```

### All Registered Waiters

From WaitRegistry (28 total):
- `network_online` - Network state online
- `sync_complete` - Network sync complete
- `dag_event` - DAG event processing
- `esbocs_active` - ESBocs consensus active
- `first_block` - First block created
- `ledger_tx` - Transaction in ledger
- `utxo_indexed` - UTXO indexation complete
- `chain_data_propagation` - Chain data propagated
- `network_sync` - Network synchronized
- `token_in_mempool` - Token in mempool
- `datum_in_mempool` - Datum in mempool
- `datum_in_chain` - Datum in chain
- `emission_synced` - Emission synced
- `master_containers_running` - Master containers running
- `emission_in_ledger` - Emission in ledger
- `transaction_processed` - Transaction processed
- `gdb_sync_complete` - GDB sync complete
- `global_db_sync` - Global DB node list sync (**NEW**)
- `delegations_synced` - Delegations synced
- `cli_ready` - CLI ready
- `wallet_balance` - Wallet balance condition
- `block_created` - Block(s) created (**NEW**)
- `validator_mode_active` - Validator mode active
- `stake_service_ready` - Stake service ready
- `esbocs_consensus_active` - ESBocs consensus active
- `node_list_propagation` - Node list propagated
- `gdb_clusters_ready` - GDB clusters ready

### wait_for_datum
Monitor datum lifecycle (mempool → block → propagation).

```yaml
# Minimal (recommended)
- wait_for_datum: "{{tx_hash}}"

# Multiple datums
- wait_for_datum:
    - "{{hash1}}"
    - "{{hash2}}"

# All options
- wait_for_datum: "{{tx_hash}}"
  node: node1
  network: stagenet
  chain: main
  check_master_nodes: true
  timeout_total: 300
  timeout_verification: 120
  timeout_in_blocks: 180
  check_interval: 2
  save_status: datum_status
```

### wait_network
Wait for network state.

**States:** online, offline, links_connecting, links_established, sync_complete

```yaml
- wait_network: online
  nodes: "{{all_nodes}}"
  timeout: 120
  network: stagenet
```

## Control Flow

### set
Set/compute variable.

```yaml
- set: var_name
  value: "{{expression}}"
  eval: true  # Evaluate as Python
```

### if
Conditional execution.

```yaml
- if: "{{condition}}"
  then:
    - step1
    - step2
  else:
    - step3
```

### for
Iterate over list.

```yaml
- for: item
  in: "{{list_var}}"
  steps:
    - print: "{{item}}"

# With range
- for: i
  in: "range(5)"
  eval: true
  steps:
    - print: "Iteration {{i}}"
```

### while
Loop while condition true.

```yaml
- while: "{{condition}}"
  max_iterations: 10
  steps:
    - cli: "check something"
```

### switch
Switch-case.

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

### loop (legacy)
Simple counter loop.

```yaml
- loop: 3
  steps:
    - cli: "wallet new -w wallet{{iteration}}"
```

### group
Group steps with defaults.

```yaml
- group: Group Name
  defaults:
    node: node1
    timeout: 60
  steps:
    - cli: "command1"
    - cli: "command2"
```

## Network Operations

### docker_op
Docker operations.

**Operations:** start, stop, restart, down

```yaml
- docker_op: restart
  services: "{{nodes}}"
  wait_for_ip: true  # For start/restart
```

### config
Modify node configuration.

```yaml
- config: "{{network}}/chain"
  nodes: "{{all_nodes}}"
  set:
    key: value
    another_key: "true"
```

**Important:** Use `stop` + `start` after config, not `restart`!

### snapshot
Save/restore network state.

```yaml
- snapshot: save
  name: snapshot_name

- snapshot: restore
  name: snapshot_name
```

## Special Steps

### StepGroup
Group with metadata.

```yaml
- group: Group Name
  description: Optional description
  defaults:
    node: node1
  steps:
    - cli: "command"
```

### StepDefaults
Default parameters for section.

```yaml
defaults:
  node: node1
  timeout: 60
  cli:
    net: stagenet
    chain: main
```

Applied in order:
1. Global defaults (top-level)
2. Section defaults (setup/test)
3. Group defaults
4. Step-level overrides
