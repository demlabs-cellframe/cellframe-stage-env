# Все Доступные Операнды

Полный справочник всех операндов, проверенный по исходному коду.

## Основные Операнды

### cli
Выполнение CLI команды с полными возможностями извлечения.

**Поля:**
```yaml
- cli: "command"              # Обязательно: CLI команда
  node: node1                 # Целевая нода (default: node1)
  save: var                   # Сохранить полный вывод
  save_hash: hash_var         # Извлечь 0x[hex] хэш
  save_wallet: wallet_var     # Извлечь и валидировать адрес кошелька
  save_node: node_var         # Извлечь адрес ноды (0x::формат)
  save_token: token_var       # Извлечь тикер токена
  save_to: output_var         # Сохранить сырой вывод
  contains: "success"         # Ожидаемая подстрока
  not_contains: "error"       # Неожиданная подстрока
  expect: success             # success | error | any
  wait: "5s"                  # Ждать после команды
  timeout: 30                 # Таймаут команды (default: 30s)
```

**Автоматические Ретраи:**
CLI команды автоматически повторяются при ошибках инициализации (до 10 раз с exponential backoff).

### rpc
JSON-RPC вызов.

```yaml
- rpc: method_name
  params: [arg1, arg2]        # RPC параметры
  node: node1                 # Целевая нода
  save: result_var            # Сохранить результат
  wait: "1s"                  # Ждать после
  expect: success             # Ожидаемый результат
```

### bash
Выполнение bash скрипта в контейнере.

```yaml
- bash: |
    cat /path/to/log | grep ERROR
  node: node1
  save: errors
  expect: success
  timeout: 30
```

### python
Выполнение Python с доступом к контексту.

**API:**
- `ctx.get_variable(name)` - получить переменную
- `ctx.set_variable(name, value)` - установить переменную
- `ctx.has_variable(name)` - проверить существование
- `ctx.variables` - dict всех переменных

```yaml
- python: |
    val = ctx.get_variable('amount')
    result = val * 2
    ctx.set_variable('doubled', result)
```

### print
Отладочный вывод с Jinja2 шаблонизацией.

```yaml
- print: "Value: {{variable}}"
- print: "Complex: {{my_dict}}"
```

**Новое в v2.1.0:** Полная поддержка всех типов данных.

## Операнды Ожидания

### wait (длительность)
Простое ожидание по времени.

```yaml
- wait: "5s"   # 5 секунд
- wait: "500ms" # 500 миллисекунд
- wait: "0s"   # Немедленно (noop)
```

### wait: global_db_sync
Ожидание синхронизации Global DB.

**Одна нода:**
```yaml
- wait: global_db_sync
  node: "{{first_root}}"
  timeout: 60
```

**Несколько нод (параллельная проверка):**
```yaml
- wait: global_db_sync
  nodes: "{{all_nodes}}"
  timeout: 60
```

**Новое в v2.1.0:** Поддержка multi-node синхронизации.

### wait: block_created
Ожидание создания блока(ов) в цепи.

```yaml
- wait: block_created
  node: "{{first_master}}"
  chain: main
  network: stagenet
  min_blocks: 1
  timeout: 120
```

**Статус:** Реализовано, но временно отключено из-за MDBX бага в SDK.

### wait: cli_ready
Ожидание готовности CLI (автоматически в CLI шагах).

```yaml
- wait: cli_ready
  node: node1
  timeout: 30
```

### wait: wallet_balance
Ожидание условия баланса кошелька.

```yaml
- wait: wallet_balance
  wallet: my_wallet
  token: TCELL
  balance: "> 1000"
  timeout: 60
```

### Все Зарегистрированные Waiters

Из WaitRegistry (28 штук):
- `mempool` - Датум в mempool
- `finalized` - Датум/транзакция финализированы в цепи
- `network_online` - Сеть в статусе online
- `sync_complete` - Синхронизация сети завершена
- `dag_event` - Обработка DAG события
- `esbocs_active` - ESBocs консенсус активен
- `first_block` - Первый блок создан
- `ledger_tx` - Транзакция в ledger
- `utxo_indexed` - UTXO индексация завершена
- `chain_data_propagation` - Chain data распространён
- `network_sync` - Сеть синхронизирована
- `token_in_mempool` - Токен в mempool
- `datum_in_mempool` - Датум в mempool
- `datum_in_chain` - Датум в chain
- `emission_synced` - Эмиссия синхронизирована
- `master_containers_running` - Master контейнеры запущены
- `emission_in_ledger` - Эмиссия в ledger
- `transaction_processed` - Транзакция обработана
- `gdb_sync_complete` - GDB sync завершён
- `global_db_sync` - Global DB node list sync (**НОВЫЙ**)
- `delegations_synced` - Делегации синхронизированы
- `cli_ready` - CLI готов
- `wallet_balance` - Условие баланса
- `block_created` - Блок(и) созданы (**НОВЫЙ**)
- `validator_mode_active` - Режим валидатора активен
- `stake_service_ready` - Stake сервис готов
- `esbocs_consensus_active` - ESBocs консенсус активен
- `node_list_propagation` - Node list распространён
- `gdb_clusters_ready` - GDB кластеры готовы

