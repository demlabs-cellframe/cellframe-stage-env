# Полный контекст проекта Cellframe Stage-Env
## Дата: 25 декабря 2025

---

## 1. ОПИСАНИЕ ПРОЕКТА

**Cellframe Stage-Env** - тестовая среда для Cellframe ноды, позволяющая:
- Запускать многонодовую сеть в Docker контейнерах
- Выполнять YAML-сценарии тестирования
- Управлять снапшотами состояния сети
- Автоматизировать genesis-инициализацию

**Путь к проекту:** `/home/cellframe/cellframe-node/tests/stage-env`

**Оригинальные Docker тесты (для справки по синтаксису CLI):** `/home/cellframe/tests-in-docker`
- `functions.sh` - синтаксис всех CLI команд
- `variables/foobar.sh` - переменные конфигурации

---

## 2. СТРУКТУРА ПРОЕКТА

```
/home/cellframe/cellframe-node/tests/stage-env/
├── src/
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py           # Главный CLI entry point
│   │   └── test_commands.py  # Команды run-tests
│   ├── config/
│   │   ├── generator.py      # Генерация конфигов нод
│   │   └── manager.py        # Загрузка конфигурации
│   ├── monitoring/
│   │   ├── datum.py          # Мониторинг датумов (mempool/finalized)
│   │   ├── manager.py        # MonitoringManager
│   │   └── network_consensus.py
│   ├── network/
│   │   ├── manager.py        # NetworkManager - главный класс управления сетью
│   │   ├── genesis_config.py # Конфигурация genesis
│   │   └── snapshot.py       # Управление снапшотами
│   ├── scenarios/
│   │   ├── executor.py       # Основной исполнитель сценариев
│   │   ├── global_context.py # ScenarioGlobalContext
│   │   ├── parser.py         # Парсер YAML сценариев
│   │   ├── schema.py         # Pydantic схемы шагов
│   │   ├── schema_control_flow.py  # Схемы control flow (set, if, while, for, switch)
│   │   ├── schema_data.py    # Схемы data manipulation (extract, count, node_list, join, compute, format, assert, log)
│   │   └── step/
│   │       ├── __init__.py   # Регистрация всех executor'ов
│   │       ├── base.py       # Базовый класс StepExecutor
│   │       ├── cli.py        # CLI команды
│   │       ├── control_flow.py  # SetStepExecutor, IfStepExecutor, WhileStepExecutor, ForStepExecutor, SwitchStepExecutor
│   │       ├── data.py       # AssertStepExecutor, LogStepExecutor, ExtractStepExecutor, CountStepExecutor, NodeListStepExecutor, JoinStepExecutor, ComputeStepExecutor, FormatStepExecutor
│   │       ├── docker.py     # Docker операции
│   │       ├── python.py     # Python шаги
│   │       ├── snapshot.py   # Snapshot операции
│   │       ├── wait.py       # Wait шаги (duration, mempool, finalized)
│   │       └── wait_for_datum.py  # WaitForDatumStepExecutor
│   └── utils/
│       ├── cli_parser.py
│       ├── logger.py
│       └── report_generator.py
├── scenarios/
│   ├── common/
│   │   └── set_net_default.yml
│   ├── genesis/
│   │   ├── phase1_zerochain.yml  # Инициализация zerochain, токен, эмиссия
│   │   ├── phase2_esbocs.yml     # Создание genesis блока mainchain
│   │   └── common/
│   │       └── snapshot_restore.yml
│   └── primary/
│       ├── phase1_delegation_direct.yml  # mTCELL, прямая делегация 2 ключей, отзыв 1
│       ├── phase2_decrees.yml            # Network fee, block reward, min_validators
│       ├── phase3_delegation_orders.yml  # Делегация по ордерам
│       └── phase4_transfers.yml          # Обычные и batch транзакции
├── config/
│   └── stage-env.cfg           # Главный конфиг
├── topologies/
│   └── default.yml             # Топология сети (4 root, 5 master, 1 full)
├── cache/                      # Кэш конфигов и данных нод
├── docker-compose.generated.yml
└── stage-env                   # Исполняемый файл CLI
```

---

## 3. ТОПОЛОГИЯ СЕТИ (default.yml)

```
Nodes:
- node-1 to node-4: ROOT (seed_nodes, PoA validators)
- node-5 to node-9: MASTER (validators, can receive delegated keys)
- node-10: FULL (обычная нода)

Начальное состояние после genesis:
- 2 активных PoA валидатора (node-5, node-6)
- TCELL токен создан
- Эмиссия 10.0e+54 TCELL на fee_addr
- Genesis блок в mainchain
```

