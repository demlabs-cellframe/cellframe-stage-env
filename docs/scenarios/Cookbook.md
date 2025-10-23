# Test Scenarios Cookbook

**Готовые рецепты для типовых задач тестирования Cellframe Node**

Эта книга рецептов содержит проверенные решения для самых частых задач тестирования. Копируйте, адаптируйте и используйте!

## 📚 Содержание

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

### Рецепт 1: Создать один кошелёк

```yaml
- cli: wallet new -w my_wallet
  save: wallet_addr
  wait: 1s
```

**Когда использовать:** Для любых операций требующих кошелёк.

**Переменные:**
- `{{wallet_addr}}` - адрес созданного кошелька

---

### Рецепт 2: Создать несколько кошельков

```yaml
- loop: 5
  steps:
    - cli: wallet new -w wallet{{iteration}}
      save: addr{{iteration}}
      wait: 500ms
```

**Результат:**
- `wallet1`, `wallet2`, ..., `wallet5`
- `{{addr1}}`, `{{addr2}}`, ..., `{{addr5}}`

**Варианты:**
```yaml
# С уникальными префиксами
- loop: 3
  steps:
    - cli: wallet new -w sender{{iteration}}
      save: sender_addr{{iteration}}

# Пакетное создание с одним wait
- loop: 10
  steps:
    - cli: wallet new -w batch_wallet{{iteration}}
      save: batch_addr{{iteration}}
- wait: 5s  # Один раз в конце
```

---

### Рецепт 3: Проверить существование кошелька

```yaml
check:
  - cli: wallet list
    contains: my_wallet
```

**Варианты:**
```yaml
# Проверить информацию о кошельке
- cli: wallet info -w my_wallet
  contains: {{wallet_addr}}

# Проверить несколько кошельков
- cli: wallet list
  contains: wallet1
- cli: wallet list
  contains: wallet2
```

---

### Рецепт 4: Экспортировать приватный ключ

```yaml
- cli: wallet export -w my_wallet
  save: private_key
  expect: success
```

**Использование:**
```yaml
- cli: wallet import -w imported_wallet -key {{private_key}}
  wait: 1s
```

---

### Рецепт 5: Удалить кошелёк

```yaml
- cli: wallet delete -w temporary_wallet
  expect: success
  wait: 1s

# Проверить что удалился
check:
  - cli: wallet list
    not_contains: temporary_wallet
```

---

## Token Management

### Рецепт 6: Создать простой токен

```yaml
- cli: token_decl -token MYTOKEN -total 1000000
  save: token_hash
  wait: 3s
```

**Параметры:**
- `-token` - имя токена (уникальное)
- `-total` - максимальный supply
- `-net` - сеть (опционально, default: stagenet)

**Переменные:**
- `{{token_hash}}` - хэш токена

---

### Рецепт 7: Создать токен с флагами

```yaml
- cli: token_decl -token BLOCK_TOKEN -total 1000000 -flags UTXO_BLOCKING_ENABLED
  save: token_hash
  wait: 3s
```

**Доступные флаги:**
- `UTXO_BLOCKING_ENABLED` - включить блокировку UTXO
- `ALL_SENDER_FROZEN` - заморозить всех отправителей
- `ALL_RECEIVER_FROZEN` - заморозить всех получателей

**Комбинация флагов:**
```yaml
- cli: token_decl -token FROZEN -total 1000000 -flags "ALL_SENDER_FROZEN,ALL_RECEIVER_FROZEN"
```

---

### Рецепт 8: Эмитировать токены

```yaml
- cli: token_emit -token MYTOKEN -value 100000 -addr {{wallet_addr}}
  save: emission_tx
  wait: 3s
```

**Важно:** Всегда добавляйте `wait: 3s` после эмиссии!

**Варианты:**
```yaml
# Эмиссия на несколько адресов
- loop: 5
  steps:
    - cli: token_emit -token DIST -value 10000 -addr {{addr{{iteration}}}}
      wait: 2s

# Массовая эмиссия
- cli: token_emit -token MASS -value 10000000 -addr {{main_wallet}}
  save: big_emission
  wait: 5s
```

---

### Рецепт 9: Получить информацию о токене

