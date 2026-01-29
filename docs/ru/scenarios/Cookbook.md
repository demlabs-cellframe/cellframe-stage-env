# Test Scenarios Cookbook

**Готовые рецепты для типовых задач тестирования Cellframe Node**

> **Версия:** 2.1.0  
> **Обновлено:** 2026-01-29  
> **Язык:** Русский | [English](../../en/scenarios/Cookbook.md)

Эта книга рецептов содержит проверенные решения для самых частых задач тестирования. Копируйте, адаптируйте и используйте!

## 📚 Содержание

- [Wallet Operations](#wallet-operations)
- [Token Management](#token-management)
- [Debugging & Monitoring](#debugging--monitoring-1)
- [Network Operations](#network-operations)
- [Advanced Patterns](#advanced-patterns)
- [Performance Tips](#performance-tips)

---

## Wallet Operations

### Рецепт 1: Создать один кошелёк

```yaml
- cli: "wallet new -w my_wallet"
  save_wallet: wallet_addr
```

**Переменные:**
- `{{wallet_addr}}` - адрес созданного кошелька

---

### Рецепт 2: Создать несколько кошельков

```yaml
# Современный подход с for loop
- for: i
  in: "range(5)"
  eval: true
  steps:
    - cli: "wallet new -w wallet_{{i}}"
      save_wallet: "addr_{{i}}"
    - print: "Кошелёк {{i}}: {{addr_{{i}}}}"
```

**Результат:**
- `wallet_0`, `wallet_1`, ..., `wallet_4`
- `{{addr_0}}`, `{{addr_1}}`, ..., `{{addr_4}}`

**Примечание:** Legacy синтаксис `loop` всё ещё работает, но `for` рекомендуется для новых тестов.

---

## Token Management

### Рецепт 3: Создать токен с авто-обработкой

```yaml
- cli: "token_decl -t NEWTOKEN -total_supply 1e+27 -decimals 18 -certs stagenet.root.pvt.0"
  save_hash: token_hash

# Автоматически обрабатывает: mempool → block → propagation
- wait_for_datum: "{{token_hash}}"
  timeout_total: 120

- print: "✓ Токен создан и финализирован!"
```

---

### Рецепт 4: Эмиссия токенов

```yaml
- cli: "token_emit -t {{token_ticker}} -value 1e+24 -addr {{recipient}}"
  save_hash: emission_hash

- wait_for_datum: "{{emission_hash}}"
  timeout_total: 120
```

---

## Debugging & Monitoring

### Рецепт 5: Отладка с Print

Трассировка выполнения и инспекция переменных.

```yaml
name: Debug Example
description: Использование print для отладки

test:
  - print: "=== Начало теста ==="
  
  - cli: "token_decl -t DEBUG -total_supply 1e+27 -decimals 18 -certs stagenet.root.pvt.0"
    save_hash: token_hash
  - print: "Токен создан: {{token_hash}}"
  
  - cli: "mempool list -chain zerochain"
    save_to: mempool_state
  - print: "Состояние mempool: {{mempool_state}}"
  
  - for: node_id
    in: ["node-1", "node-2", "node-3"]
    steps:
      - print: "Проверка {{node_id}}..."
      - cli: "node dump"
        node: "{{node_id}}"
        save_node: node_addr
      - print: "Адрес {{node_id}}: {{node_addr}}"
  
  - print: "=== Тест завершён ==="
```

---

### Рецепт 6: Ожидание Multi-Node Синхронизации

Эффективное ожидание синхронизации Global DB на всех нодах.

**Старый способ (медленный - последовательный):**
```yaml
# 6 нод × 30s = 180s максимум
- for: node
  in: "{{all_nodes}}"
  steps:
    - wait: global_db_sync
      node: "{{node}}"
      timeout: 30
```

**Новый способ (быстрый - параллельный):**
```yaml
# Все ноды за 60s максимум
- wait: global_db_sync
  nodes: "{{all_nodes}}"
  timeout: 60
```

**Полный пример:**
```yaml
name: Multi-Node Sync
description: Эффективная параллельная проверка синхронизации

test:
  # Перезапуск всех нод
  - docker_op: restart
    services: "{{_active_nodes}}"
  
  # Ожидание сети
  - wait_network: online
    nodes: "{{_active_nodes}}"
  
  # Ожидание Global DB sync на ВСЕХ нодах (параллельно!)
  - wait: global_db_sync
    nodes: "{{_active_nodes}}"
    timeout: 60
  
  - print: "✓ Все ноды синхронизированы и готовы!"
```

---

## Network Operations

### Рецепт 7: Паттерн Перезагрузки Конфигурации

Правильное применение изменений конфигурации.

**Неправильный способ:**
```yaml
- config: "{{network_name}}/main"
  set:
    is_add_directly: "true"
- docker_op: restart  # ❌ Конфиг НЕ перезагружен!
```

**Правильный способ:**
```yaml
- config: "{{network_name}}/main"
  nodes: "{{_active_nodes}}"
  set:
    is_add_directly: "true"

# Используйте stop + start вместо restart
- docker_op: stop
  services: "{{_active_nodes}}"

- docker_op: start
  services: "{{_active_nodes}}"
  wait_for_ip: true

- wait_network: online
  nodes: "{{_active_nodes}}"

# Конфиг теперь применён!
```

**Почему?**
- `docker_op: restart` сигнализирует Docker о перезапуске контейнера
- Но процесс ноды внутри не перезагружает конфиг-файлы с диска
- `stop` + `start` обеспечивает чистую перезагрузку

---

### Рецепт 8: Создание Genesis Block

Реальный паттерн ESBocs genesis.

```yaml
name: ESBocs Genesis
description: Создание genesis блока mainchain

test:
  # Создать genesis транзакцию
  - cli: "tx_create -chain_emission zerochain -from_emission {{emission_hash}} -value 10.0e+54 -to_addr {{fee_addr}} -fee 5.0e+18 -cert stagenet.root.pvt.0"
    save_hash: genesis_tx
  - print: "Genesis TX: {{genesis_tx}}"
  
  # Обработать через mempool
  - cli: "mempool proc -datum {{genesis_tx}}"
  
  # Ждать Global DB sync
  - wait: global_db_sync
    node: "{{first_root}}"
    timeout: 60
  
  # Ждать ESBocs consensus (валидаторам нужно время на подпись)
  - wait: "120s"
  - print: "Ожидание создания блока (ESBocs consensus)..."
  
  # Ждать распространения блока на все ноды
  - wait: global_db_sync
    nodes: "{{_active_nodes}}"
    timeout: 60
  
  # Проверить создание блока
  - cli: "block list -chain main"
    node: "{{first_master}}"
    expect_output: "have blocks: [1-9]"
  
  - print: "✓ Genesis блок создан и синхронизирован!"
```

---

## Advanced Patterns

### Рецепт 9: Интеллектуальное Ожидание Датумов

Замените фиксированные ожидания на интеллектуальный мониторинг.

**Старый способ (расточительный):**
```yaml
- cli: "token_decl ..."
  save_hash: token_hash
- wait: "3s"  # Надеемся что попал в mempool

- cli: "mempool proc -datum {{token_hash}}"
- wait: "30s"  # Надеемся что обработался

- cli: "dag event last"  # Проверяем сработало ли
```

**Новый способ (эффективный):**
```yaml
- cli: "token_decl ..."
  save_hash: token_hash

# Автоматически ждёт:
# 1. Датум в mempool
# 2. Включение в блок
# 3. Распространение по сети
- wait_for_datum: "{{token_hash}}"
  timeout_total: 120

- print: "✓ Токен обработан и распространён!"
```

**Преимущества:**
- Нет потерянного времени (возвращается сразу после завершения)
- Fail-fast если датум отклонён
- Автоматическая проверка по всей сети
- Детальный статус в логах

---

### Рецепт 10: Цикл с Range

Итерация по числовому диапазону.

```yaml
name: Создание Нескольких Кошельков
description: Генерация N кошельков

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
          print(f"Кошелёк {i}: {addr}")
```

---

### Рецепт 11: Условное Создание Токена

Создать токен только если он не существует.

```yaml
name: Условный Токен
description: Создать токен если не существует

test:
  - cli: "ledger list coins -chain zerochain"
    save_to: coin_list
  
  - if: "'MYTOKEN' not in '{{coin_list}}'"
    then:
      - print: "Токен не найден, создаём..."
      - cli: "token_decl -t MYTOKEN -total_supply 1e+27 -decimals 18 -certs stagenet.root.pvt.0"
        save_hash: token_hash
      - wait_for_datum: "{{token_hash}}"
      - print: "✓ Токен создан!"
    else:
      - print: "Токен уже существует, пропускаем."
```

---

### Рецепт 12: Обработка Данных в Python

Обработка вывода CLI с помощью Python.

```yaml
name: Парсинг и Анализ
description: Извлечение данных из вывода CLI

test:
  - cli: "wallet list"
    save_to: wallet_list
  
  - python: |
      import re
      output = ctx.get_variable('wallet_list')
      
      # Извлечь все адреса кошельков
      addresses = re.findall(r'(Wkoj\w+)', output)
      
      # Сохранить для последующего использования
      ctx.set_variable('wallet_addresses', addresses)
      ctx.set_variable('wallet_count', len(addresses))
  
  - print: "Найдено {{wallet_count}} кошельков"
  
  - for: addr
    in: "{{wallet_addresses}}"
    steps:
      - cli: "wallet info -w {{addr}}"
        contains: "balance"
```

---

### Рецепт 13: Snapshot и Restore

Сохранение/восстановление состояния сети.

```yaml
name: Snapshot Test
description: Тестирование со снапшотами состояния

test:
  # Настроить начальное состояние
  - cli: "wallet new -w test_wallet"
    save_wallet: wallet_addr
  
  - cli: "token_decl -t TEST -total_supply 1e+27 -decimals 18 -certs stagenet.root.pvt.0"
    save_hash: token_hash
  
  # Сохранить snapshot
  - snapshot: save
    name: with_token
  
  # Провести деструктивный тест
  - cli: "token_decl -t BAD ..."  # Может упасть
    expect: any
  
  # Восстановить чистое состояние
  - snapshot: restore
    name: with_token
  
  - print: "Состояние восстановлено, продолжаем..."
```

---

## Performance Tips

### 1. Используйте Интеллектуальные Waiters
❌ **Плохо:** `wait: "30s"`  
✅ **Хорошо:** `wait_for_datum: "{{hash}}"`

### 2. Параллельные Операции
❌ **Плохо:** Последовательный `for` цикл для проверок синхронизации  
✅ **Хорошо:** `wait: global_db_sync` со списком `nodes`

### 3. Fail-Fast
❌ **Плохо:** `expect: any` везде  
✅ **Хорошо:** Явный `expect: success` или `contains`

### 4. Переиспользование Переменных
❌ **Плохо:** Хардкод значений  
✅ **Хорошо:** Секция `variables`

### 5. Группировка Связанных Шагов
❌ **Плохо:** Плоский список из 100 шагов  
✅ **Хорошо:** Группировка с `group`

---

## Troubleshooting Guide

### "Pattern not found in output"
```yaml
# Добавьте print чтобы увидеть реальный вывод
- cli: "some command"
  save_to: output
- print: "Вывод был: {{output}}"
```

### "Timeout waiting for datum"
```yaml
# Сначала проверьте mempool
- cli: "mempool list -chain {{chain}}"
  save_to: mempool
- print: "Mempool: {{mempool}}"

# Затем проверьте обработку
- cli: "mempool proc -datum {{hash}}"
  save_to: proc_result
- print: "Результат proc: {{proc_result}}"
```

### "Node not ready"
```yaml
# Не добавляйте ручные ожидания!
# CLI имеет автоматический механизм ретраев
- cli: "node dump"  # Автоматически повторяет
  save_node: addr
```

### "Config not applied"
```yaml
# Используйте stop + start, не restart
- config: ...
- docker_op: stop
- docker_op: start
```

---

## 📚 См. также

- **[Tutorial](Tutorial.md)** - Пошаговое обучение
- **[Glossary](Glossary.md)** - Полный справочник
- **[Семантика Языка](01_Language_Semantics.md)** - Основные принципы
- **[Все Операнды](03_All_Operands.md)** - Полный справочник операндов
- **[Отладка](05_Debugging_Scenarios.md)** - Техники отладки
- **[Руководство Разработчика](../developer/DeveloperGuide.md)** - Руководство по интеграции
- `tests/stage-env/scenarios/` - Реальные примеры тестов

Удачного тестирования! 🎉