---

## 4. ТЕКУЩЕЕ СОСТОЯНИЕ РАЗРАБОТКИ

### 4.1 Завершённые задачи

1. **Genesis сценарии** - работают, создают снапшоты:
   - `genesis_complete` - после phase2_esbocs.yml

2. **Primary сценарии Phase 1-4** - работают:
   - `primary_phase1_complete` - после делегации/отзыва
   - `primary_phase2_complete` - после decrees
   - `primary_phase3_complete` - после delegation by orders
   - `primary_complete` - финальный снапшот

3. **Новые step types** (добавлены и работают):
   - `set` - установка переменных
   - `log` - логирование сообщений
   - `assert` - проверка условий
   - `extract` - regex извлечение из строки
   - `count` - подсчёт вхождений паттерна
   - `node_list` - генерация списка нод
   - `join` - объединение элементов в строку
   - `compute` - вычисление выражений
   - `format` - форматирование строк

4. **Waiters** (условные ожидания):
   - `wait: mempool` - ждёт datum в mempool
   - `wait: finalized` - ждёт datum в блоке
   - `wait_network: online` - ждёт ноды онлайн
   - `wait: wallet_balance` - ждёт баланс кошелька

### 4.2 Текущая задача (в процессе)

**Проверка genesis сценариев и их рефакторинг**

Была обнаружена проблема: при запуске standalone сценариев переменные топологии (`all_nodes`, `root_nodes`, `master_nodes` и т.д.) не инициализировались.

**Исправление в `test_commands.py`:**
- Добавлена передача `global_context` и `node_configs` в `execute_scenario()`
- Использован `ScenarioGlobalContext` из `global_context.py`

### 4.3 Ожидающие задачи

1. **Рефакторинг genesis сценариев** - заменить Python блоки на новые step types
2. **Рефакторинг primary сценариев** - аналогично
3. **Auction tests** - не начаты
4. **Composer tests** - не начаты

---

## 5. КЛЮЧЕВЫЕ ФАЙЛЫ И ИХ ИЗМЕНЕНИЯ

### 5.1 test_commands.py (последние изменения)

**Путь:** `/home/cellframe/cellframe-node/tests/stage-env/src/cli/test_commands.py`

**Изменения:**
1. Добавлена инициализация `global_context` и `node_configs` для standalone сценариев (строки ~283-303)
2. Аналогичные изменения для suite setup (строки ~449-470)
3. Аналогичные изменения для suite scenarios (строки ~598-620)

```python
# Пример добавленного кода:
node_configs = None
global_context = None
if network_mgr:
    node_configs = network_mgr.generate_node_configs()
    from ..scenarios.global_context import ScenarioGlobalContext
    global_context = ScenarioGlobalContext(
        network_name=network_mgr.topology.network.name,
        topology_name=network_mgr.topology_name
    )
    global_context.set_static_node_info(node_configs)

await executor.execute_scenario(
    scenario,
    compose_manager=network_mgr.compose if network_mgr else None,
    snapshot_manager=network_mgr.snapshot_manager if network_mgr else None,
    genesis_config_manager=network_mgr.genesis if network_mgr else None,
    global_context=global_context,
    node_configs=node_configs
)
```

4. Пользователь добавил поддержку `restore_snapshot` в suite descriptor:
```python
restore_snapshot_name = None
if isinstance(suite_spec, SuiteDescriptor) and suite_spec.restore_snapshot:
    restore_snapshot_name = suite_spec.restore_snapshot
    if "{{topology_name}}" in restore_snapshot_name:
        topology_name = getattr(suite_spec.network, 'topology', 'default') if suite_spec.network else 'default'
        restore_snapshot_name = restore_snapshot_name.replace("{{topology_name}}", topology_name)
```

### 5.2 executor.py

**Путь:** `/home/cellframe/cellframe-node/tests/stage-env/src/scenarios/executor.py`

Ключевой метод `execute_scenario()`:
- Принимает `global_context` и `node_configs`
- Инжектирует переменные топологии перед setup фазой (строки 448-466)
- После setup собирает IP адреса нод (строки 487-500)

### 5.3 global_context.py

**Путь:** `/home/cellframe/cellframe-node/tests/stage-env/src/scenarios/global_context.py`

