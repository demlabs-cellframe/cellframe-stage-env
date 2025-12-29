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