```yaml
- cli: token list
  contains: MYTOKEN

- cli: token info -token MYTOKEN
  save: token_details
  contains: {{token_hash}}
```

**Проверки:**
```yaml
check:
  # Проверить supply
  - cli: token info -token MYTOKEN
    contains: "total_supply: 1000000"
  
  # Проверить flags
  - cli: token info -token MYTOKEN
    contains: "UTXO_BLOCKING_ENABLED"
```

---

### Рецепт 10: Обновить токен

```yaml
# Добавить флаг
- cli: token_update -token MYTOKEN -set_flags ALL_SENDER_FROZEN
  wait: 3s

# Убрать флаг
- cli: token_update -token MYTOKEN -unset_flags ALL_SENDER_FROZEN
  wait: 3s

# Изменить владельца
- cli: token_update -token MYTOKEN -set_owner {{new_owner_addr}}
  wait: 3s
```

---

### Рецепт 11: Удалить токен

```yaml
- cli: token_delete -token TEMP_TOKEN
  expect: success
  wait: 3s

check:
  - cli: token list
    not_contains: TEMP_TOKEN
```

---

## Transactions & Transfers

### Рецепт 12: Простой трансфер

```yaml
- cli: transfer -token MYTOKEN -to {{recipient_addr}} -value 1000
  save: tx_hash
  expect: success
  wait: 3s
```

**Проверка:**
```yaml
check:
  - cli: balance -addr {{recipient_addr}} -token MYTOKEN
    contains: "1000"
```

---

### Рецепт 13: Трансфер с указанием отправителя

```yaml
- cli: transfer -token TEST -from {{sender_addr}} -to {{receiver_addr}} -value 500
  save: tx_hash
  wait: 3s
```

---

### Рецепт 14: Создать транзакцию из эмиссии

```yaml
setup:
  - cli: token_emit -token TEST -value 100000 -addr {{wallet_addr}}
    save: emission_tx
    wait: 3s

test:
  - cli: tx_create -token TEST -from_emission {{emission_tx}} -value 5000
    save: tx_hash
    wait: 3s
```

**Использование:**
- Создаёт UTXO из эмиссии
- Сохраняет хэш транзакции

---

### Рецепт 15: Массовая рассылка

```yaml
# Prepare recipients
setup:
  - loop: 10
    steps:
      - cli: wallet new -w recipient{{iteration}}
        save: rcpt{{iteration}}
        wait: 500ms

# Mass transfer
test:
  - loop: 10
    steps:
      - cli: transfer -token MASS -to {{rcpt{{iteration}}}} -value 1000
        wait: 2s
```

---

### Рецепт 16: Проверить историю транзакций

```yaml
- cli: tx_history -limit 100
  save: history
  contains: {{tx_hash}}

# Проверить конкретную транзакцию
- cli: tx_info -tx {{tx_hash}}
  contains: "status: success"
```

---

### Рецепт 17: Получить баланс

```yaml
- cli: balance -addr {{wallet_addr}} -token MYTOKEN
  save: current_balance
  contains: "10000"
```

**Варианты:**
```yaml
# Баланс всех токенов
- cli: balance -addr {{wallet_addr}}

# Баланс нативного токена
- cli: balance -addr {{wallet_addr}} -token CELL
```

---

## UTXO Operations

### Рецепт 18: Заблокировать UTXO

```yaml
setup:
  # Создать токен с блокировкой
  - cli: token_decl -token BLOCK -total 1000000 -flags UTXO_BLOCKING_ENABLED
    wait: 3s
  
  # Эмитировать
  - cli: token_emit -token BLOCK -value 10000 -addr {{wallet_addr}}
    save: emission
    wait: 3s
  
  # Создать UTXO
  - cli: tx_create -token BLOCK -from_emission {{emission}} -value 1000
    save: utxo_tx
    wait: 3s

test:
  # Заблокировать UTXO
  - cli: token_update -token BLOCK -utxo_blocked_add {{utxo_tx}}:0
    wait: 3s

check:
  # Попытка использовать заблокированный UTXO должна fail
  - cli: tx_create -token BLOCK -value 500
    expect: error
    contains: "UTXO is blocked"
```

---

### Рецепт 19: Разблокировать UTXO