Класс `ScenarioGlobalContext`:
- `__init__(network_name, topology_name, docker_client=None)`
- `set_static_node_info(node_configs)` - устанавливает списки нод
- `to_dict()` - возвращает все переменные для инъекции в контекст

Генерируемые переменные:
- `all_nodes` - список всех нод ["node-1", "node-2", ...]
- `root_nodes` - ["node-1", "node-2", "node-3", "node-4"]
- `master_nodes` - ["node-5", "node-6", "node-7", "node-8", "node-9"]
- `full_nodes` - ["node-10"]
- `seed_nodes` - те же что root_nodes
- `root_count`, `master_count`, `full_count` - количества
- `root_indices`, `master_indices`, `full_indices` - индексы [1,2,3,4], [5,6,7,8,9], [10]
- `first_root`, `first_master` - "node-1", "node-5"
- `node_ip` - словарь с IP адресами

### 5.4 schema_control_flow.py и schema_data.py

Разделение шагов на две категории:

**Control flow (schema_control_flow.py):**
- `SetStep` - установка переменных
- `IfStep` - условное выполнение
- `WhileStep` - цикл while
- `ForStep` - цикл for
- `SwitchStep` - switch/case
- `SkipIfStep` - пропуск шагов

**Data manipulation (schema_data.py):**
- `AssertStep` - проверка условий
- `LogStep` - логирование
- `ExtractStep` - regex извлечение
- `CountStep` - подсчёт
- `NodeListStep` - генерация списка нод
- `JoinStep` - объединение в строку
- `ComputeStep` - вычисление выражений
- `FormatStep` - форматирование строк

### 5.5 control_flow.py и data.py (step executors)

**control_flow.py:**
- `SetStepExecutor`
- `IfStepExecutor`
- `WhileStepExecutor`
- `ForStepExecutor`
- `SwitchStepExecutor`

**data.py:**
- `AssertStepExecutor`
- `LogStepExecutor`
- `ExtractStepExecutor`
- `CountStepExecutor`
- `NodeListStepExecutor`
- `JoinStepExecutor`
- `ComputeStepExecutor`
- `FormatStepExecutor`

### 5.6 wait.py

Обрабатывает различные типы ожиданий:
- Duration: `wait: "30s"`
- Mempool: `wait: mempool` (с datum hash)
- Finalized: `wait: finalized` (datum в блоке)
- Wallet balance: `wait: wallet_balance`

### 5.7 datum.py

Класс `DatumMonitor`:
- `_check_in_mempool()` - проверка в mempool
- `_check_in_dag_mempool()` - для DAG chains
- `_check_in_blockchain_blocks()` - проверка в блоках (использует `block dump`)

---

## 6. ИЗВЕСТНЫЕ ПРОБЛЕМЫ И РЕШЕНИЯ

### 6.1 Переменные топологии не инициализируются

**Проблема:** `Undefined variable: all_nodes`

**Решение:** Добавить передачу `global_context` и `node_configs` в `execute_scenario()` (см. раздел 5.1)

### 6.2 wait: finalized не находит datum в блоках

**Проблема:** `block list` не показывает datum hashes

**Решение:** В `datum.py` используется `block dump` для каждого блока:
```python
for block_hash in block_hashes:
    dump_cmd = ["cellframe-node-cli", "block", "dump", "-net", network, "-chain", chain, "-hash", block_hash]
    # ... check if datum_hash in dump output
```

### 6.3 Синтаксис CLI команд

**Проблема:** Неправильный порядок параметров

**Правильный синтаксис (из /home/cellframe/tests-in-docker/functions.sh):**
- `srv_stake order list` (не `srv_stake list orders`)
- `esbocs min_validators_count set -chain main -net ${NET} -cert ${CERT} -val_count ${VAL_COUNT}`
- `decree create common -net ${NET} -chain zerochain -decree_chain main`
- `block reward set -net ${NET} -poa_cert ${CERT} -value 1.5e+18 -chain main`

### 6.4 Минимальный размер делегации

**Правило:** Минимальный размер делегированного стейка - 10.0 mTCELL (задаётся декретом консенсуса)

**Решение:** В phase3 увеличены размеры делегации до 10.0e+18

### 6.5 Сертификаты не копируются после cache clean

**Проблема:** "certificate not found" после очистки кэша

**Решение:** В `generator.py` добавлен вызов `copy_private_certs_to_node_data()` даже если сертификаты существуют

---

## 7. СУЩЕСТВУЮЩИЕ СНАПШОТЫ