### wait_for_datum
Мониторинг жизненного цикла датума (mempool → block → propagation).

```yaml
# Минимальный (рекомендуется)
- wait_for_datum: "{{tx_hash}}"

# Несколько датумов
- wait_for_datum:
    - "{{hash1}}"
    - "{{hash2}}"

# Все опции
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
Ожидание состояния сети.

**Состояния:** online, offline, links_connecting, links_established, sync_complete

```yaml
- wait_network: online
  nodes: "{{all_nodes}}"
  timeout: 120
  network: stagenet
```

## Управляющие Конструкции

### set
Установка/вычисление переменной. Имя переменной поддерживает подстановку `{{}}`.

```yaml
- set: var_name
  value: "{{expression}}"
  eval: true  # Вычислить как Python
```

**Доступные helper-функции** (при `eval: true`):

| Функция | Описание |
|---------|----------|
| `regex_extract(text, pattern, group=1)` | Первое совпадение regex (строка) |
| `find_all(text, pattern)` | Все совпадения regex (список) |
| `concat(*args)` | Конкатенация строк |
| `join_vars(prefix, count, sep)` | Объединение переменных по префиксу |
| `get_var(name, default)` | Получение переменной по динамическому имени |
| `get_var_dict(name)` | Получение dict-переменной |

```yaml
# Извлечь все серийники из вывода CLI
- set: _serials
  value: "find_all(raw_output, r'[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}')"
  eval: true

# Динамическое имя переменной в for-цикле
- for: _i
  in: "range(1, len(_serials) + 1)"
  steps:
    - set: "serial_{{_i}}"
      value: "_serials[_i - 1]"
      eval: true
```

### if
Условное выполнение.

```yaml
- if: "{{condition}}"
  then:
    - step1
    - step2
  else:
    - step3
```

### for
Итерация по списку.

```yaml
- for: item
  in: "{{list_var}}"
  steps:
    - print: "{{item}}"

# С range
- for: i
  in: "range(5)"
  eval: true
  steps:
    - print: "Iteration {{i}}"
```

### while
Цикл пока условие истинно.

```yaml
- while: "{{condition}}"
  max_loops: 10
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

### loop (устаревший)
Простой счётный цикл.

```yaml
- loop: 3
  steps:
    - cli: "wallet new -w wallet{{iteration}}"
```

### group
Группировка шагов с defaults. Ключи `group:` и `name:` взаимозаменяемы.

```yaml
- group: Group Name
  defaults:
    node: node1
    timeout: 60
  steps:
    - cli: "command1"
    - cli: "command2"
```

## Сетевые Операции

### docker_op
Docker операции над контейнерами.

**Операции:** `start`, `stop`, `restart`, `pause`, `unpause`, `logs`, `exec`, `cp`

```yaml
- docker_op: restart
  services: "{{nodes}}"
  wait_for_ip: true  # Для start/restart

- docker_op: pause
  services: "node-1"  # Заморозить контейнер (имитация потери связи)

- docker_op: unpause
  services: "node-1"  # Возобновить замороженный контейнер

- docker_op: logs
  services: "node-1"
  tail: 50           # последние N строк (по умолчанию 100)
  save: node1_logs   # сохранить вывод в переменную

- docker_op: exec
  services: "node-1"
  command: "cat /opt/cellframe-node/var/log/cellframe-node.log | tail -20"
  save: exec_output  # сохранить stdout в переменную

- docker_op: cp
  src: "node-1:/opt/cellframe-node/var/log/cellframe-node.log"
  dst: "/tmp/node1.log"  # Копирование файла из контейнера на хост
```

**ВАЖНО:** Используйте `stop` + `start` вместо `restart` после изменения конфигурации!

### config
Модификация конфигурации ноды.

```yaml
- config: "{{network}}/chain"
  nodes: "{{all_nodes}}"
  set:
    key: value
    another_key: "true"
```

**Паттерн Config Reload:**
```yaml
- config: "{{network}}/main"
  nodes: "{{all_nodes}}"
  set:
    is_add_directly: "true"

# НЕ restart! Конфиг не перезагрузится
- docker_op: stop
  services: "{{all_nodes}}"
- docker_op: start
  services: "{{all_nodes}}"
  wait_for_ip: true

- wait_network: online
  nodes: "{{all_nodes}}"
```

### snapshot
Сохранение/восстановление состояния сети.

```yaml
- snapshot: create
  name: snapshot_name

- snapshot: restore
  name: snapshot_name
```

## Специальные Шаги

### StepGroup
Группа с метаданными.

```yaml
- group: Group Name
  description: Опциональное описание
  defaults:
    node: node1
  steps:
    - cli: "command"
```

### StepDefaults
Defaults для секции.

```yaml
defaults:
  node: node1
  timeout: 60
  cli:
    net: stagenet
    chain: main
```

Применяются в порядке:
1. Глобальные defaults (верхний уровень)
2. Секционные defaults (setup/test)
3. Групповые defaults
4. Параметры шага (наивысший приоритет)