```yaml
- cli: token_update -token BLOCK -utxo_blocked_remove {{utxo_tx}}:0
  wait: 3s

# Теперь можно использовать
- cli: tx_create -token BLOCK -value 500
  expect: success
```

---

### Рецепт 20: Тест арбитражной транзакции

```yaml
setup:
  - cli: token_decl -token ARB -total 1000000 -flags UTXO_BLOCKING_ENABLED
    wait: 3s
  - cli: token_emit -token ARB -value 10000 -addr {{wallet_addr}}
    save: emission
    wait: 3s
  - cli: tx_create -token ARB -from_emission {{emission}} -value 5000
    save: normal_tx
    wait: 3s
  - cli: token_update -token ARB -utxo_blocked_add {{normal_tx}}:0
    wait: 3s

test:
  # Арбитражная транзакция обходит блокировку
  - cli: tx_create -token ARB -value 1000 -arbitrage
    save: arb_tx
    expect: success
    wait: 3s

check:
  - cli: tx_info -tx {{arb_tx}}
    contains: "arbitrage: true"
```

---

### Рецепт 21: Список заблокированных UTXO

```yaml
- cli: token info -token BLOCK
  contains: "blocked_utxo"
  save: blocked_list
```

---

## Network & Consensus

### Рецепт 22: Проверить статус сети

```yaml
- cli: net get status -net stagenet
  expect: success
  contains: "NET_STATE_ONLINE"
```

**Варианты:**
```yaml
# Проверить конкретное состояние
check:
  - cli: net get status -net stagenet
    contains: "current: NET_STATE_ONLINE"
  
  - cli: net get status -net stagenet
    contains: "links: 3"
```

---

### Рецепт 23: Список нод в сети

```yaml
- cli: node list -net stagenet
  save: nodes_list
  expect: success

# Проверить количество нод
check:
  - cli: node list -net stagenet
    contains: "node-1"
  - cli: node list -net stagenet
    contains: "node-2"
```

---

### Рецепт 24: Информация о конкретной ноде

```yaml
- cli: node info -net stagenet -addr {{node_addr}}
  save: node_details
```

---

### Рецепт 25: Проверить синхронизацию

```yaml
test:
  # Подождать синхронизации
  - wait: 10s
  
  - cli: net get status -net stagenet
    contains: "NET_STATE_ONLINE"
  
  # Проверить на разных нодах
  - cli: net get status -net stagenet
    node: node-1
    contains: "NET_STATE_ONLINE"
  
  - cli: net get status -net stagenet
    node: node-2
    contains: "NET_STATE_ONLINE"
```

---

### Рецепт 26: Создать validator order

```yaml
- cli: srv_stake order create validator -net stagenet -value_min 1000 -value_max 10000 -tax 10 -cert pvt.stagenet.master.0 -node_addr {{validator_addr}} -H hex
  save: order_hash
  expect: success
  wait: 3s
```

**Параметры:**
- `-value_min` - минимальная ставка
- `-value_max` - максимальная ставка
- `-tax` - комиссия (%)
- `-cert` - сертификат валидатора
- `-node_addr` - адрес ноды

---

### Рецепт 27: Проверить consensus rounds

```yaml
- cli: net get status -net stagenet
  contains: "round:"
  save: round_info
```

---

## Stress Testing

### Рецепт 28: Создание множества кошельков

```yaml
variables:
  wallets_count: 100

test:
  - loop: {{wallets_count}}
    steps:
      - cli: wallet new -w stress_w{{iteration}}
        save: stress_addr{{iteration}}
        wait: 100ms
  
  # Один wait в конце
  - wait: 5s

check:
  - cli: wallet list
    contains: stress_w1
  - cli: wallet list
    contains: stress_w{{wallets_count}}
```

---

### Рецепт 29: Массовые транзакции

```yaml
setup:
  - cli: token_decl -token STRESS -total 100000000
    wait: 3s
  - cli: token_emit -token STRESS -value 100000000 -addr {{sender}}
    wait: 3s

test:
  - loop: 1000
    steps:
      - cli: transfer -token STRESS -to {{receiver}} -value {{i + 1}}
        timeout: 60
        wait: 50ms

check:
  - cli: tx_history -limit 1000
    contains: STRESS
```

---

### Рецепт 30: Стресс-тест нескольких нод

