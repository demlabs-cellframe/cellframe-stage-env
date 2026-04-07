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
  save_regex: "hash:\s+(\w+)" # Извлечь через regex (первая capture group)
  save_map:                   # Извлечь несколько значений через regex
    order_hash: "hash:\s+(0x[a-f0-9]+)"
    price: "price:\s+(\d+\.\d+)"
  save_hash: hash_var         # Извлечь 0x[hex] хэш
  save_wallet: wallet_var     # Извлечь и валидировать адрес кошелька
  save_node: node_var         # Извлечь адрес ноды (0x::формат)
  save_token: token_var       # Извлечь тикер токена
  save_to: output_var         # Сохранить сырой вывод
  contains: "success"         # Ожидаемая подстрока (поддерживает regex)
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
  save_regex: "addr:\s+(\S+)" # Извлечь через regex
  save_map:                   # Извлечь несколько значений
    key: "pattern"
  wait: "1s"                  # Ждать после
  expect: success             # Ожидаемый результат
  timeout: 30                 # Таймаут RPC вызова
```

**Примечание:** `rpc` НЕ поддерживает `contains`/`not_contains` (в отличие от `cli`).

### bash
Выполнение bash скрипта в контейнере.

```yaml
- bash: |
    cat /path/to/log | grep ERROR
  node: node1                  # None = на хосте
  save: errors
  save_regex: "count:\s+(\d+)" # Извлечь через regex
  save_map:                    # Извлечь несколько значений
    key: "pattern"
  expect: success
  timeout: 300                 # Default: 300s
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
  save: result_var             # Сохранить возвращаемое значение
  save_regex: "pattern"        # Извлечь через regex
  save_map: { key: "pattern" } # Извлечь несколько значений
```

### print
Отладочный вывод с Jinja2 шаблонизацией.

```yaml
- print: "Value: {{variable}}"
- print: "Complex: {{my_dict}}"
```

**Новое в v2.1.0:** Полная поддержка всех типов данных.

### docker_exec
Выполнение команды внутри Docker контейнера. Компактная замена `docker_op: exec`.

```yaml
- docker_exec: "cf-vpn-clientd-ctl status 2>&1"
  services: ["clientd-1"]      # Обязательно: целевые сервисы
  save: _status
  save_regex: "State:\s+(\d+)" # Извлечь через regex
  save_map:
    state: "State:\s+(\d+)"
    addr: "Addr:\s+(\S+)"
  expect: success              # success | error | any
  timeout: 300                 # Default: 300s
```

### dpkg
Установка/удаление DEB пакетов.

```yaml
- dpkg: install
  package: "{{vpn_common_deb}}"
  services: ["clientd-1", "clientd-2"]
  fix_deps: true               # Запустить apt-get -f install

- dpkg: remove
  package: "cellframe-plugin-vpn-client"
  services: ["vpn-client-1"]
```

### metric / metrics_table
Запись и отображение метрик производительности.

```yaml
- metric: throughput_vpn_client_1
  value: "{{_iperf_throughput}}"
  unit: Mbps
  group: multi_client_load
  tags: { client: vpn-client-1 }

- metrics_table: multi_client_load
  title: "Per-Client Throughput"
  format: text                     # text (default) | markdown
  columns: [tag:client, value, unit]
```

---

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

### wait: cli
Поллинг CLI команды до выполнения условия.

```yaml
- wait: cli
  cmd: "srv_vpn_client status -net {{network_name}}"
  node: vpn-client-1
  contains: "connected"        # Подстрока или regex
  not_contains: "error"
  timeout: 30
  interval: 3                  # Секунды между запросами (default: 5)
  save: _status                # Сохранить последний успешный вывод
  save_regex: "state:\s+(\w+)"
  save_map: { key: "pattern" }
  optional: true               # Таймаут НЕ фейлит тест
```

### wait: bash
Поллинг bash скрипта до exit code 0.

```yaml
- wait: bash
  script: "test -f /tmp/ready && echo ok"
  node: vpn-server-1
  contains: "ok"
  timeout: 20
  interval: 2
```

### wait: docker_exec
Поллинг команды внутри Docker контейнера.

```yaml
- wait: docker_exec
  cmd: "test -S /opt/cf-vpn-clientd/var/run/cf-vpn-clientd.sock && echo ready"
  services: ["clientd-1"]
  contains: "ready"
  timeout: 20
  interval: 1
  save: _output
  save_regex: "..."
  save_map: {}
```

### wait: python
Поллинг Python выражения до истинности.

```yaml
- wait: python
  script: "int(ctx.get('_block_count', 0)) > 0"
  timeout: 30
  interval: 5
```

### wait: notify
Ожидание уведомления от notify сервера.

```yaml
- wait: notify
  node: "{{client_node}}"
  notify_class: "VpnClientState"
  contains: "connected"
  timeout: 30
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

# С range (строковые in авто-вычисляются)
- for: i
  in: "range(5)"
  steps:
    - print: "Iteration {{i}}"
```

**Примечание:** Строковые значения `in` автоматически вычисляются как Python-выражения. `eval: true` не нужен (в отличие от `set` шагов).

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
  save: exec_output        # сохранить stdout в переменную
  save_regex: "pattern"    # Извлечь через regex
  save_map: { k: "re" }   # Извлечь несколько значений

- docker_op: cp
  src: "node-1:/opt/cellframe-node/var/log/cellframe-node.log"
  dst: "/tmp/node1.log"    # Копирование файла из контейнера на хост
```

**Примечание:** Для простых `exec` операций предпочтительнее [`docker_exec`](#docker_exec).

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
    fee_addr: "{{fee_addr}}"

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
Создание/восстановление/проверка/удаление снэпшотов состояния сети.

```yaml
- snapshot: create
  name: snapshot_name
  is_base: true                # Базовый снэпшот для suite
  stop_containers: true        # Остановить перед создание (MDBX/GDB)
  restart_after: true
  regenerate_certs: false
  clone_images: { src: [t1] }  # Клонировать committed image
  wait_ready: true             # Ждать CLI-готовности нод
  wait_ready_timeout: 90
  wait_ready_check: "vpn_cdb version"

- snapshot: restore
  name: snapshot_name

- snapshot: verify
  name: cdb_ready
  save: has_snapshot           # True/False (без exception)

- snapshot: delete
  name: old_snapshot
```

## Специальные Шаги

### StepGroup
Группировка шагов с общим именем и опциональными defaults. Ключи `group:` и `name:` взаимозаменяемы.

```yaml
- group: Group Name     # 'name:' тоже допустим
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
