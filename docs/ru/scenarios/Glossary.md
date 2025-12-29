# Словарь тестовых сценариев

**Полный справочник языка сценариев stage-env**

Comprehensive описание всех возможностей YAML языка сценариев. Используйте как справочник при написании тестов.

## 📚 Содержание

1. [Типы файлов](#типы-файлов)
2. [Структура сценария](#структура-сценария)
3. [Типы шагов](#типы-шагов)
4. [Типы проверок](#типы-проверок)
5. [Система defaults](#система-defaults)
6. [Извлечение данных](#извлечение-данных)
7. [Система suites](#система-suites)
8. [Продвинутые возможности](#продвинутые-возможности)

---

## Типы файлов

### Тестовый сценарий
Помечен наличием поля `test:`. Содержит выполняемые тестовые шаги.

```yaml
name: Мой тест
description: Описание теста

test:
  - cli: token list
```

### Suite descriptor
Помечен наличием поля `suite:`. Определяет метаданные test suite и общий setup.

```yaml
suite: "Token Operations Suite"
description: "E2E тесты токенов"

includes:
  - common/create_test_cert.yml

setup:
  - wait: 5s
```

Располагается на том же уровне что и директория suite (например, `token.yml` рядом с `token/`).

### Include шаблон
Переиспользуемый компонент в `tests/common/`. Содержит setup, defaults или variables.

```yaml
# common/set_net_default.yml
defaults:
  cli:
    net: "{{network_name}}"
```

---

## Структура сценария

```yaml
# === МЕТАДАННЫЕ (обязательно) ===
name: string                    # Название сценария
description: string             # Что делает тест

# === МЕТАДАННЫЕ (опционально) ===
author: string                  # Автор
tags: [string, ...]            # Теги для фильтрации
version: string                 # Версия (default: "1.0")

# === СЕТЬ (опционально, default: topology: default) ===
network:
  topology: default             # Использовать predefined топологию
  name: stagenet                # Имя сети (становится {{network_name}})

# === INCLUDES (опционально) ===
includes:
  - common/create_test_cert.yml  # Пути относительно tests/common/

# === ПЕРЕМЕННЫЕ (опционально) ===
variables:
  my_var: value                  # Предопределённые переменные

# === DEFAULTS (опционально) ===
defaults:
  node: node1                    # Default нода для всех шагов
  wait: 3s                       # Default wait после шагов
  expect: success                # Default ожидаемый результат
  timeout: 30                    # Default таймаут (секунды)
  cli:                          # CLI авто-префиксы
    net: "{{network_name}}"

# === SETUP (опционально) ===
setup:
  - cli: wallet new -w test      # Подготовительные шаги

# === TEST (обязательно) ===
test:
  - cli: token list              # Основные тестовые действия

# === CHECK (опционально) ===
check:
  - cli: token info -name TEST   # Проверка результатов
    contains: "TEST"
```

---

## Типы шагов

### CLIStep
Выполнение команды `cellframe-node-cli`.

```yaml
- cli: token_decl -token TEST -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
  node: node1                    # Нода для выполнения (default: node1)
  save: full_output              # Сохранить весь вывод
  save_hash: tx_hash             # Извлечь и валидировать hash (0x[hex])
  save_wallet: my_address        # Извлечь и валидировать wallet address (base58 + checksum)
  save_node: node_addr           # Извлечь node address (0x::формат)
  wait: 3s                       # Ожидание после команды
  expect: success                # Ожидаемый результат (success/error/any)
  contains: "SUCCESS"            # Проверить что вывод содержит строку
  timeout: 30                    # Таймаут команды (секунды)
```

**Save хелперы:**
- `save: var` - сохраняет весь вывод (авто-извлечение hash для token_decl/emit/tx_create)
- `save_hash: var` - извлекает и валидирует hash (0x[hex]{64})
- `save_wallet: var` - извлекает и валидирует wallet address (base58 + checksum)
- `save_node: var` - извлекает node address (0x::формат)

**Примеры:**

```yaml
# Извлечь адрес кошелька (одна строка!)
- cli: wallet info -w test
  save_wallet: addr

# Извлечь hash из создания токена
- cli: token_decl -token TEST -total_supply 1000000 -certs test_cert
  save_hash: token_hash

# Извлечь адрес ноды
- cli: net get_cur_addr
  save_node: node_addr

# Сохранить весь вывод
- cli: token info -name TEST
  save: full_info
```

**CLI авто-defaults:** Параметры из `defaults.cli` автоматически добавляются если команда их поддерживает.

### ToolStep
Выполнение команды `cellframe-node-tool`.

```yaml
- tool: cert create test_cert sig_dil
  node: node1
  save: cert_result
  expect: success
  timeout: 30
```

**Важно:** Указывайте только ИМЯ сертификата, без пути и расширения. Tool автоматически добавляет `/opt/cellframe-node/var/lib/ca/` и `.dcert`.

### RPCStep
JSON-RPC вызов к ноде.

```yaml
- rpc: net_get_cur_addr
  params: []                     # RPC параметры (список)
  node: node1
  save: rpc_result
  wait: 1s
  expect: success
  timeout: 30
```

**Endpoint:** `http://<node_ip>:8545` (base_rpc_port из конфига)

### WaitStep
Простое ожидание.

```yaml
- wait: 5s                       # Длительность: Ns, Nms (например, 5s, 500ms, 0s)
```

### WaitForDatumStep
Мониторинг жизненного цикла датума (mempool → блок → распространение).

```yaml
# Минимальный синтаксис (рекомендуется!)
- wait_for_datum: "{{tx_hash}}"

# Несколько датумов
- wait_for_datum:
    - "{{hash1}}"
    - "{{hash2}}"

# Со всеми опциями (обычно не нужно!)
- wait_for_datum: "{{tx_hash}}"
  node: node1                    # Нода для проверки (default: node1)
  network: stagenet              # Имя сети (default: stagenet)
  chain: main                    # Имя chain (default: main)
  check_master_nodes: true       # Проверять masters (default: true)
  timeout_total: 300             # Общий таймаут (default: 300s)
  timeout_mempool: 60            # Таймаут mempool (DEPRECATED - hardcoded 0.5s)
  timeout_verification: 120      # После verification (default: 120s)
  timeout_in_blocks: 180         # После in blocks (default: 180s)
  check_interval: 2              # Проверка каждые N секунд (default: 2s)
  save_status: datum_status      # Сохранить финальный статус
```

**Жизненный цикл:**
1. **0.5s** - Проверка mempool (если не найден → REJECTED, fail fast!)
2. **30-120s** - Ожидание включения в блок
3. **60-180s** - Ожидание распространения по сети
4. Возвращается немедленно по завершении (без лишнего ожидания)

**Лучшая практика:** Используйте минимальный синтаксис. Defaults настроены для реального поведения сети.

### PythonStep
Выполнение Python кода с доступом к контексту.

```yaml
- python: |
    items = ctx.get_variable('items_list')
    ctx.set_variable('count', len(items))
```

**Context API:**
- `ctx.get_variable(name)` - получить переменную
- `ctx.set_variable(name, value)` - установить переменную
- `ctx.has_variable(name)` - проверить существование

### BashStep
Выполнение Bash скрипта в контейнере ноды.

```yaml
- bash: |
    cat /opt/cellframe-node/var/log/cellframe-node.log | grep ERROR
  node: node1
  save: errors
  expect: success
  timeout: 30
```

**Применение:** Когда нужны shell команды недоступные через CLI (файловые операции, парсинг логов и т.д.)

### LoopStep
Повторение шагов N раз.

```yaml
- loop: 5
  steps:
    - cli: ledger tx -all
      save: tx_list
    - wait: 1s
```

**Применение:** Простая итерация без переменной индекса. Для итерации с индексом используйте `ForStep`.

### ForStep
Итерация по списку значений.

```yaml
- for: node_idx
  in: "{{root_indices}}"        # Список или переменная со списком
  steps:
    - cli: node dump
      node: "node-{{node_idx}}"
      save_node: "addr_{{node_idx}}"
```

### IfStep
Условное выполнение.

```yaml
- if: ctx.get_variable('balance') > 1000
  then:
    - cli: token emit ...
  else:
    - cli: token list
```

### WhileStep
Цикл пока условие истинно.

```yaml
- while: ctx.get_variable('retry_count') < 3
  max_iterations: 100           # Лимит безопасности
  steps:
    - cli: net get status
      save: status
```

### SwitchStep
Switch/case для множественного выбора.

```yaml
- switch: "{{node_role}}"
  cases:
    root:
      - cli: ...
    master:
      - cli: ...
  default:
    - cli: ...
```

### SetStep
Установка значения переменной.

```yaml
- set: calculated_value
  value: "{{base_value}}_processed"
```

### ConfigStep
Модификация конфигурации ноды.

```yaml
- config: "stagenet/main"
  nodes: ["node-1", "node-2"]
  set:
    validators_addrs: "{{validators_str}}"
    fee_addr: "{{fee_wallet}}"
```

### NetworkWaitStep
Ожидание состояния сети.

```yaml
- wait_network: online
  nodes: ["node-1", "node-2"]
  timeout: 120
```

### DockerOpStep
Docker операции (start/stop/restart).

```yaml
- docker_op: restart
  services: ["node-1", "node-2"]
  detach: true
```

### SnapshotStep
Операции со snapshots.

```yaml
- snapshot: create
  name: before_emission
```

### StepGroup
Группировка шагов с локальными defaults.

```yaml
- group: "Операции с кошельками"
  defaults:
    node: node2
    wait: 1s
  steps:
    - cli: wallet new -w wallet1    # Использует node2, wait 1s
    - cli: wallet new -w wallet2    # Использует node2, wait 1s
```

---

## Типы проверок

Выполняются после секции `test` для валидации результатов.

### CLICheck

```yaml
check:
  - cli: token info -name TEST
    node: node1
    contains: "TEST"               # Вывод должен содержать
    not_contains: "ERROR"          # Вывод НЕ должен содержать
    equals: "точное совпадение"    # Точное совпадение вывода
    timeout: 30
```

### PythonCheck

```yaml
check:
  - python: |
      emitted = int(ctx.get_variable('emitted_amount'))
      received = int(ctx.get_variable('received_amount'))
      assert received == emitted, f"Несовпадение: {received} != {emitted}"
```

Падает если AssertionError или любое исключение.

### BashCheck

```yaml
check:
  - bash: |
      test -f /opt/cellframe-node/var/lib/global_db/gdb.dat
    node: node1
    timeout: 10
```

Падает если exit code != 0.

### RPCCheck

```yaml
check:
  - rpc: net_get_cur_addr
    params: []
    node: node1
    result_contains: "0x"          # Результат должен содержать
    result_equals: expected_value  # Точное совпадение
```

---

## Система defaults

Иерархические defaults с наследованием: **global → section → group → step**

### Глобальные defaults

```yaml
defaults:
  node: node1
  wait: 3s
  expect: success
  timeout: 60
  cli:
    net: "{{network_name}}"
    token: MYTOKEN

test:
  - cli: token list               # Наследует все defaults
  - cli: wallet list
    node: node2                   # Переопределяет node
```

### Section defaults

```yaml
test:
  defaults:                       # Применяется только к test секции
    node: node2
    wait: 1s
  steps:
    - cli: token list
    - cli: wallet list
```

**Современный синтаксис:** Используйте формат `SectionConfig` для setup/test/check секций.

### Group defaults

```yaml
- group: "Операции с токенами"
  defaults:
    wait: 5s
  steps:
    - cli: token_decl ...
    - cli: token_emit ...
```

### CLI авто-defaults

Специальное поле `cli:` для автоматического добавления CLI параметров:

```yaml
defaults:
  cli:
    net: "{{network_name}}"       # Добавляет -net stagenet ко всем CLI командам
    token: MYTOKEN                # Добавляет -token MYTOKEN
```

**Механизм:**
1. CLICommandParser парсит `cellframe-node-cli help` при старте
2. Строит карту команды → поддерживаемые опции
3. Перед выполнением CLI команды проверяет поддержку опции
4. Добавляет `-option value` если отсутствует
5. Никогда не дублирует существующие опции

**Типичное использование:** Через include `common/set_net_default.yml`.

---

## Извлечение данных

Удобные `save_*` хелперы для извлечения и валидации типовых данных.

### Save хелперы

```yaml
# Извлечь адрес кошелька (одна строка - авто-валидация!)
- cli: wallet info -w my_wallet
  save_wallet: wallet_addr

# Извлечь hash
- cli: token_decl -token TEST -total_supply 1000000 -certs test_cert
  save_hash: token_hash

# Извлечь адрес ноды
- cli: net get_cur_addr
  save_node: node_addr

# Сохранить весь вывод
- cli: token info -name TEST
  save: full_info
```

### Справочник хелперов

| Хелпер | Извлекает | Валидация | Использование |
|--------|-----------|-----------|---------------|
| `save_hash` | 0x[hex]{64} | Проверка формата | token_decl, token_emit, tx_create |
| `save_wallet` | Base58 адрес | Base58 + SHA3-256 checksum | wallet info |
| `save_node` | 0x::формат | Проверка :: separator | net get_cur_addr |
| `save` | Весь вывод | Нет (авто-hash для token/tx команд) | Любая команда |

### Примеры

```yaml
test:
  # Создать кошелёк и извлечь адрес
  - cli: wallet new -w test
  - cli: wallet info -w test
    save_wallet: addr              # ✅ Чисто и понятно!
  
  # Создать токен и извлечь hash
  - cli: token_decl -token T -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
    save_hash: token_hash          # ✅ Одна строка!
  
  # Эмитировать и извлечь hash
  - cli: token_emit -token T -value 1000 -addr {{addr}} -certs test_cert
    save_hash: emit_hash
  
  # Использовать извлечённые значения
  - cli: tx_create -token T -from {{emit_hash}}:0 -value 500 -fee 0.1
    save_hash: tx_hash
```

---

## Система suites

Организация связанных тестов в suites с общим setup.

### Структура

```
tests/e2e/token/
├── token.yml                    # Suite descriptor
├── 001_token_decl.yml           # Тестовый сценарий
├── 002_token_emit.yml           # Тестовый сценарий
└── 003_token_list.yml           # Тестовый сценарий
```

### Suite descriptor

```yaml
suite: "Token Operations Suite"
description: "E2E тесты для токенов"
tags: [e2e, token]
version: "1.0"

# Default сеть для всех сценариев
network:
  topology: default

# Общие includes - наследуются всеми сценариями
includes:
  - common/create_test_cert.yml
  - common/set_net_default.yml

# Suite-level setup - выполняется ОДИН раз перед всеми сценариями
setup:
  - wait: 5s
```

### Порядок выполнения

1. **Suite discovery** - по структуре директорий
2. **Snapshot restore** - чистое состояние для suite
3. **Suite setup** - выполнение descriptor's includes + setup
4. **Scenario execution** - запуск всех .yml в директории
5. **Artifact collection** - сбор логов для suite

### Преимущества

- Сертификат создаётся один раз для suite (не для каждого сценария)
- Общий setup разделяется
- Чистое состояние между suites (snapshots)
- Логическая группировка

---

## Подстановка переменных

**Синтаксис:** `{{variable_name}}`

**Использование:** Любое строковое поле (CLI команды, RPC параметры, проверки, и т.д.)

**Встроенные переменные:**
- `{{network_name}}` - из network.name (default: "stagenet")

**Runtime переменные:**
- Устанавливаются через `save:` в шагах
- Устанавливаются через `ctx.set_variable()` в Python коде
- Устанавливаются в секции `variables:`

**Пример:**

```yaml
variables:
  token_name: MYTOKEN

test:
  - cli: token_decl -token {{token_name}} -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
    save: hash
  
  - cli: token info -name {{token_name}}
    contains: "{{token_name}}"
```

---

## Обработка ошибок

### CLI ошибки

Cellframe CLI возвращает exit code 0 даже при ошибках!

**Детектирование:** Executor парсит JSON/YAML вывод на наличие поля `errors:`.

**Пример:**

```yaml
# Это будет детектировано как ошибка даже с exit 0!
- cli: tx_create -token TEST -from {{blocked_utxo}}:0 -value 100
  expect: error                  # Мы ХОТИМ ошибку здесь
  contains: "UTXO is blocked"
```

### Ожидаемые ошибки

```yaml
- cli: wallet new -w existing_wallet
  expect: error                  # Тестируем что правильно падает
  contains: "already exists"
```

### Ошибки валидации

Pydantic валидирует YAML структуру перед выполнением.

**Частые ошибки:**
- `Field required` - отсутствует обязательное поле
- `Invalid type` - неправильный тип данных
- `Unknown step type` - опечатка в типе шага

---

## Система includes

**Путь поиска:** `tests/common/`

**Стратегия merge:** Deep merge, основной файл имеет приоритет, `None` значения игнорируются.

**Общие includes:**

```yaml
includes:
  - common/create_test_cert.yml       # Создаёт test_cert для подписи
  - common/set_net_default.yml        # Авто-добавляет -net параметр
  - common/wallets/create_wallet.yml  # Создаёт test_wallet с wallet_addr
  - common/networks/single_node.yml   # Минимальная топология override
```

**Создание своего include:**

`tests/common/my_include.yml`:
```yaml
setup:
  - cli: token_decl -token {{token_name}} -total_supply {{supply}} -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert

variables:
  token_created: true
```

---

## Лучшие практики

### ✅ ДЕЛАЙТЕ

```yaml
# Используйте includes для общего setup
includes:
  - common/create_test_cert.yml

# Используйте defaults для уменьшения повторений
defaults:
  node: node1
  wait: 3s

# Используйте wait_for_datum вместо фиксированных wait
- cli: token_emit -token TEST -value 1000 -addr {{addr}} -certs test_cert
  save: tx
- wait_for_datum: "{{tx}}"

# Используйте save_* хелперы для извлечения с валидацией
- cli: wallet info -w test
  save_wallet: addr

- cli: token_decl -token TEST -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
  save_hash: token_hash

# Организуйте в suites
tests/e2e/token/
├── token.yml                    # Suite descriptor
├── 001_test.yml
└── 002_test.yml
```

### ❌ НЕ ДЕЛАЙТЕ

```yaml
# Не повторяйте один setup в каждом тесте
setup:
  - tool: cert create test_cert sig_dil  # Используйте suite-level setup!

# Не используйте фиксированные waits
- wait: 30s                      # Сколько? Используйте wait_for_datum!

# Не сохраняйте весь вывод когда нужно конкретное значение
- cli: wallet info -w test
  save: full_output              # Используйте save_wallet!

# Не хардкодьте имя сети
- cli: token list -net stagenet  # Используйте -net {{network_name}} или auto-defaults
```

---

## Справочник

### Типы шагов - краткая таблица

| Шаг | Назначение | Ключевое поле |
|-----|-----------|---------------|
| CLIStep | CLI команда | `cli: command` |
| ToolStep | Tool команда | `tool: command` |
| RPCStep | JSON-RPC вызов | `rpc: method` |
| WaitStep | Простое ожидание | `wait: 5s` |
| WaitForDatumStep | Умное ожидание датума | `wait_for_datum: hash` |
| PythonStep | Python код | `python: \|` |
| BashStep | Bash скрипт | `bash: \|` |
| LoopStep | Повторение N раз | `loop: 5` |
| ForStep | Итерация по списку | `for: var in: list` |
| IfStep | Условие | `if: condition then:` |
| WhileStep | Цикл с условием | `while: condition` |
| SwitchStep | Switch/case | `switch: var cases:` |
| SetStep | Установка переменной | `set: var value:` |
| ConfigStep | Изменение конфига | `config: path set:` |
| NetworkWaitStep | Ожидание сети | `wait_network: online` |
| DockerOpStep | Docker операции | `docker_op: restart` |
| SnapshotStep | Работа со snapshot | `snapshot: create` |
| StepGroup | Группа с defaults | `group: name` |

### Типы проверок - краткая таблица

| Проверка | Назначение | Ключевое поле |
|----------|-----------|---------------|
| CLICheck | Проверка CLI вывода | `cli: command` |
| PythonCheck | Python assertions | `python: \|` |
| BashCheck | Bash exit code | `bash: \|` |
| RPCCheck | Проверка RPC результата | `rpc: method` |

---

## См. также

- **[Tutorial](Tutorial.md)** - Пошаговое руководство (7 уроков)
- **[Cookbook](Cookbook.md)** - Готовые рецепты для типовых задач
- **Реальные сценарии** - Изучите `tests/stage-env/scenarios/genesis/` для продвинутых паттернов
- **[СЛК модули](../../../../../.context/modules/testing/)** - Полный технический справочник

---

**Версия:** 2.1  
**Обновлено:** 2025-12-23  
**Язык:** Русский | [English](../../en/scenarios/Glossary.md)