```yaml
includes:
  - common/network_full.yml

variables:
  operations_per_node: 50

test:
  # Node 1: wallet operations
  - loop: {{operations_per_node}}
    steps:
      - cli: wallet new -w n1_w{{iteration}}
        node: node-1
        wait: 100ms
  
  # Node 2: token operations
  - loop: {{operations_per_node}}
    steps:
      - cli: token_decl -token N2_T{{iteration}} -total 1000000
        node: node-2
        wait: 2s
  
  # Node 3: transfers
  - loop: {{operations_per_node}}
    steps:
      - cli: transfer -token TEST -to {{addr}} -value {{i * 100}}
        node: node-3
        wait: 100ms
```

---

### Рецепт 31: Benchmark транзакций

```yaml
name: Transaction Throughput Benchmark
description: Measure transactions per second

variables:
  total_transactions: 10000
  batch_size: 100

test:
  - loop: {{total_transactions / batch_size}}
    steps:
      - loop: {{batch_size}}
        steps:
          - cli: transfer -token BENCH -value 1 -to {{recipient}}
            wait: 10ms
      - wait: 1s  # Batch pause
```

---

## Error Scenarios

### Рецепт 32: Тест недостаточного баланса

```yaml
test:
  - cli: transfer -token TEST -value 999999999
    expect: error
    contains: "insufficient funds"
```

---

### Рецепт 33: Тест несуществующего токена

```yaml
test:
  - cli: token info -token NONEXISTENT
    expect: error
    contains: "not found"
```

---

### Рецепт 34: Тест заблокированного UTXO

```yaml
setup:
  # Block UTXO
  - cli: token_update -token BLOCK -utxo_blocked_add {{tx_hash}}:0
    wait: 3s

test:
  # Try to use blocked UTXO
  - cli: tx_create -token BLOCK -value 100
    expect: error
    contains: "UTXO is blocked"
```

---

### Рецепт 35: Тест замороженного токена

```yaml
setup:
  - cli: token_decl -token FROZEN -total 1000000 -flags ALL_SENDER_FROZEN
    wait: 3s
  - cli: token_emit -token FROZEN -value 10000 -addr {{sender}}
    wait: 3s

test:
  # Transfer should fail
  - cli: transfer -token FROZEN -to {{receiver}} -value 1000
    expect: error
    contains: "sender frozen"
```

---

### Рецепт 36: Тест невалидной транзакции

```yaml
test:
  # Invalid amount
  - cli: transfer -token TEST -value -100
    expect: error
  
  # Invalid address
  - cli: transfer -token TEST -to 0x000000 -value 100
    expect: error
```

---

### Рецепт 37: Тест таймаута

```yaml
test:
  - cli: very_long_operation
    timeout: 5
    expect: error  # Should timeout
```

---

## Multi-Node Patterns

### Рецепт 38: Распределённое создание кошельков

```yaml
includes:
  - common/network_full.yml

test:
  # Create wallets on different nodes
  - cli: wallet new -w node1_wallet
    node: node-1
    save: addr1
  
  - cli: wallet new -w node2_wallet
    node: node-2
    save: addr2
  
  - cli: wallet new -w node3_wallet
    node: node-3
    save: addr3
  
  # Wait for replication
  - wait: 5s

check:
  # Verify all wallets visible on all nodes
  - cli: wallet list
    node: node-1
    contains: node2_wallet
  
  - cli: wallet list
    node: node-2
    contains: node3_wallet
```

---

### Рецепт 39: Кросс-нодовые трансферы

```yaml
includes:
  - common/network_full.yml

setup:
  - cli: wallet new -w sender
    node: node-1
    save: sender_addr
  
  - cli: wallet new -w receiver
    node: node-2
    save: receiver_addr
  
  - cli: token_decl -token CROSS -total 1000000
    node: node-1
    wait: 3s
  
  - cli: token_emit -token CROSS -value 10000 -addr {{sender_addr}}
    node: node-1
    wait: 3s

test:
  # Transfer from node-1
  - cli: transfer -token CROSS -to {{receiver_addr}} -value 5000
    node: node-1
    wait: 3s

check:
  # Verify on node-2
  - cli: balance -addr {{receiver_addr}} -token CROSS
    node: node-2
    contains: "5000"
  
  # Verify on node-3
  - cli: balance -addr {{receiver_addr}} -token CROSS
    node: node-3
    contains: "5000"
```

