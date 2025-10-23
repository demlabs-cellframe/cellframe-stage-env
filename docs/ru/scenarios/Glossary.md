# Test Scenarios Glossary

**Полный справочник языка тест-сценариев Cellframe Node**

Этот документ содержит исчерпывающее описание всех возможностей языка YAML-сценариев. Используйте как справочник при написании тестов.

## 📚 Содержание

1. [Структура сценария](#структура-сценария)
2. [Метаданные](#метаданные)
3. [Конфигурация сети](#конфигурация-сети)
4. [Переменные](#переменные)
5. [Includes](#includes)
6. [Секции сценария](#секции-сценария)
7. [Типы шагов](#типы-шагов)
8. [CLI команды](#cli-команды)
9. [RPC вызовы](#rpc-вызовы)
10. [Проверки](#проверки)
11. [Циклы](#циклы)
12. [Ожидания](#ожидания)
13. [Выполнение на нодах](#выполнение-на-нодах)
14. [Таймауты](#таймауты)
15. [Специальные возможности](#специальные-возможности)

---

## Структура сценария

Полная структура YAML файла сценария:

```yaml
# === МЕТАДАННЫЕ (обязательно) ===
name: string                        # Название сценария
description: string                 # Описание теста
author: string                      # Автор (опционально)
tags: [string, ...]                # Теги (опционально)
version: string                     # Версия (опционально, default: "1.0")

# === INCLUDES (опционально) ===
includes:
  - path/to/template.yml           # Путь относительно сценария

# === ПЕРЕМЕННЫЕ (опционально) ===
variables:
  key: value                        # Предопределённые переменные

# === КОНФИГУРАЦИЯ СЕТИ (обязательно) ===
network:
  topology: string                  # Имя топологии
  nodes:                           # Список нод
    - name: string
      role: string
      validator: boolean
      ip: string
      port: integer

# === УСТАНОВКА ПАКЕТОВ (опционально) ===
packages:
  - node: string | [string]
    apt: [string]
  - node: string | [string]
    local: string
  - node: string | [string]
    url: string
    checksum: string

# === РАЗМЕЩЕНИЕ ФАЙЛОВ (опционально) ===
files:
  - node: string | [string]
    src: string
    dst: string
    mode: string
  - node: string | [string]
    content: string
    dst: string
    mode: string

# === ПОДГОТОВКА (опционально) ===
setup:
  - [test_step]

# === ОСНОВНОЙ ТЕСТ (обязательно) ===
test:
  - [test_step]

# === ПРОВЕРКИ (рекомендуется) ===
check:
  - [check_spec]

# === ОЧИСТКА (опционально, планируется) ===
cleanup:
  - [test_step]
```

---

## Метаданные

### `name`

**Тип:** `string` (обязательно)

**Описание:** Название сценария. Должно быть понятным и описательным.

**Примеры:**
```yaml
name: Token Transfer Test
name: UTXO Blocking Verification
name: Multi-Node Wallet Replication
```

**Рекомендации:**
- Используйте Title Case
- Будьте конкретны
- Избегайте аббревиатур без пояснений
- Максимум 80 символов

---

### `description`

**Тип:** `string` (обязательно)

**Описание:** Подробное описание что тестирует сценарий.

**Примеры:**
```yaml
description: Verifies that tokens can be transferred between wallets

description: |
  Tests UTXO blocking functionality:
  1. Create token with UTXO_BLOCKING_ENABLED
  2. Block specific UTXO
  3. Verify normal transactions fail
  4. Verify arbitrage transactions succeed
```

**Рекомендации:**
- Описывайте ЧТО тестируется, не КАК
- Используйте списки для многошаговых тестов
- Указывайте prerequisites если есть
- Упоминайте ожидаемые результаты

---

### `author`

**Тип:** `string` (опционально)

**Описание:** Имя или команда автора сценария.

**Примеры:**
```yaml
author: QA Team
author: John Doe
author: Blockchain Testing Team
```

---

### `tags`

**Тип:** `array[string]` (опционально)

**Описание:** Список тегов для категоризации и фильтрации сценариев.

**Примеры:**
```yaml
tags: [tokens, transfer, critical]
tags: [smoke, fast, basic]
tags: [utxo, blocking, integration, medium]
```

**Рекомендуемые категории тегов:**

**По функциональности:**
- `wallet` - операции с кошельками
- `tokens` - управление токенами
- `transfer` - трансферы
- `utxo` - UTXO операции
- `network` - сетевые операции
- `consensus` - консенсус
- `stake` - стейкинг

**По приоритету:**
- `critical` - критичные тесты
- `high` - высокий приоритет
- `medium` - средний приоритет
- `low` - низкий приоритет

**По типу:**
- `smoke` - smoke тесты
- `regression` - регрессионные тесты
- `integration` - интеграционные тесты
- `e2e` - end-to-end тесты
- `stress` - стресс-тесты
- `security` - тесты безопасности

**По длительности:**
- `fast` - < 1 минуты
- `medium` - 1-5 минут
- `slow` - > 5 минут

**По статусу:**
- `wip` - work in progress
- `draft` - черновик
- `stable` - стабильный
- `flaky` - нестабильный

---

### `version`

**Тип:** `string` (опционально, default: "1.0")

**Описание:** Версия сценария в формате semantic versioning.

**Примеры:**
```yaml
version: "1.0"      # Initial version
version: "1.1"      # Minor update
version: "2.0"      # Major rewrite
version: "2.1.3"    # Patch
```

---

## Конфигурация сети

### `network.topology`

**Тип:** `string` (обязательно)

**Описание:** Имя предопределённой топологии сети.

**Доступные топологии:**

#### `minimal`
- **Описание:** Минимальная сеть из 1 ноды
- **Ноды:** 1 root validator
- **Использование:** Быстрые тесты, базовые проверки

```yaml
network:
  topology: minimal
  nodes:
    - name: node1
      role: root
      validator: true
```

#### `default`
- **Описание:** Полная сеть из 7 нод
- **Ноды:** 3 validators + 4 full nodes
- **Использование:** Комплексные тесты, консенсус, репликация

```yaml
network:
  topology: default
  nodes:
    - name: node-1
      role: root
      validator: true
    - name: node-2
      role: master
      validator: true
    - name: node-3
      role: master
      validator: true
    - name: node-4
      role: full
    - name: node-5
      role: full
    - name: node-6
      role: full
    - name: node-7
      role: full
```

---

### `network.nodes`

**Тип:** `array[object]` (обязательно)

**Описание:** Список нод в сети с их параметрами.

**Структура объекта ноды:**

```yaml
- name: string           # Уникальное имя ноды (обязательно)
  role: string           # Роль в сети (обязательно)
  validator: boolean     # Является ли валидатором (опционально, default: false)
  ip: string            # Статический IP (опционально)
  port: integer         # Порт (опционально, default: 8079)
```

**Параметры:**

#### `name`
- **Тип:** `string` (обязательно)
- **Описание:** Уникальный идентификатор ноды
- **Формат:** alphanumeric, дефис, underscore
- **Примеры:** `node1`, `validator-1`, `full_node_3`

#### `role`
- **Тип:** `enum` (обязательно)
- **Описание:** Роль ноды в сети

**Доступные роли:**

| Роль | Описание | Когда использовать |
|------|----------|-------------------|
| `root` | Корневая нода, seed node | Первая нода в сети, bootstrap |
| `master` | Мастер нода, validator | Участие в консенсусе |
| `full` | Полная нода | Полная синхронизация без валидации |
| `light` | Лёгкая нода | Минимальная синхронизация |
| `archive` | Архивная нода | Полная история блокчейна |

#### `validator`
- **Тип:** `boolean` (опционально, default: `false`)
- **Описание:** Является ли нода валидатором в консенсусе
- **Примеры:**
```yaml
validator: true   # Нода участвует в консенсусе
validator: false  # Нода только синхронизирует
```

#### `ip`
- **Тип:** `string` (опционально)
- **Описание:** Статический IPv4 адрес ноды
- **Формат:** `XXX.XXX.XXX.XXX`
- **Default:** Auto-assigned из subnet
- **Примеры:**
```yaml
ip: 172.20.0.10
ip: 192.168.1.100
```

#### `port`
- **Тип:** `integer` (опционально, default: `8079`)
- **Описание:** Порт для P2P/HTTP коммуникаций
- **Диапазон:** 1024-65535
- **Примеры:**
```yaml
port: 8079   # Default Cellframe Node port
port: 9000   # Custom port
```

**Полный пример:**

```yaml
network:
  topology: custom
  nodes:
    # Root validator
    - name: validator-1
      role: root
      validator: true
      ip: 172.20.0.10
      port: 8079
    
    # Master validators
    - name: validator-2
      role: master
      validator: true
      ip: 172.20.0.11
    
    - name: validator-3
      role: master
      validator: true
      ip: 172.20.0.12
    
    # Full nodes
    - name: observer-1
      role: full
      validator: false
      ip: 172.20.0.20
    
    - name: observer-2
      role: full
      ip: 172.20.0.21
      port: 9000  # Custom port
```

---

## Переменные

### Определение переменных

**Секция:** `variables`

**Тип:** `object[string, any]`

**Описание:** Предопределённые переменные доступные во всём сценарии.

**Синтаксис:**
```yaml
variables:
  key1: value1
  key2: value2
  nested:
    subkey: subvalue
```

**Типы значений:**

```yaml
variables:
  # String
  token_name: MYTOKEN
  wallet_prefix: test_wallet
  
  # Integer
  supply: 1000000
  iterations: 10
  
  # Boolean
  enable_feature: true
  skip_checks: false
  
  # Array
  wallets: [wallet1, wallet2, wallet3]
  amounts: [100, 500, 1000]
  
  # Object
  config:
    min_value: 1000
    max_value: 10000
```

---

### Использование переменных

**Синтаксис:** `{{variable_name}}`

**Где можно использовать:**
- В командах CLI
- В параметрах RPC
- В проверках
- В других переменных

**Примеры:**

```yaml
variables:
  token: TEST
  amount: 1000

test:
  # В CLI командах
  - cli: token_decl -token {{token}} -total_supply {{amount}} -decimals 18 -signs_total 1 -signs_emission 1 -certs owner -net stagenet -chain zerochain
  
  # В проверках
  - cli: token info -token {{token}}
    contains: {{amount}}
  
  # Математика (ограниченная)
  - cli: transfer -value {{amount * 2}}
```

---

### Сохранение результатов в переменные

**Параметр:** `save: variable_name`

**Описание:** Сохраняет вывод команды в переменную для последующего использования.

**Примеры:**

```yaml
# Сохранить адрес кошелька
- cli: wallet new -w my_wallet
  save: wallet_addr

# Использовать сохранённый адрес
- cli: balance -addr {{wallet_addr}}

# Сохранить хэш токена
- cli: token_decl -token TEST -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs owner -net stagenet -chain zerochain
  save: token_hash

# Сохранить хэш транзакции
- cli: transfer -value 1000
  save: tx_hash

# Использовать в следующих командах
- cli: tx_info -tx {{tx_hash}}
```

---

### Специальные переменные

#### В циклах

**`{{i}}`** - индекс итерации (0-based)
```yaml
- loop: 5
  steps:
    - cli: echo "Index: {{i}}"
    # Output: Index: 0, Index: 1, ..., Index: 4
```

**`{{iteration}}`** - номер итерации (1-based)
```yaml
- loop: 5
  steps:
    - cli: wallet new -w wallet{{iteration}}
    # Creates: wallet1, wallet2, ..., wallet5
```

#### Математические выражения

**Поддерживаемые операции:**
- `+` - сложение
- `-` - вычитание
- `*` - умножение
- `/` - деление
- `%` - остаток от деления

**Примеры:**
```yaml
- loop: 10
  steps:
    - cli: transfer -value {{i * 100}}
    # Values: 0, 100, 200, ..., 900
    
    - cli: wallet new -w node{{(i % 3) + 1}}
    # Распределение по 3 нодам: node1, node2, node3, node1, ...
```

---

## Includes

### Синтаксис

```yaml
includes:
  - path/to/file1.yml
  - path/to/file2.yml
  - ../common/template.yml
```

**Описание:** Включает и объединяет содержимое других YAML файлов.

---

### Порядок объединения

1. Загружаются все `includes` в порядке указания
2. Применяется основной файл сценария
3. Основной файл **перезаписывает** значения из includes

---

### Правила слияния

#### Словари (dict)
Рекурсивно объединяются:

```yaml
# include.yml
network:
  topology: minimal

# main.yml
includes:
  - include.yml

network:
  nodes:
    - name: node1

# Результат:
network:
  topology: minimal        # Из include
  nodes:                   # Из main
    - name: node1
```

#### Списки (list)
Конкатенируются:

```yaml
# include.yml
setup:
  - cli: command1

# main.yml
includes:
  - include.yml

setup:
  - cli: command2

# Результат:
setup:
  - cli: command1   # Из include
  - cli: command2   # Из main
```

#### Скаляры
Основной файл перезаписывает:

```yaml
# include.yml
name: Included Name

# main.yml
includes:
  - include.yml

name: Main Name

# Результат:
name: Main Name   # Main перезаписывает include
```

---

### Относительные пути

Пути в `includes` относительны к **директории сценария**:

```
scenarios/
  common/
    network.yml
  features/
    subfolder/
      my_test.yml
```

В `my_test.yml`:
```yaml
includes:
  - ../../common/network.yml   # Относительный путь вверх и вниз
```

---

### Готовые шаблоны

**Расположение:** `scenarios/common/`

#### `network_minimal.yml`
```yaml
network:
  topology: minimal
  nodes:
    - name: node1
      role: root
      validator: true
```

**Использование:**
```yaml
includes:
  - common/network_minimal.yml
```

#### `network_full.yml`
```yaml
network:
  topology: default
  nodes:
    - name: node-1
      role: root
      validator: true
    # ... (7 nodes total)
```

**Использование:**
```yaml
includes:
  - common/network_full.yml
```

#### `wallet_setup.yml`
```yaml
setup:
  - cli: wallet new -w test_wallet
    save: wallet_addr
    wait: 1s
```

**Использование:**
```yaml
includes:
  - common/wallet_setup.yml

# Теперь доступна переменная {{wallet_addr}}
test:
  - cli: balance -addr {{wallet_addr}}
```

---

## Секции сценария

### `setup`

**Тип:** `array[test_step]` (опционально)

**Описание:** Подготовительные шаги, выполняются перед основным тестом.

**Назначение:**
- Создание ресурсов (кошельки, токены)
- Начальная конфигурация
- Предусловия теста

**Примеры:**
```yaml
setup:
  - cli: wallet new -w test_wallet
    save: wallet_addr
  
  - cli: token_decl -token TEST -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs owner -net stagenet -chain zerochain
    save: token_hash
    wait: 3s
  
  - cli: token_emit -token TEST -value 10000 -addr {{wallet_addr}}
    wait: 3s
```

**Best practices:**
- Используйте для создания начального состояния
- Сохраняйте важные значения в переменные
- Добавляйте `wait` после изменений состояния

---

### `test`

**Тип:** `array[test_step]` (обязательно)

**Описание:** Основные тестовые шаги, действия которые тестируем.

**Назначение:**
- Выполнение тестируемых операций
- Действия которые проверяются

**Примеры:**
```yaml
test:
  - cli: transfer -token TEST -to {{recipient}} -value 5000
    save: tx_hash
    expect: success
    wait: 3s
  
  - cli: token_update -token TEST -set_flags ALL_SENDER_FROZEN
    wait: 3s
```

---

### `check`

**Тип:** `array[check_spec]` (рекомендуется)

**Описание:** Проверки результатов, assertions.

**Назначение:**
- Верификация результатов
- Проверка состояния системы
- Валидация выходных данных

**Примеры:**
```yaml
check:
  - cli: balance -addr {{wallet_addr}} -token TEST
    contains: "5000"
  
  - cli: token info -token TEST
    contains: "ALL_SENDER_FROZEN"
  
  - cli: tx_info -tx {{tx_hash}}
    contains: "status: success"
```

**Best practices:**
- Всегда добавляйте проверки
- Проверяйте ключевые параметры
- Используйте конкретные значения

---

### `cleanup`

**Тип:** `array[test_step]` (опционально, планируется)

**Описание:** Очистка после теста.

**Примечание:** В текущей версии cleanup выполняется автоматически через `stage-env stop --volumes`.

---

## Типы шагов

### CLI Step

Выполнение команды cellframe-node-cli.

**Структура:**
```yaml
- cli: string             # Команда (обязательно)
  node: string            # Нода для выполнения (опционально, default: node-1)
  save: string            # Сохранить результат (опционально)
  wait: string            # Подождать после (опционально)
  expect: enum            # Ожидаемый результат (опционально, default: success)
  contains: string        # Проверить наличие текста (опционально)
  timeout: integer        # Таймаут в секундах (опционально, default: 30)
```

**Параметры:**

#### `cli`
- **Тип:** `string` (обязательно)
- **Описание:** Команда для cellframe-node-cli (без префикса `cellframe-node-cli`)
- **Примеры:**
```yaml
cli: version
cli: wallet new -w my_wallet
cli: token_decl -token TEST -total 1000000
```

#### `node`
- **Тип:** `string` (опционально, default: `node-1`)
- **Описание:** Имя ноды на которой выполнить команду
- **Примеры:**
```yaml
node: node-1
node: validator-2
node: observer-1
```

#### `save`
- **Тип:** `string` (опционально)
- **Описание:** Имя переменной для сохранения вывода
- **Примеры:**
```yaml
save: wallet_addr
save: token_hash
save: tx_result
```

#### `wait`
- **Тип:** `string` (опционально)
- **Описание:** Время ожидания после выполнения
- **Формат:** `<number><unit>` где unit: `ms`, `s`, `m`
- **Примеры:**
```yaml
wait: 100ms   # 100 миллисекунд
wait: 3s      # 3 секунды
wait: 2m      # 2 минуты
```

#### `expect`
- **Тип:** `enum` (опционально, default: `success`)
- **Описание:** Ожидаемый результат выполнения

**Значения:**
- `success` - команда должна завершиться успешно (exit code 0)
- `error` - команда должна завершиться с ошибкой (exit code != 0)
- `any` - любой результат допустим

**Примеры:**
```yaml
expect: success   # Успех обязателен
expect: error     # Ожидаем ошибку
expect: any       # Игнорируем результат
```

#### `contains`
- **Тип:** `string` (опционально)
- **Описание:** Подстрока которая должна присутствовать в выводе
- **Примеры:**
```yaml
contains: "Created"
contains: "Balance: 1000"
contains: {{wallet_addr}}
```

#### `timeout`
- **Тип:** `integer` (опционально, default: `30`)
- **Описание:** Максимальное время выполнения в секундах
- **Диапазон:** 1-3600
- **Примеры:**
```yaml
timeout: 30    # Default
timeout: 60    # Для долгих операций
timeout: 5     # Для быстрых операций
```

**Полный пример:**
```yaml
- cli: transfer -token TEST -to {{recipient}} -value 1000
  node: node-1
  save: tx_hash
  wait: 3s
  expect: success
  contains: "Transaction created"
  timeout: 60
```

---

### RPC Step

Выполнение JSON-RPC вызова.

**Структура:**
```yaml
- rpc: string              # Метод (обязательно)
  params: array            # Параметры (опционально, default: [])
  node: string             # Нода (опционально, default: node-1)
  save: string             # Сохранить результат (опционально)
  wait: string             # Подождать после (опционально)
  expect: enum             # Ожидаемый результат (опционально, default: success)
  timeout: integer         # Таймаут (опционально, default: 30)
```

**Параметры:**

#### `rpc`
- **Тип:** `string` (обязательно)
- **Описание:** Имя JSON-RPC метода
- **Примеры:**
```yaml
rpc: eth_blockNumber
rpc: eth_getBalance
rpc: net_version
```

#### `params`
- **Тип:** `array` (опционально, default: `[]`)
- **Описание:** Массив параметров метода
- **Примеры:**
```yaml
params: []
params: ["0x1234..."]
params: ["{{wallet_addr}}", "latest"]
```

**Полный пример:**
```yaml
- rpc: eth_getBalance
  params: ["{{wallet_addr}}", "latest"]
  node: node-1
  save: balance
  wait: 1s
  expect: success
  timeout: 30
```

---

### Wait Step

Пауза между шагами.

**Структура:**
```yaml
- wait: string   # Длительность (обязательно)
```

**Формат:** `<number><unit>`

**Единицы:**
- `ms` - миллисекунды
- `s` - секунды
- `m` - минуты

**Примеры:**
```yaml
- wait: 100ms
- wait: 3s
- wait: 2m
```

---

### Loop Step

Повторение шагов.

**Структура:**
```yaml
- loop: integer          # Количество итераций (обязательно)
  steps:                 # Шаги для повторения (обязательно)
    - [test_step]
```

**Параметры:**

#### `loop`
- **Тип:** `integer` (обязательно)
- **Описание:** Количество итераций
- **Диапазон:** 1-10000
- **Примеры:**
```yaml
loop: 10
loop: 100
loop: {{iterations_count}}
```

#### `steps`
- **Тип:** `array[test_step]` (обязательно)
- **Описание:** Список шагов для повторения
- **Примеры:**
```yaml
steps:
  - cli: wallet new -w wallet{{iteration}}
  - wait: 500ms
```

**Доступные переменные:**
- `{{i}}` - индекс (0, 1, 2, ...)
- `{{iteration}}` - номер (1, 2, 3, ...)

**Примеры:**

```yaml
# Простой цикл
- loop: 5
  steps:
    - cli: wallet new -w wallet{{iteration}}

# С математикой
- loop: 10
  steps:
    - cli: transfer -value {{i * 100}}
    - wait: 1s

# Вложенные циклы
- loop: 3
  steps:
    - loop: 5
      steps:
        - cli: operation{{i}}
```

---

### Python Step

Выполнение Python кода с доступом к контексту сценария.

**Структура:**
```yaml
- python: string           # Python код (обязательно)
  save: string             # Сохранить result (опционально)
  description: string      # Описание шага (опционально)
```

**Параметры:**

#### `python`
- **Тип:** `string` (обязательно)
- **Описание:** Python код для выполнения
- **Доступ к контексту:**
  - `ctx.get_variable('name')` - получить переменную
  - `ctx.set_variable('name', value)` - установить переменную
  - `ctx.variables` - словарь всех переменных
  - `result` - переменная для сохранения через `save:`
- **Библиотеки:** Полный доступ к Python стандартной библиотеке

#### `save`
- **Тип:** `string` (опционально)
- **Описание:** Сохранить значение `result` в переменную
- **Примечание:** В коде Python установите `result = значение`

#### `description`
- **Тип:** `string` (опционально)
- **Описание:** Человекочитаемое описание шага

**Примеры:**

```yaml
# Простая обработка данных
- python: |
    addr = ctx.get_variable('wallet_addr')
    result = addr.upper()
  save: uppercase_addr
  description: "Convert address to uppercase"

# Валидация с assert
- python: |
    balance = ctx.get_variable('balance')
    assert balance > 0, "Balance must be positive"
  description: "Validate balance"

# Парсинг вывода CLI
- python: |
    import re
    output = ctx.get_variable('wallet_info')
    match = re.search(r'balance:\s*(\d+)', output)
    if match:
        result = int(match.group(1))
    else:
        result = 0
  save: parsed_balance
  description: "Parse balance from wallet info"

# Работа со списками
- python: |
    tokens = ctx.get_variable('token_list').split('\n')
    valid_tokens = [t for t in tokens if 'TEST' in t]
    result = len(valid_tokens)
  save: test_tokens_count
  description: "Count TEST tokens"

# Установка переменных
- python: |
    # Можно устанавливать переменные напрямую
    ctx.set_variable('computed_fee', 0.01)
    ctx.set_variable('max_retries', 3)
  description: "Set computed parameters"
```

**Реальные примеры из тестов:**

```yaml
# Проверка сетевых линков (tests/e2e/net/003_net_links.yml)
- python: |
    links = ctx.get_variable('link_list')
    has_links = any(word in links.lower() 
                    for word in ['active', 'established', 'link'])
    assert has_links, "Should have active links"
  description: "Verify network links"

# Проверка списка токенов (tests/e2e/token/006_token_with_flags.yml)
- python: |
    tokens = ctx.get_variable('token_list')
    assert 'FLAGTEST1' in tokens, "FLAGTEST1 should be in list"
    assert 'FLAGTEST2' in tokens, "FLAGTEST2 should be in list"
  description: "Verify token flags"
```

**Best practices:**
- Используйте Python для сложной обработки данных
- Комбинируйте с CLI шагами: CLI получает данные → Python обрабатывает
- Добавляйте `description` для понимания логики
- Используйте `assert` с информативными сообщениями
- Избегайте слишком сложной логики - разбивайте на несколько шагов

---

### Bash Step

Выполнение Bash скрипта на указанной ноде.

**Структура:**
```yaml
- bash: string             # Bash скрипт (обязательно)
  node: string             # Нода для выполнения (опционально, default: node1)
  save: string             # Сохранить stdout (опционально)
  expect: enum             # Ожидаемый результат (опционально, default: success)
  timeout: integer         # Таймаут в секундах (опционально, default: 30)
  description: string      # Описание шага (опционально)
```

**Параметры:**

#### `bash`
- **Тип:** `string` (обязательно)
- **Описание:** Bash скрипт для выполнения на ноде
- **Возможности:**
  - Полный доступ к shell командам
  - Pipes, redirects, переменные окружения
  - Доступ к файловой системе ноды
  - Поддержка подстановки переменных: `{{variable_name}}`

#### `node`
- **Тип:** `string` (опционально, default: `node1`)
- **Описание:** Имя ноды на которой выполнить скрипт
- **Примеры:**
```yaml
node: node1
node: node-2
node: validator-1
```

#### `save`
- **Тип:** `string` (опционально)
- **Описание:** Сохранить stdout скрипта в переменную

#### `expect`
- **Тип:** `enum[success, error, any]` (опционально, default: `success`)
- **Описание:** Ожидаемый результат выполнения
  - `success` - exit code 0
  - `error` - exit code != 0
  - `any` - любой exit code

#### `timeout`
- **Тип:** `integer` (опционально, default: 30)
- **Описание:** Таймаут выполнения в секундах

#### `description`
- **Тип:** `string` (опционально)
- **Описание:** Человекочитаемое описание шага

**Примеры:**

```yaml
# Простая команда
- bash: |
    ls -la /opt/cellframe-node/var
  node: node1
  description: "List node data directory"

# Сбор системной информации
- bash: |
    mem=$(free -m | awk 'NR==2{print $3}')
    disk=$(df -h / | awk 'NR==2{print $5}' | tr -d '%')
    echo "Memory: ${mem}MB, Disk: ${disk}%"
  node: node1
  save: system_metrics
  description: "Collect system metrics"

# Проверка файла с expect
- bash: |
    if [ -f /opt/cellframe-node/var/run/cellframe-node.pid ]; then
      cat /opt/cellframe-node/var/run/cellframe-node.pid
      exit 0
    else
      exit 1
    fi
  node: node1
  expect: success
  description: "Check if node is running"

# Использование переменных
- bash: |
    echo "Working with wallet: {{wallet_addr}}"
    echo "Token: {{token_ticker}}"
    # Переменные подставляются автоматически
  node: node1
  description: "Process with variables"

# Сложный скрипт с таймаутом
- bash: |
    #!/bin/bash
    set -e
    
    # Wait for condition
    for i in {1..30}; do
      if [ -f /tmp/ready ]; then
        echo "Ready!"
        exit 0
      fi
      sleep 1
    done
    
    echo "Timeout waiting for ready"
    exit 1
  node: node1
  timeout: 60
  expect: success
  description: "Wait for ready flag"
```

**Best practices:**
- Используйте Bash для системных операций и проверок
- Проверяйте файлы, процессы, сетевые подключения
- Собирайте системные метрики
- Используйте `set -e` для автоматического выхода при ошибках
- Добавляйте `timeout` для long-running операций
- Используйте `save` для передачи результатов в Python или другие шаги

---

## CLI команды

### Wallet команды

#### `wallet new`
Создать новый кошелёк.

**Синтаксис:**
```yaml
- cli: wallet new -w <wallet_name> [-sign <sign_type>] [-restore <hex_value>] 
        [-restore_legacy <restore_string>] [-net <net_name>] [-force] [-password <password>]
```

**Обязательные параметры:**
- `-w <name>` - имя кошелька

**Опциональные параметры:**
- `-sign <sign_type>` - тип подписи (по умолчанию: sig_dil)
- `-restore <hex_value>` - восстановить из hex значения приватного ключа
- `-restore_legacy <restore_string>` - восстановить из legacy формата
- `-net <net_name>` - привязать к конкретной сети
- `-force` - перезаписать существующий кошелёк
- `-password <password>` - установить пароль для кошелька

**Примеры:**
```yaml
# Простое создание
- cli: wallet new -w my_wallet
  save: wallet_addr

# С паролем
- cli: wallet new -w secure_wallet -password mypass123

# Восстановление из hex
- cli: wallet new -w restored -restore {{private_key_hex}}
```

---

#### `wallet list`
Список кошельков.

**Синтаксис:**
```yaml
- cli: wallet list
```

**Пример:**
```yaml
- cli: wallet list
  contains: my_wallet
```

---

#### `wallet info`
Информация о кошельке или адресе.

**Синтаксис:**
```yaml
- cli: wallet info {-addr <addr> | -w <wallet_name>} -net <net_name>
```

**Параметры:**
- `-w <name>` - имя кошелька (один из: -w или -addr)
- `-addr <address>` - адрес кошелька (один из: -w или -addr)
- `-net <network>` - имя сети (обязательно)

**Примеры:**
```yaml
# По имени кошелька
- cli: wallet info -w my_wallet -net stagenet
  save: wallet_details

# По адресу
- cli: wallet info -addr {{wallet_addr}} -net stagenet
```

---

### Token команды

#### `token_decl`
Декларировать новый токен.

**Синтаксис:**
```yaml
- cli: token_decl -token <ticker> -total_supply <amount> -decimals <value> 
        -signs_total <count> -signs_emission <count> -certs <cert_list> 
        -net <network> -chain <chain> [-flags <flags>] [-H <hex|base58>]
```

**Обязательные параметры:**
- `-token <ticker>` - тикер токена
- `-total_supply <amount>` - максимальная эмиссия (256-bit число)
- `-decimals <value>` - знаков после запятой (должно быть 18)
- `-signs_total <count>` - общее количество подписей
- `-signs_emission <count>` - минимум подписей для эмиссии
- `-certs <cert_list>` - список сертификатов (через запятую)
- `-net <network>` - имя сети
- `-chain <chain>` - имя цепочки

**Опциональные параметры:**
- `-H <hex|base58>` - формат вывода хэша (default: hex)
- `-type <private|native>` - тип токена (default: native)
- `-flags <flags>` - флаги токена (через запятую)

**Флаги:**
- `UTXO_BLOCKING_ENABLED` - включить блокировку UTXO
- `ALL_SENDER_FROZEN` - заморозить всех отправителей
- `ALL_RECEIVER_FROZEN` - заморозить всех получателей
- `ALL_SENDER_ALLOWED` - разрешить всем отправителям
- `ALL_RECEIVER_ALLOWED` - разрешить всем получателям

**Примеры:**
```yaml
# Простой токен
- cli: token_decl -token SIMPLE -total_supply 1000000 -decimals 18 
        -signs_total 1 -signs_emission 1 -certs owner 
        -net stagenet -chain zerochain

# С флагами
- cli: token_decl -token BLOCK -total_supply 1000000 -decimals 18 
        -signs_total 1 -signs_emission 1 -certs owner 
        -net stagenet -chain zerochain 
        -flags UTXO_BLOCKING_ENABLED

# Несколько флагов
- cli: token_decl -token FROZEN -total_supply 1000000 -decimals 18 
        -signs_total 1 -signs_emission 1 -certs owner 
        -net stagenet -chain zerochain 
        -flags "ALL_SENDER_FROZEN,ALL_RECEIVER_FROZEN"
```

---

#### `token_emit`
Эмитировать токены.

**Синтаксис:**
```yaml
# Создание новой эмиссии
- cli: token_emit -token <mempool_token_ticker> -emission_value <value> -addr <addr> 
        -net <net_name> -certs <cert_list> [-chain_emission <chain_name>]

# Подпись существующей эмиссии
- cli: token_emit sign -emission <hash> -net <net_name> -certs <cert_list>
```

**Параметры (создание эмиссии):**
- `-token <ticker>` - тикер токена в mempool (обязательно)
- `-emission_value <amount>` - количество токенов для эмиссии (обязательно)
- `-addr <address>` - адрес получателя (обязательно)
- `-net <network>` - имя сети (обязательно)
- `-certs <cert_list>` - список сертификатов для подписи (обязательно)
- `-chain_emission <chain>` - цепочка для эмиссии (опционально)

**Параметры (подпись эмиссии):**
- `sign` - режим подписи существующей эмиссии
- `-emission <hash>` - хэш эмиссии для подписи (обязательно)
- `-net <network>` - имя сети (обязательно)
- `-certs <cert_list>` - список сертификатов для подписи (обязательно)

**Примеры:**
```yaml
# Создание эмиссии
- cli: token_emit -token TEST -emission_value 100000 -addr {{wallet_addr}} 
        -net stagenet -certs owner
  save: emission_tx
  wait: 3s

# Подпись эмиссии
- cli: token_emit sign -emission {{emission_hash}} -net stagenet -certs validator
  wait: 2s
```

---

#### `token_update`
Обновить параметры токена.

**Синтаксис:**
```yaml
- cli: token_update -token <name> [-set_flags <flags>] [-unset_flags <flags>] [-utxo_blocked_add <utxo>] [-utxo_blocked_remove <utxo>]
```

**Параметры:**
- `-token <name>` - имя токена (обязательно)
- `-set_flags <flags>` - установить флаги
- `-unset_flags <flags>` - снять флаги
- `-utxo_blocked_add <utxo>` - заблокировать UTXO
- `-utxo_blocked_remove <utxo>` - разблокировать UTXO

**Примеры:**
```yaml
# Установить флаг
- cli: token_update -token TEST -set_flags ALL_SENDER_FROZEN

# Снять флаг
- cli: token_update -token TEST -unset_flags ALL_SENDER_FROZEN

# Заблокировать UTXO
- cli: token_update -token TEST -utxo_blocked_add {{tx_hash}}:0

# Разблокировать UTXO
- cli: token_update -token TEST -utxo_blocked_remove {{tx_hash}}:0
```

---

#### `token list`
Список токенов.

**Синтаксис:**
```yaml
- cli: token list
```

**Пример:**
```yaml
- cli: token list
  contains: MYTOKEN
```

---

#### `token info`
Информация о токене.

**Синтаксис:**
```yaml
- cli: token info -token <name>
```

**Пример:**
```yaml
- cli: token info -token TEST
  save: token_details
```

---

### Transaction команды

#### `tx_create`
Создать транзакцию (перевод токенов).

**Синтаксис:**
```yaml
- cli: tx_create -net <net_name> -token <token_ticker> -value <amount> 
        -to_addr <addr> -from_wallet <wallet_name> -fee <fee_value>
        [-chain <chain_name>] [-lock_before <unlock_time>] [-arbitrage]
```

**Обязательные параметры:**
- `-net <net_name>` - имя сети
- `-token <token_ticker>` - тикер токена
- `-value <amount>` - количество токенов
- `-to_addr <addr>` - адрес получателя
- `-from_wallet <wallet_name>` - кошелёк отправителя (или -from_emission)
- `-fee <fee_value>` - комиссия транзакции

**Опциональные параметры:**
- `-chain <chain_name>` - имя цепочки (по умолчанию: main)
- `-lock_before <unlock_time>` - заблокировать до времени (формат: RFC822 или YYMMDD)
- `-arbitrage` - арбитражная транзакция (требует подписи владельца токена, обходит UTXO блокировку)
- `-from_emission <emission_hash>` - создать из эмиссии (альтернатива -from_wallet)

**Примеры:**
```yaml
# Простая транзакция (перевод токенов)
- cli: tx_create -net stagenet -token TEST -value 1000 
        -to_addr {{recipient_addr}} -from_wallet my_wallet -fee 0.01

# Транзакция с блокировкой по времени
- cli: tx_create -net stagenet -token TEST -value 5000 
        -to_addr {{recipient}} -from_wallet sender -fee 0.01 
        -lock_before "2025-12-31"

# Арбитражная транзакция (обход UTXO блокировки)
- cli: tx_create -net stagenet -token BLOCK -value 1000 
        -to_addr {{arbitrage_addr}} -from_wallet owner -fee 0.01 
        -arbitrage

# Из эмиссии
- cli: tx_create -net stagenet -token TEST -value 10000 
        -to_addr {{first_recipient}} -from_emission {{emission_hash}} 
        -cert owner -fee 0.01
```

---

#### `tx_info`
Информация о транзакции.

**Синтаксис:**
```yaml
- cli: tx_info -tx <hash>
```

**Пример:**
```yaml
- cli: tx_info -tx {{tx_hash}}
  contains: "status: success"
```

---

#### `tx_history`
История транзакций.

**Синтаксис:**
```yaml
- cli: tx_history [-limit <N>]
```

**Параметры:**
- `-limit <N>` - максимум транзакций (опционально)

**Пример:**
```yaml
- cli: tx_history -limit 100
  save: history
```

---

#### `balance`
Получить баланс.

**Синтаксис:**
```yaml
- cli: balance -addr <address> [-token <name>]
```

**Параметры:**
- `-addr <address>` - адрес кошелька (обязательно)
- `-token <name>` - конкретный токен (опционально)

**Примеры:**
```yaml
# Баланс всех токенов
- cli: balance -addr {{wallet_addr}}

# Баланс конкретного токена
- cli: balance -addr {{wallet_addr}} -token TEST
  contains: "1000"
```

---

### Network команды

#### `net get status`
Статус сети.

**Синтаксис:**
```yaml
- cli: net get status -net <network>
```

**Пример:**
```yaml
- cli: net get status -net stagenet
  contains: "NET_STATE_ONLINE"
```

---

#### `node list`
Список нод.

**Синтаксис:**
```yaml
- cli: node list -net <network>
```

**Пример:**
```yaml
- cli: node list -net stagenet
  save: nodes_list
```

---

#### `node info`
Информация о ноде.

**Синтаксис:**
```yaml
- cli: node info -net <network> -addr <address>
```

**Пример:**
```yaml
- cli: node info -net stagenet -addr {{node_addr}}
```

---

### Validator команды

#### `srv_stake order create validator`
Создать validator order.

**Синтаксис:**
```yaml
- cli: srv_stake order create validator -net <network> -value_min <min> -value_max <max> -tax <percent> -cert <cert> -node_addr <addr> -H hex
```

**Параметры:**
- `-net <network>` - сеть
- `-value_min <min>` - минимальная ставка
- `-value_max <max>` - максимальная ставка
- `-tax <percent>` - комиссия в процентах
- `-cert <cert>` - сертификат валидатора
- `-node_addr <addr>` - адрес ноды
- `-H hex` - формат вывода

**Пример:**
```yaml
- cli: srv_stake order create validator -net stagenet -value_min 1000 -value_max 10000 -tax 10 -cert pvt.stagenet.master.0 -node_addr {{validator_addr}} -H hex
  save: order_hash
```

---

## Проверки

### CLI Check

Проверка вывода CLI команды.

**Структура:**
```yaml
- cli: string              # Команда (обязательно)
  node: string             # Нода (опционально, default: node-1)
  contains: string         # Должно содержать (опционально)
  not_contains: string     # НЕ должно содержать (опционально)
  equals: string           # Точное совпадение (опционально)
  timeout: integer         # Таймаут (опционально, default: 30)
```

**Параметры:**

#### `contains`
- **Тип:** `string` (опционально)
- **Описание:** Подстрока которая должна присутствовать в выводе
- **Примеры:**
```yaml
contains: "Balance: 1000"
contains: {{wallet_addr}}
contains: "status: success"
```

#### `not_contains`
- **Тип:** `string` (опционально)
- **Описание:** Подстрока которой НЕ должно быть в выводе
- **Примеры:**
```yaml
not_contains: error
not_contains: failed
not_contains: "insufficient funds"
```

#### `equals`
- **Тип:** `string` (опционально)
- **Описание:** Вывод должен точно совпадать
- **Примеры:**
```yaml
equals: "connected"
equals: "Balance: 1000"
```

**Примеры:**

```yaml
check:
  # Проверить наличие
  - cli: wallet list
    contains: my_wallet
  
  # Проверить отсутствие
  - cli: token info -token TEST
    not_contains: error
  
  # Точное совпадение
  - cli: net status
    equals: connected
  
  # С переменными
  - cli: balance -addr {{wallet_addr}}
    contains: "{{expected_balance}}"
```

---

### RPC Check

Проверка результата JSON-RPC.

**Структура:**
```yaml
- rpc: string               # Метод (обязательно)
  params: array             # Параметры (опционально, default: [])
  node: string              # Нода (опционально, default: node-1)
  result_contains: any      # Результат должен содержать (опционально)
  result_equals: any        # Результат должен равняться (опционально)
  timeout: integer          # Таймаут (опционально, default: 30)
```

**Примеры:**

```yaml
check:
  # Проверить формат
  - rpc: net_version
    result_contains: "1"
  
  # Точное значение
  - rpc: eth_chainId
    result_equals: "0x1"
  
  # С переменными
  - rpc: eth_getBalance
    params: ["{{wallet_addr}}"]
    result_contains: "0x"
```

---

### Python Check

Проверка условий с помощью Python кода.

**Структура:**
```yaml
- python: string           # Python код для проверки (обязательно)
  description: string      # Описание проверки (опционально)
```

**Параметры:**

#### `python`
- **Тип:** `string` (обязательно)
- **Описание:** Python код для выполнения проверки
- **Правила:**
  - Любое исключение (exception) = проверка провалена
  - Нет исключений = проверка прошла
  - Используйте `assert` для проверок с сообщениями
  - Доступ к контексту через `ctx`

#### `description`
- **Тип:** `string` (опционально)
- **Описание:** Человекочитаемое описание проверки

**Примеры:**

```yaml
check:
  # Простая проверка значения
  - python: |
      balance = ctx.get_variable('balance')
      assert balance > 0, "Balance must be positive"
    description: "Verify positive balance"
  
  # Валидация формата адреса
  - python: |
      addr = ctx.get_variable('wallet_addr')
      assert addr, "Wallet address should not be empty"
      assert '::' in addr, "Address should contain :: separator"
      assert len(addr) > 10, "Address too short"
    description: "Wallet address format is valid"
  
  # Проверка списка
  - python: |
      tokens = ctx.get_variable('token_list')
      assert 'TEST' in tokens, "TEST token should be in list"
      assert 'DEMO' in tokens, "DEMO token should be in list"
    description: "Verify token list"
  
  # Сложная проверка с множественными условиями
  - python: |
      links = ctx.get_variable('link_list')
      has_links = any(word in links.lower() 
                      for word in ['active', 'established', 'link'])
      assert has_links, "Should have active network links"
      assert 'error' not in links.lower(), "Should not contain errors"
    description: "Verify network connectivity"
  
  # Проверка диапазона
  - python: |
      value = ctx.get_variable('parsed_value')
      assert 100 <= value <= 1000, f"Value {value} out of range [100, 1000]"
    description: "Verify value range"
  
  # Проверка с регулярным выражением
  - python: |
      import re
      status = ctx.get_variable('status')
      pattern = r'^NET_STATE_(ONLINE|SYNC)'
      assert re.match(pattern, status), f"Invalid status: {status}"
    description: "Verify status format"
```

**Реальные примеры из тестов:**

```yaml
# Проверка сетевого статуса (tests/e2e/net/002_net_status.yml)
- python: |
    status = ctx.get_variable('net_status')
    assert 'status' in status.lower() or 'state' in status.lower(), \
      "Status should contain status information"
  description: "Network status is valid"

# Проверка адреса кошелька (tests/functional/wallet/002_wallet_info.yml)
- python: |
    addr = ctx.get_variable('wallet_addr')
    assert addr, "Wallet address should not be empty"
    assert '::' in addr, "Address should contain :: separator"
  description: "Wallet address format is valid"

# Проверка токенов с флагами (tests/e2e/token/006_token_with_flags.yml)
- python: |
    tokens = ctx.get_variable('token_list')
    assert 'FLAGTEST1' in tokens, "FLAGTEST1 should be in list"
    assert 'FLAGTEST2' in tokens, "FLAGTEST2 should be in list"
  description: "Verify tokens with flags"
```

**Best practices:**
- Используйте информативные сообщения в `assert`
- Проверяйте одно логическое условие на один check
- Используйте `description` для документирования проверки
- Для сложных проверок разбивайте на несколько checks
- Добавляйте контекст в сообщения об ошибках (f-strings)

---

### Bash Check

Проверка условий с помощью Bash скрипта.

**Структура:**
```yaml
- bash: string             # Bash скрипт для проверки (обязательно)
  node: string             # Нода для выполнения (опционально, default: node1)
  description: string      # Описание проверки (опционально)
  timeout: integer         # Таймаут в секундах (опционально, default: 30)
```

**Параметры:**

#### `bash`
- **Тип:** `string` (обязательно)
- **Описание:** Bash скрипт для выполнения проверки
- **Правила:**
  - Exit code 0 = проверка прошла
  - Exit code != 0 = проверка провалена
  - Используйте стандартные shell команды и условия

#### `node`
- **Тип:** `string` (опционально, default: `node1`)
- **Описание:** Имя ноды на которой выполнить проверку

#### `description`
- **Тип:** `string` (опционально)
- **Описание:** Человекочитаемое описание проверки

#### `timeout`
- **Тип:** `integer` (опционально, default: 30)
- **Описание:** Таймаут выполнения в секундах

**Примеры:**

```yaml
check:
  # Проверка существования файла
  - bash: |
      [ -f /opt/cellframe-node/var/run/cellframe-node.pid ] && exit 0 || exit 1
    node: node1
    description: "Verify node process is running"
  
  # Проверка содержимого файла
  - bash: |
      if grep -q "ONLINE" /opt/cellframe-node/var/log/cellframe-node.log; then
        exit 0
      else
        exit 1
      fi
    node: node1
    description: "Verify node reached ONLINE state"
  
  # Проверка свободной памяти
  - bash: |
      mem=$(free -m | awk 'NR==2{print $4}')
      if [ $mem -gt 100 ]; then
        exit 0
      else
        echo "Low memory: ${mem}MB"
        exit 1
      fi
    node: node1
    description: "Verify sufficient free memory"
  
  # Проверка свободного места на диске
  - bash: |
      disk=$(df -h / | awk 'NR==2{print $5}' | tr -d '%')
      if [ $disk -lt 90 ]; then
        exit 0
      else
        echo "Disk usage too high: ${disk}%"
        exit 1
      fi
    node: node1
    description: "Verify disk space"
  
  # Проверка сетевого порта
  - bash: |
      if netstat -tuln | grep -q ":8079"; then
        echo "Port 8079 is listening"
        exit 0
      else
        echo "Port 8079 is not listening"
        exit 1
      fi
    node: node1
    description: "Verify node port is open"
  
  # Комплексная проверка с переменными
  - bash: |
      # Используем переменные сценария
      expected_file="/opt/cellframe-node/var/lib/wallet/{{wallet_name}}"
      
      if [ -f "$expected_file" ]; then
        size=$(stat -f%z "$expected_file" 2>/dev/null || stat -c%s "$expected_file")
        if [ $size -gt 0 ]; then
          echo "Wallet file exists and valid"
          exit 0
        fi
      fi
      
      echo "Wallet file check failed"
      exit 1
    node: node1
    timeout: 10
    description: "Verify wallet file"
```

**Best practices:**
- Используйте `exit 0` для успеха, `exit 1` для провала
- Добавляйте информативные `echo` перед `exit 1`
- Используйте стандартные команды (доступные в минимальных образах)
- Проверяйте системные ресурсы и файлы
- Используйте переменные сценария для параметризации
- Добавляйте `timeout` для потенциально долгих проверок

---

## Таймауты

### Глобальные таймауты

Настраиваются в `tests/stage-env.cfg`:

```ini
[timeouts]
startup = 600          # Запуск сети (секунды)
health_check = 600     # Health check (секунды)
command = 30           # Команды по умолчанию (секунды)
```

### Per-command таймауты

Переопределяются в каждом шаге:

```yaml
- cli: long_operation
  timeout: 120   # 2 минуты

- rpc: slow_method
  timeout: 60    # 1 минута
```

---

## Специальные возможности

### Packages Installation

Установка пакетов в ноды перед тестом.

**Структура:**
```yaml
packages:
  - node: string | [string]   # Целевые ноды
    apt: [string]             # APT пакеты
  
  - node: string | [string]
    local: string             # Локальный .deb файл
  
  - node: string | [string]
    url: string               # URL пакета
    checksum: string          # SHA256 checksum
```

**Примеры:**

```yaml
packages:
  # APT пакеты
  - node: node-1
    apt:
      - curl
      - jq
      - htop
  
  # На несколько нод
  - node: [node-1, node-2, node-3]
    apt: [vim, net-tools]
  
  # Локальный пакет
  - node: node-1
    local: ../build/cellframe-node.deb
  
  # Из URL
  - node: node-1
    url: https://example.com/package.deb
    checksum: sha256:abc123...
```

---

### File Placement

Копирование файлов в ноды.

**Структура:**
```yaml
files:
  - node: string | [string]    # Целевые ноды
    src: string                # Источник на хосте
    dst: string                # Путь в ноде
    mode: string               # Права доступа
  
  - node: string | [string]
    content: string            # Inline контент
    dst: string
    mode: string
```

**Примеры:**

```yaml
files:
  # Копирование файла
  - node: node-1
    src: configs/custom.cfg
    dst: /opt/cellframe-node/etc/custom.cfg
    mode: "0644"
  
  # На несколько нод
  - node: [node-1, node-2]
    src: scripts/init.sh
    dst: /usr/local/bin/init.sh
    mode: "0755"
  
  # Inline контент
  - node: node-1
    content: |
      [network]
      name=testnet
      enabled=true
    dst: /opt/cellframe-node/etc/testnet.cfg
  
  # С переменными
  - node: node-1
    content: "wallet={{wallet_addr}}"
    dst: /tmp/wallet.conf
```

---

## Best Practices

### Именование

**✅ DO:**
```yaml
name: Token Transfer Between Wallets Test
- cli: wallet new -w sender_wallet
  save: sender_address
```

**❌ DON'T:**
```yaml
name: test1
- cli: wallet new -w w1
  save: a1
```

---

### Структура

**✅ DO:**
```yaml
setup:
  - cli: preparation

test:
  - cli: action

check:
  - cli: verification
```

**❌ DON'T:**
```yaml
test:
  - cli: preparation
  - cli: action
  - cli: verification   # Используйте check секцию
```

---

### Wait Times

**✅ DO:**
```yaml
- cli: token_emit
  wait: 3s   # Достаточно для обработки
```

**❌ DON'T:**
```yaml
- cli: token_emit
  wait: 30s  # Слишком долго

- cli: token_emit
  # wait отсутствует - может не успеть
```

---

### Проверки

**✅ DO:**
```yaml
test:
  - cli: transfer -value 1000
    expect: success

check:
  - cli: balance
    contains: "1000"
```

**❌ DON'T:**
```yaml
test:
  - cli: transfer -value 1000
  # Нет проверок результата
```

---

### Переменные

**✅ DO:**
```yaml
- cli: wallet new -w sender
  save: sender_addr

- cli: transfer -to {{sender_addr}}
```

**❌ DON'T:**
```yaml
- cli: wallet new -w sender
  # Не сохранили адрес

- cli: transfer -to 0xABC...  # Копипаста
```

---

## См. также

- **[Tutorial](Tutorial.md)** - Пошаговое обучение
- **[Cookbook](Cookbook.md)** - Готовые рецепты
- `scenarios/features/` - Примеры реальных тестов
- `scenarios/common/` - Готовые шаблоны

---

**Версия документа:** 2.0
**Последнее обновление:** 2025-10-23

Для вопросов и предложений создавайте issues в репозитории проекта.



---

**Язык:** Русский | [English](../../en/scenarios/Glossary.md)
