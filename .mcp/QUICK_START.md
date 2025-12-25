# Quick Start - Cellframe Stage-Env
## 25 декабря 2025

---

## Быстрый старт

```bash
cd /home/cellframe/cellframe-node/tests/stage-env

# Запуск genesis
sudo ./stage-env run-tests --keep-running scenarios/genesis/

# Запуск primary сценариев
sudo ./stage-env run-tests --keep-running scenarios/primary/

# Запуск конкретного сценария
sudo ./stage-env run-tests --keep-running scenarios/genesis/phase1_zerochain.yml
```

---

## Текущая проблема

**Переменные топологии не инициализируются в standalone сценариях**

Симптом: `Undefined variable: all_nodes`

Исправление внесено в `src/cli/test_commands.py`:
- Добавлена передача `global_context` и `node_configs` в executor
- Используется `ScenarioGlobalContext` из `global_context.py`

---

## Структура проекта

```
/home/cellframe/cellframe-node/tests/stage-env/
├── src/                      # Python код
│   ├── cli/                  # CLI команды
│   ├── scenarios/            # Executor и схемы
│   │   ├── step/             # Step executors
│   │   │   ├── control_flow.py  # set, if, while, for, switch
│   │   │   ├── data.py          # extract, count, node_list, join, compute, format, assert, log
│   │   │   └── wait.py          # wait (duration, mempool, finalized)
│   │   ├── global_context.py    # ScenarioGlobalContext
│   │   └── executor.py          # ScenarioExecutor
│   └── network/              # Network manager
├── scenarios/
│   ├── genesis/              # Genesis сценарии
│   └── primary/              # Primary test сценарии
└── config/stage-env.cfg      # Конфигурация
```

---

## Ключевые классы

1. **ScenarioGlobalContext** (`src/scenarios/global_context.py`)
   - Хранит информацию о топологии (node lists, counts, indices)
   - `set_static_node_info(node_configs)` - инициализация
   - `to_dict()` - для инъекции в RuntimeContext

2. **ScenarioExecutor** (`src/scenarios/executor.py`)
   - `execute_scenario(scenario, global_context, node_configs, ...)`
   - Инжектирует переменные из global_context

3. **NetworkManager** (`src/network/manager.py`)
   - `generate_node_configs()` - генерирует конфиги нод
   - `topology_name` - имя топологии
   - `topology.network.name` - имя сети

---

## Переменные топологии (auto-injected)

```
all_nodes       = ["node-1", "node-2", ..., "node-10"]
root_nodes      = ["node-1", "node-2", "node-3", "node-4"]
master_nodes    = ["node-5", "node-6", "node-7", "node-8", "node-9"]
full_nodes      = ["node-10"]
seed_nodes      = ["node-1", "node-2", "node-3", "node-4"]

root_count      = 4
master_count    = 5
full_count      = 1

root_indices    = [1, 2, 3, 4]
master_indices  = [5, 6, 7, 8, 9]
full_indices    = [10]

first_root      = "node-1"
first_master    = "node-5"
second_root     = "node-2"

node_ip         = {"node1": "172.x.x.x", ...}  # После запуска контейнеров
```

---

## Новые step types

```yaml
# Установка переменной
- set: my_var = "value"

# Логирование
- log: "Message {{var}}"
  level: info

# Вычисление выражения
- compute: result
  expr: "root_count + master_count"

# Генерация списка нод
- node_list: validators
  prefix: "node-"
  start: "{{root_count + 1}}"
  count: "{{master_count}}"

# Объединение в строку
- join: validators_str
  items: "{{validators}}"
  separator: ","

# Извлечение regex
- extract: hash
  source: "{{output}}"
  pattern: "(0x[A-Fa-f0-9]{64})"
  group: 1

# Подсчёт вхождений
- count: order_count
  source: "{{orders}}"
  pattern: "order:"

# Форматирование
- format: message
  template: "Found {n} items"
  n: "{{count}}"

# Проверка условия
- assert: order_count >= 3
  message: "Expected at least 3 orders"
```

---

## Снапшоты

```
/home/cellframe/cellframe-node/tests/testing/snapshots/
├── clean_state               # Чистое состояние
├── genesis_complete          # После genesis
├── primary_phase1_complete   # После phase1
├── primary_phase2_complete   # После phase2
├── primary_phase3_complete   # После phase3
└── primary_complete          # Финальный
```

---

## Полезные файлы

- Детальный контекст: `.mcp/FULL_CONTEXT_20251225.md`
- Pending изменения: `.mcp/PENDING_CHANGES_20251225.md`
- Экспорт кода: `.mcp/CODE_EXPORTS_20251225.md`
- Оригинальные тесты: `/home/cellframe/tests-in-docker`

---

## Следующие шаги

1. Проверить genesis сценарии работают с исправлениями
2. Рефакторинг сценариев с новыми step types
3. Auction tests
4. Composer tests