---

### Рецепт 40: Репликация токенов

```yaml
includes:
  - common/network_full.yml

test:
  # Create token on node-1
  - cli: token_decl -token REPL -total 1000000
    node: node-1
    save: token_hash
    wait: 5s

check:
  # Verify token visible on all nodes
  - cli: token list
    node: node-1
    contains: REPL
  
  - cli: token list
    node: node-2
    contains: REPL
  
  - cli: token list
    node: node-3
    contains: REPL
  
  - cli: token info -token REPL
    node: node-4
    contains: {{token_hash}}
```

---

## Advanced Patterns

### Рецепт 41: Conditional Execution (через переменные)

```yaml
variables:
  run_stress_test: true
  stress_iterations: 100

test:
  # Simulated conditional via comments
  # If run_stress_test == true:
  - loop: {{stress_iterations if run_stress_test else 1}}
    steps:
      - cli: stress_operation
```

**Примечание:** Настоящие условия не поддерживаются, но можно использовать переменные для управления.

---

### Рецепт 42: Prepare-Act-Assert паттерн

```yaml
name: Prepare-Act-Assert Pattern Example

# === PREPARE ===
setup:
  - cli: wallet new -w test_wallet
    save: wallet_addr
  - cli: token_decl -token TEST -total 1000000
    wait: 3s
  - cli: token_emit -token TEST -value 10000 -addr {{wallet_addr}}
    wait: 3s

# === ACT ===
test:
  - cli: transfer -token TEST -to {{recipient}} -value 5000
    save: tx_hash
    wait: 3s

# === ASSERT ===
check:
  - cli: balance -addr {{wallet_addr}} -token TEST
    contains: "5000"
  - cli: balance -addr {{recipient}} -token TEST
    contains: "5000"
  - cli: tx_info -tx {{tx_hash}}
    contains: "status: success"
```

---

### Рецепт 43: Цепочка зависимостей

```yaml
test:
  # Step 1: Create base
  - cli: wallet new -w base
    save: base_addr
    wait: 1s
  
  # Step 2: Use base to create derived
  - cli: token_decl -token DERIVED -total 1000000 -owner {{base_addr}}
    save: derived_token
    wait: 3s
  
  # Step 3: Use derived for operation
  - cli: token_emit -token DERIVED -value 10000 -addr {{base_addr}}
    save: emission
    wait: 3s
  
  # Step 4: Use emission for transaction
  - cli: tx_create -token DERIVED -from_emission {{emission}} -value 1000
    save: final_tx
    wait: 3s

check:
  - cli: tx_info -tx {{final_tx}}
    contains: DERIVED
```

---

### Рецепт 44: Snapshot & Restore (через переменные)

```yaml
setup:
  # Take snapshot of initial state
  - cli: wallet list
    save: initial_wallets
  - cli: token list
    save: initial_tokens

test:
  # Perform operations
  - cli: wallet new -w temp
  - cli: token_decl -token TEMP -total 1000

check:
  # Compare with snapshot
  - cli: wallet list
    # Should contain initial + new
  - cli: token list
    # Should contain initial + new
```

---

### Рецепт 45: Параметризованный тест

```yaml
variables:
  # Test parameters
  token_prefix: PARAM
  wallet_prefix: param_wallet
  iterations: 10
  transfer_amount: 1000

setup:
  - loop: {{iterations}}
    steps:
      - cli: wallet new -w {{wallet_prefix}}{{iteration}}
        save: addr{{iteration}}
        wait: 500ms

test:
  - cli: token_decl -token {{token_prefix}}_TOKEN -total 1000000
    wait: 3s
  
  - loop: {{iterations}}
    steps:
      - cli: token_emit -token {{token_prefix}}_TOKEN -value {{transfer_amount}} -addr {{addr{{iteration}}}}
        wait: 2s

check:
  - loop: {{iterations}}
    steps:
      - cli: balance -addr {{addr{{iteration}}}} -token {{token_prefix}}_TOKEN
        contains: "{{transfer_amount}}"
```

---

### Рецепт 46: Teardown паттерн

