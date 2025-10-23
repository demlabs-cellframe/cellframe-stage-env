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
  - cli: token_decl -token {{token}} -total {{amount}}
  
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
- cli: token_decl -token TEST -total 1000000
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
  
  - cli: token_decl -token TEST -total 1000000
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

## CLI команды

### Wallet команды

#### `wallet new`
Создать новый кошелёк.

**Синтаксис:**
```yaml
- cli: wallet new -w <name>
```

**Параметры:**
- `-w <name>` - имя кошелька (обязательно)

**Пример:**
```yaml
- cli: wallet new -w my_wallet
  save: wallet_addr
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
Информация о кошельке.

**Синтаксис:**
```yaml
- cli: wallet info -w <name>
```

**Параметры:**
- `-w <name>` - имя кошелька (обязательно)

**Пример:**
```yaml
- cli: wallet info -w my_wallet
  save: wallet_details
```

---

#### `wallet export`
Экспортировать приватный ключ.

**Синтаксис:**
```yaml
- cli: wallet export -w <name>
```

**Пример:**
```yaml
- cli: wallet export -w my_wallet
  save: private_key
```

---

#### `wallet import`
Импортировать кошелёк из приватного ключа.

**Синтаксис:**
```yaml
- cli: wallet import -w <name> -key <key>
```

**Параметры:**
- `-w <name>` - имя нового кошелька
- `-key <key>` - приватный ключ

**Пример:**
```yaml
- cli: wallet import -w imported -key {{private_key}}
```

---

#### `wallet delete`
Удалить кошелёк.

**Синтаксис:**
```yaml
- cli: wallet delete -w <name>
```

**Пример:**
```yaml
- cli: wallet delete -w temp_wallet
```

---

### Token команды

#### `token_decl`
Декларировать новый токен.

**Синтаксис:**
```yaml
- cli: token_decl -token <name> -total <supply> [-flags <flags>] [-net <network>]
```

**Параметры:**
- `-token <name>` - имя токена (обязательно)
- `-total <supply>` - максимальный supply (обязательно)
- `-flags <flags>` - флаги токена (опционально)
- `-net <network>` - сеть (опционально, default: stagenet)

**Флаги:**
- `UTXO_BLOCKING_ENABLED` - включить блокировку UTXO
- `ALL_SENDER_FROZEN` - заморозить всех отправителей
- `ALL_RECEIVER_FROZEN` - заморозить всех получателей

**Примеры:**
```yaml
# Простой токен
- cli: token_decl -token SIMPLE -total 1000000

# С флагами
- cli: token_decl -token BLOCK -total 1000000 -flags UTXO_BLOCKING_ENABLED

# Несколько флагов
- cli: token_decl -token FROZEN -total 1000000 -flags "ALL_SENDER_FROZEN,ALL_RECEIVER_FROZEN"
```

---

#### `token_emit`
Эмитировать токены.

**Синтаксис:**
```yaml
- cli: token_emit -token <name> -value <amount> -addr <address>
```

**Параметры:**
- `-token <name>` - имя токена (обязательно)
- `-value <amount>` - количество (обязательно)
- `-addr <address>` - адрес получателя (обязательно)

**Пример:**
```yaml
- cli: token_emit -token TEST -value 100000 -addr {{wallet_addr}}
  save: emission_tx
  wait: 3s
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

#### `transfer`
Перевести токены.

**Синтаксис:**
```yaml
- cli: transfer -token <name> -to <address> -value <amount> [-from <address>]
```

**Параметры:**
- `-token <name>` - имя токена (обязательно)
- `-to <address>` - адрес получателя (обязательно)
- `-value <amount>` - количество (обязательно)
- `-from <address>` - адрес отправителя (опционально)

**Примеры:**
```yaml
# Простой трансфер
- cli: transfer -token TEST -to {{recipient}} -value 1000

# С указанием отправителя
- cli: transfer -token TEST -from {{sender}} -to {{recipient}} -value 1000
```

---

#### `tx_create`
Создать транзакцию.

**Синтаксис:**
```yaml
- cli: tx_create -token <name> -value <amount> [-from_emission <tx>] [-arbitrage]
```

**Параметры:**
- `-token <name>` - имя токена (обязательно)
- `-value <amount>` - количество (обязательно)
- `-from_emission <tx>` - создать из эмиссии (опционально)
- `-arbitrage` - арбитражная транзакция (опционально)

**Примеры:**
```yaml
# Простая транзакция
- cli: tx_create -token TEST -value 1000

# Из эмиссии
- cli: tx_create -token TEST -from_emission {{emission_tx}} -value 1000

# Арбитражная
- cli: tx_create -token TEST -value 1000 -arbitrage
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