```
/home/cellframe/cellframe-node/tests/testing/snapshots/
├── clean_state/              # Чистое состояние после genesis
├── genesis_complete/         # После phase2_esbocs
├── primary_phase1_complete/  # После делегации/отзыва
├── primary_phase2_complete/  # После decrees
├── primary_phase3_complete/  # После delegation by orders
└── primary_complete/         # Финальный снапшот
```

---

## 8. ПОЛЕЗНЫЕ КОМАНДЫ

### Запуск тестов
```bash
cd /home/cellframe/cellframe-node/tests/stage-env
sudo ./stage-env run-tests scenarios/genesis/phase1_zerochain.yml
sudo ./stage-env run-tests --keep-running scenarios/primary/
```

### Проверка контейнеров
```bash
sudo docker ps --format "{{.Names}}: {{.Status}}" | grep cellframe-stage
```

### Просмотр логов
```bash
sudo docker logs cellframe-stage-node-1 2>&1 | tail -50
```

### CLI команды в контейнере
```bash
sudo docker exec cellframe-stage-node-1 cellframe-node-cli net get status -net stagenet
sudo docker exec cellframe-stage-node-1 cellframe-node-cli srv_stake list keys -net stagenet
sudo docker exec cellframe-stage-node-1 cellframe-node-cli block list -chain main -net stagenet
```

---

## 9. ЗАВИСИМОСТИ PYTHON

```
jinja2
pydantic
structlog
docker
httpx
```

Установка:
```bash
sudo apt install python3-jinja2 python3-pydantic
pip install structlog docker httpx
```

---

## 10. ПРИМЕРЫ YAML СЦЕНАРИЕВ

### 10.1 Использование новых step types

```yaml
test:
  # Установка переменной
  - set: my_var = "value"
  
  # Логирование
  - log: "Processing {{my_var}}"
    level: info
  
  # Вычисление
  - compute: result
    expr: "root_count + master_count"
  
  # Генерация списка нод
  - node_list: validators
    prefix: "node-"
    start: "{{root_count + 1}}"
    count: "{{master_count}}"
  
  # Объединение
  - join: validators_str
    items: "{{validators}}"
    separator: ","
  
  # Извлечение
  - extract: hash
    source: "{{cli_output}}"
    pattern: "(0x[A-Fa-f0-9]{64})"
    group: 1
  
  # Подсчёт
  - count: order_count
    source: "{{orders_list}}"
    pattern: "order:"
  
  # Форматирование
  - format: message
    template: "Found {count} orders"
    count: "{{order_count}}"
  
  # Проверка
  - assert: order_count >= 3
    message: "Expected at least 3 orders"
```

### 10.2 Control flow

```yaml
test:
  # Условие
  - if: "{{validator_count}} < 3"
    then:
      - log: "Not enough validators"
    else:
      - log: "Validators OK"
  
  # Цикл for
  - for: node_idx
    in: "{{master_indices}}"
    steps:
      - cli: "node dump"
        node: "node-{{node_idx}}"
```

---

## 11. СЛЕДУЮЩИЕ ШАГИ

1. **Исправить genesis сценарии** - проверить что переменные топологии корректно инжектируются
2. **Рефакторинг genesis сценариев** - заменить Python блоки на новые step types где возможно
3. **Рефакторинг primary сценариев** - аналогично
4. **Auction tests** - разработать новые сценарии
5. **Composer tests** - разработать новые сценарии

---

## 12. КОНТАКТЫ И РЕСУРСЫ

- **Оригинальные тесты:** `/home/cellframe/tests-in-docker`
- **Артефакты тестов:** `/home/cellframe/cellframe-node/tests/testing/artifacts/`
- **Логи:** `/home/cellframe/cellframe-node/tests/testing/logs/`
- **Снапшоты:** `/home/cellframe/cellframe-node/tests/testing/snapshots/`

---

## 13. КОНФИГУРАЦИЯ (stage-env.cfg)

```ini
[SNAPSHOT]
mode = filesystem
phase1_snapshot_name = primary_phase1_complete
genesis_stage = full
auto_cleanup = True
keep_snapshot_count = 5

[TIMEOUTS]
startup = 600
health_check = 600
command = 30

[NODE]
source_type = local
build_type = debug

[ARTIFACTS]
collect_node_logs = True
collect_crash_dumps = True
```

---

*Документ создан: 25 декабря 2025*
*Автор: Claude (AI Assistant)*