```yaml
setup:
  - cli: create_temporary_resources
    save: temp_ids

test:
  - cli: use_resources {{temp_ids}}

# Cleanup (автоматический через stage-env stop --volumes)
# Или явный:
cleanup:
  - cli: delete_resource {{temp_ids}}
```

---

### Рецепт 47: Retry паттерн (через loop)

```yaml
test:
  # Try operation multiple times
  - loop: 3
    steps:
      - cli: unreliable_operation
        expect: any  # Don't fail on error
        wait: 2s
```

---

### Рецепт 48: Batch операции

```yaml
variables:
  batch_size: 100
  total_batches: 10

test:
  - loop: {{total_batches}}
    steps:
      # Process batch
      - loop: {{batch_size}}
        steps:
          - cli: operation
            wait: 10ms
      
      # Batch pause
      - wait: 1s
```

---

### Рецепт 49: Hierarchical тестирование

```yaml
name: Hierarchical Test Suite

# Level 1: Base setup
includes:
  - common/network_full.yml
  - common/wallet_setup.yml

# Level 2: Token setup
setup:
  - cli: token_decl -token HIER -total 1000000
    wait: 3s
  - cli: token_emit -token HIER -value 100000 -addr {{wallet_addr}}
    wait: 3s

# Level 3: Distributed operations
test:
  - cli: transfer -token HIER -to {{addr2}} -value 30000
    wait: 3s
  - cli: transfer -token HIER -to {{addr3}} -value 30000
    wait: 3s

# Level 4: Verification
check:
  - cli: balance -addr {{wallet_addr}} -token HIER
    contains: "40000"
  - cli: balance -addr {{addr2}} -token HIER
    contains: "30000"
  - cli: balance -addr {{addr3}} -token HIER
    contains: "30000"
```

---

### Рецепт 50: Data-driven тестирование

```yaml
variables:
  # Test data
  test_cases:
    - name: small
      amount: 100
    - name: medium
      amount: 1000
    - name: large
      amount: 10000

test:
  # Simulate data-driven via loop
  - cli: transfer -token TEST -value 100
    save: tx_small
    wait: 2s
  
  - cli: transfer -token TEST -value 1000
    save: tx_medium
    wait: 2s
  
  - cli: transfer -token TEST -value 10000
    save: tx_large
    wait: 2s

check:
  - cli: tx_info -tx {{tx_small}}
    contains: "100"
  - cli: tx_info -tx {{tx_medium}}
    contains: "1000"
  - cli: tx_info -tx {{tx_large}}
    contains: "10000"
```

---

## 🎯 Советы по использованию

### Комбинирование рецептов

Рецепты можно комбинировать:

```yaml
includes:
  - common/network_minimal.yml

setup:
  # Рецепт 2: Несколько кошельков
  - loop: 3
    steps:
      - cli: wallet new -w wallet{{iteration}}
        save: addr{{iteration}}
  
  # Рецепт 6: Создать токен
  - cli: token_decl -token COMBO -total 1000000
    wait: 3s
  
  # Рецепт 8: Эмитировать
  - cli: token_emit -token COMBO -value 90000 -addr {{addr1}}
    wait: 3s

test:
  # Рецепт 15: Массовая рассылка
  - loop: 2
    steps:
      - cli: transfer -token COMBO -to {{addr{{i+2}}}} -value 30000
        wait: 2s

check:
  # Рецепт 17: Проверить балансы
  - loop: 3
    steps:
      - cli: balance -addr {{addr{{iteration}}}} -token COMBO
        contains: "30000"
```

### Адаптация под задачу

Изменяйте параметры:

```yaml
# Базовый рецепт
- cli: wallet new -w wallet1

# Адаптированный
- cli: wallet new -w {{my_prefix}}_{{my_suffix}}
  node: {{target_node}}
  timeout: {{custom_timeout}}
```

### Документирование

Добавляйте комментарии к используемым рецептам:

```yaml
# Recipe 12: Simple Transfer
# Modified: increased wait time for slow network
- cli: transfer -token TEST -value 1000
  wait: 5s  # Original: 3s
```

---

## 📚 См. также

- **[Tutorial](Tutorial.md)** - Пошаговое обучение
- **[Glossary](Glossary.md)** - Полный справочник
- `scenarios/features/` - Реальные примеры тестов

Удачного тестирования! 🎉

