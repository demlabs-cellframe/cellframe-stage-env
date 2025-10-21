# Scenario Groups Documentation
# Документация по группировке сценариев

## 🎯 Концепция

Stage Environment поддерживает **иерархическую организацию тестовых сценариев**:

1. **Scenario** - отдельный тестовый сценарий (файл `.yml`)
2. **Suite** - набор сценариев с общей топологией сети (файл `suite.yml`)
3. **Group** - группа наборов для функциональных областей (файл `group.yml`)

## 📁 Структура директорий

```
scenarios/
├── suites/                        # Наборы сценариев
│   ├── token_operations/          # Suite: операции с токенами
│   │   ├── suite.yml              # Определение набора
│   │   ├── common_setup.yml       # Общий setup
│   │   ├── common_cleanup.yml     # Общий cleanup
│   │   ├── 01_token_creation.yml  # Сценарий #1
│   │   ├── 02_token_emission.yml  # Сценарий #2
│   │   └── 03_token_transfer.yml  # Сценарий #3
│   │
│   ├── consensus/                 # Suite: консенсус
│   │   ├── suite.yml
│   │   ├── block_validation.yml
│   │   └── fork_resolution.yml
│   │
│   └── network/                   # Suite: сеть
│       ├── suite.yml
│       ├── node_discovery.yml
│       └── balancer_test.yml
│
├── groups/                        # Группы наборов
│   ├── smoke_tests.yml            # Быстрые smoke тесты
│   ├── regression.yml             # Полная регрессия
│   └── nightly.yml                # Ночные тесты
│
└── common/                        # Переиспользуемые компоненты
    ├── network_minimal.yml
    └── wallet_setup.yml
```

## 📝 Формат Suite (Набор сценариев)

### Файл `suite.yml`

```yaml
name: Token Operations Suite
description: Complete test suite for CF20 token operations
author: Your Team
tags: [tokens, critical]
version: "1.0"

# Общая топология для всех сценариев
network_topology: default

# Список сценариев (выполняются последовательно)
scenarios:
  - suites/token_operations/01_token_creation.yml
  - suites/token_operations/02_token_emission.yml
  - suites/token_operations/03_token_transfer.yml

# Общий setup (выполняется один раз перед всеми сценариями)
common_setup: suites/token_operations/common_setup.yml

# Общий cleanup (выполняется один раз после всех сценариев)
common_cleanup: suites/token_operations/common_cleanup.yml

# Опции выполнения
options:
  stop_on_failure: false           # Продолжать при ошибке
  rebuild_network: false            # Не пересобирать сеть
  cleanup_between_scenarios: true   # Очищать между сценариями
  parallel_execution: false         # Последовательно
  timeout_per_scenario: 300         # Таймаут на сценарий (сек)
```

### Общий Setup (`common_setup.yml`)

Выполняется **один раз** перед всеми сценариями в suite:

```yaml
name: Common Setup
description: Create wallets for all token tests

setup:
  - cli: wallet new -w test_wallet_owner
    node: node1
    save: owner_addr
  
  - cli: wallet new -w test_wallet_receiver
    node: node1
    save: receiver_addr

test:
  - cli: wallet list
    node: node1
    contains: "test_wallet_owner"
```

### Индивидуальный сценарий

Использует переменные из `common_setup`:

```yaml
name: Token Transfer Test
description: Test token transfers between wallets

test:
  # owner_addr и receiver_addr доступны из common_setup
  - cli: token_emit -token TEST1 -addr {{owner_addr}} -value 1000
    node: node1
    expect: success
    wait: 3s
  
  - cli: transfer -token TEST1 -to {{receiver_addr}} -value 500
    node: node1
    expect: success

check:
  - cli: balance -addr {{receiver_addr}} -token TEST1
    node: node1
    contains: "500"
```

## 🎮 Запуск Suite

### Через stage-env CLI

```bash
# Запустить весь suite
./stage-env run-suite scenarios/suites/token_operations/suite.yml

# Запустить конкретный сценарий из suite (с сохранением контекста)
./stage-env run-suite scenarios/suites/token_operations/suite.yml --scenario 02_token_emission.yml

# Запустить suite с rebuild сети
./stage-env run-suite scenarios/suites/token_operations/suite.yml --rebuild
```

### Lifecycle Suite

```
1. [Один раз] Поднять сеть по network_topology
2. [Один раз] Выполнить common_setup
3. Для каждого сценария:
   a. Загрузить сценарий
   b. Выполнить setup сценария
   c. Выполнить test сценария
   d. Выполнить check сценария
   e. [Опционально] Cleanup между сценариями
4. [Один раз] Выполнить common_cleanup
5. [Опционально] Остановить сеть
```

## 📋 Формат Group (Группа наборов)

### Файл `group.yml`

Группирует несколько suite для организации:

```yaml
name: Smoke Tests Group
description: Quick smoke tests for critical functionality

# Список suite в группе
suites:
  - suites/token_operations/suite.yml
  - suites/consensus/suite.yml
  - suites/network/suite.yml

# Порядок выполнения (опционально)
execution_order:
  - token_operations
  - network
  - consensus

# Вложенные группы (опционально)
groups:
  - groups/integration_tests.yml
```

### Запуск Group

```bash
# Запустить всю группу
./stage-env run-group scenarios/groups/smoke_tests.yml

# Запустить группу с остановкой при первой ошибке
./stage-env run-group scenarios/groups/smoke_tests.yml --stop-on-failure
```

## 🔧 Best Practices

### 1. Организация Suite

✅ **DO:**
- Группируйте связанные тесты в один suite
- Используйте префиксы для порядка (`01_`, `02_`)
- Создавайте общий setup для переиспользования
- Держите suite компактными (3-10 сценариев)

❌ **DON'T:**
- Не смешивайте несвязанные тесты
- Не дублируйте setup в каждом сценарии
- Не создавайте огромные suite (>20 сценариев)

### 2. Common Setup vs Individual Setup

**Common Setup** - для:
- Создания кошельков
- Декларации базовых токенов
- Общей инициализации

**Individual Setup** - для:
- Специфичных для теста данных
- Локальных переменных
- Особых условий

### 3. Cleanup между сценариями

```yaml
options:
  cleanup_between_scenarios: true
```

**Что очищается:**
- Незавершенные транзакции
- Временные файлы
- Кеши

**Что НЕ очищается:**
- Сеть (остается запущенной)
- Кошельки из common_setup
- Токены и состояние ledger

### 4. Именование

```
suites/
  <functional_area>/
    suite.yml
    common_setup.yml
    common_cleanup.yml
    01_<test_name>.yml
    02_<test_name>.yml
```

Пример:
```
suites/
  token_operations/
    suite.yml
    common_setup.yml
    01_token_creation.yml
    02_token_emission.yml
    03_token_transfer.yml
```

## 📊 Примеры использования

### Пример 1: Smoke Tests

```yaml
# groups/smoke_tests.yml
name: Smoke Tests
description: Quick 5-minute smoke test

suites:
  - suites/basic_operations/suite.yml
  - suites/token_basic/suite.yml

execution_order:
  - basic_operations
  - token_basic
```

### Пример 2: Full Regression

```yaml
# groups/regression.yml
name: Full Regression Suite
description: Complete regression test suite (~2 hours)

suites:
  - suites/token_operations/suite.yml
  - suites/consensus/suite.yml
  - suites/network/suite.yml
  - suites/services/suite.yml
  - suites/utxo_blocking/suite.yml

execution_order:
  - network              # Начать с сетевых тестов
  - consensus            # Затем консенсус
  - token_operations     # Затем токены
  - utxo_blocking        # Затем UTXO blocking
  - services             # Закончить сервисами
```

### Пример 3: Nightly Tests

```yaml
# groups/nightly.yml
name: Nightly Full Test Suite
description: Comprehensive nightly tests

groups:
  - groups/regression.yml
  - groups/performance_tests.yml
  - groups/stress_tests.yml

suites:
  - suites/long_running/suite.yml
```

## 🚀 Интеграция с CI/CD

### GitHub Actions

```yaml
name: Test Suite

on: [push, pull_request]

jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run Smoke Tests
        run: |
          cd tests/stage-env
          ./stage-env run-group scenarios/groups/smoke_tests.yml
  
  regression:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v3
      - name: Run Full Regression
        run: |
          cd tests/stage-env
          ./stage-env run-group scenarios/groups/regression.yml
```

## 📈 Мониторинг и отчеты

Suite генерирует детальные отчеты:

```
results/
  smoke_tests_20251021_150000/
    summary.json              # Общий отчет
    token_operations/
      suite_summary.json      # Отчет suite
      01_token_creation.json  # Отчет сценария
      02_token_emission.json
    network/
      suite_summary.json
      node_discovery.json
```

### Формат отчета

```json
{
  "suite": "token_operations",
  "status": "passed",
  "scenarios_total": 5,
  "scenarios_passed": 5,
  "scenarios_failed": 0,
  "duration_seconds": 127.5,
  "scenarios": [
    {
      "name": "01_token_creation",
      "status": "passed",
      "duration": 25.3
    }
  ]
}
```

## 🔍 Troubleshooting

### Suite падает на первом сценарии

**Причина:** Проблема с common_setup или сетью

**Решение:**
```bash
# Проверить common_setup отдельно
./stage-env run-scenario scenarios/suites/token_operations/common_setup.yml

# Проверить сеть
./stage-env status
```

### Переменные недоступны между сценариями

**Причина:** Cleanup очищает контекст

**Решение:** Использовать `common_setup` для глобальных переменных

### Suite слишком долгий

**Причина:** Много сценариев или долгие wait

**Решение:**
```yaml
options:
  parallel_execution: true  # Включить параллельное выполнение
  timeout_per_scenario: 120 # Уменьшить таймаут
```

## 📚 Дополнительные ресурсы

- [Scenario Schema Reference](REFERENCE.md)
- [Writing Scenarios Guide](GETTING_STARTED.md)
- [Stage Environment Cookbook](COOKBOOK.md)

