# Stage Environment - Cellframe Node Testing Infrastructure

**Автономная система для E2E тестирования блокчейн приложений**

Stage Environment - это полнофункциональная инфраструктура для запуска и тестирования Cellframe Node в изолированной Docker среде. Система полностью автономна, легко портируется и не требует глубоких знаний программирования для написания тестов.

## 🎯 Возможности

- ✅ **YAML-сценарии** - пишите тесты на декларативном языке без программирования
- ✅ **Автоматизация** - сборка, запуск, тестирование, сбор артефактов
- ✅ **Docker-изоляция** - каждый тест в чистом окружении
- ✅ **Гибкие топологии** - от 1 ноды до сложных сетей
- ✅ **Artifacts & Reports** - автоматический сбор логов, core dumps, генерация PDF отчетов
- ✅ **Rich CLI** - красивый интерфейс с цветным выводом и progress bars

## 🚀 Быстрый старт

### Способ 1: Через run.sh (Рекомендуется)

Самый простой способ запустить тесты - использовать унифицированный раннер `run.sh`:

```bash
cd tests

# Запустить все тесты (E2E + Functional + Regression)
./run.sh

# Запустить только E2E тесты
./run.sh --e2e

# Запустить только functional тесты
./run.sh --functional

# Запустить конкретный test suite
./run.sh tests/e2e/token/

# Очистить окружение и запустить
./run.sh --clean --e2e
```

**Что происходит:**
- Автоматически стартует stage-env сеть
- Запускает выбранные test suites
- Собирает artifacts и генерирует отчёты
- Останавливает сеть и показывает сводку

**Результаты:** `tests/testing/artifacts/run_*/`

### Способ 2: Через stage-env напрямую

Для продвинутого управления используйте stage-env CLI напрямую:

```bash
cd tests/stage-env

# 1. Запуск тестовой сети
./stage-env start --wait

# 2. Проверка статуса
./stage-env status

# 3. Запуск тестов
./stage-env run-tests ../e2e/

# 4. Остановка
./stage-env stop
```

## 📖 Документация

### Для пользователей и CI/CD

- **[Руководство по run.sh](RunShGuide.md)** - Полное руководство по запуску тестов через run.sh
- **[Быстрый старт](#быстрый-старт)** - Начните за 2 минуты

### Для QA инженеров

- **[Tutorial](scenarios/Tutorial.md)** - Пошаговое обучение языку сценариев (8 уроков)
- **[Cookbook](scenarios/Cookbook.md)** - Готовые рецепты для типовых задач 
- **[Glossary](scenarios/Glossary.md)** - Полный справочник языка (все команды и параметры)

### Для разработчиков

- **[Архитектура](Architecture.md)** - Архитектура системы и внутренние компоненты
- **Исходники stage-env** - Python код в директории `src/`

## 📁 Структура проекта

```
stage-env/
├── stage-env                # Bash wrapper (точка входа)
├── stage_env.py             # Python CLI (Typer)
├── stage-env.cfg            # Конфигурация (в tests/)
│
├── src/                     # Python модули
│   ├── scenarios/           # Система сценариев (parser, executor, schema)
│   ├── network/             # Управление сетью и топологией
│   ├── docker/              # Docker Compose интеграция
│   ├── config/              # Управление конфигурацией
│   ├── certs/               # Генерация сертификатов
│   ├── snapshots/           # Система snapshots (filesystem, squashfs)
│   ├── monitoring/          # Health checks, datum monitoring, artifacts
│   └── utils/               # CLI helpers, логирование, отчёты
│
├── config/                  # Шаблоны конфигурации
│   ├── topologies/          # Шаблоны сетевых топологий
│   └── templates/           # Jinja2 шаблоны конфигов
│       ├── base/            # Базовые конфиги нод
│       └── chains/          # Конфиги блокчейнов
│
├── scenarios/               # YAML тест-сценарии
│   ├── common/              # Переиспользуемые шаблоны
│   ├── genesis/             # Сценарии инициализации genesis
│   └── suites/              # Тестовые suites
│
├── tests/                   # Собственные тесты stage-env
│   ├── base/                # Базовые проверки connectivity
│   ├── unit/                # Unit тесты компонентов
│   └── integration/         # Integration тесты
│
└── docs/                    # Документация
    ├── en/                  # Английская документация
    │   ├── README.md
    │   ├── RunShGuide.md
    │   ├── Architecture.md
    │   └── scenarios/       # Документация языка сценариев
    └── ru/                  # Русская документация
        ├── README.md
        ├── RunShGuide.md
        ├── Architecture.md
        └── scenarios/
```

## 🎨 Основные команды

### Через run.sh (Рекомендуется для большинства пользователей)

```bash
cd tests

# Запуск тестов по типу
./run.sh                     # Все тесты (E2E + Functional + Regression)
./run.sh --e2e               # Только E2E тесты
./run.sh --functional        # Только functional тесты
./run.sh --regression        # Только regression тесты

# Запуск конкретных тестов
./run.sh tests/e2e/token/    # Запустить конкретный test suite
./run.sh tests/e2e/token/001_token_decl.yml  # Запустить один сценарий

# С очисткой/пересборкой
./run.sh --clean --e2e       # Очистить cache перед запуском
./run.sh --rebuild --e2e     # Пересобрать Docker images перед запуском

# Обслуживание
./run.sh --stop              # Остановить stage environment
./run.sh --pkgs-update       # Обновить пакеты в контейнерах
```

### Через stage-env CLI (Продвинутое)

```bash
cd tests/stage-env

# === Управление сетью ===
./stage-env start --wait             # Запустить сеть и ждать ONLINE
./stage-env start --rebuild          # Пересобрать images перед запуском
./stage-env stop                     # Остановить сеть
./stage-env stop --volumes           # Остановить и удалить volumes
./stage-env restart                  # Перезапустить все ноды
./stage-env status                   # Показать статус нод

# === Тестирование ===
./stage-env run-tests ../e2e/            # Запустить тесты из директории
./stage-env run-tests ../e2e/test.yml    # Запустить конкретный сценарий
./stage-env run-tests --filter token     # Фильтр по названию

# === Мониторинг ===
./stage-env logs node-1              # Показать логи ноды (последние 100 строк)
./stage-env logs node-1 --follow     # Follow логи в реальном времени
./stage-env exec node-1 "ls -la"     # Выполнить команду в ноде

# === Сертификаты ===
./stage-env certs                    # Сгенерировать сертификаты (default топология)
./stage-env certs --force            # Пересоздать существующие

# === Snapshots ===
./stage-env snapshots-list           # Список snapshots
./stage-env snapshots-delete <hash>  # Удалить конкретный snapshot
./stage-env snapshots-info <hash>    # Показать детали snapshot
./stage-env snapshots-clean          # Очистить старые snapshots

# === Сборка и пересборка ===
./stage-env build                    # Собрать cellframe-node
./stage-env rebuild                  # Пересобрать images и перезапустить

# === Очистка ===
./stage-env clean --all              # Очистить всё
./stage-env pkgs-update              # Обновить пакеты в контейнерах
```

## 📝 Написание тестов

### Простой тест

```yaml
# scenarios/my_test.yml
name: My First Test
description: Check wallet creation

includes:
  - common/network_minimal.yml

test:
  - cli: wallet new -w test_wallet
    save: wallet_addr
  
  - cli: wallet list
    contains: test_wallet

check:
  - cli: wallet info -w test_wallet
    contains: {{wallet_addr}}
```

### Запуск сценария

```bash
cd tests/stage-env
./stage-env run-tests ../e2e/my_test.yml
```

**Или через run.sh:**
```bash
cd tests
./run.sh tests/e2e/my_test.yml
```

### Готовые шаблоны

- `scenarios/common/network_minimal.yml` - Минимальная сеть (1 нода)
- `scenarios/common/network_full.yml` - Полная сеть (несколько нод)
- `scenarios/common/wallet_setup.yml` - Предконфигурированный кошелёк
- `scenarios/common/set_net_default.yml` - Автодобавление -net параметра

## 🔧 Конфигурация

Основная конфигурация находится в `tests/stage-env.cfg`:

```ini
# === Сеть ===
[network]
name = stagenet                    # Имя сети
network_id = 0x1234                # Network ID
consensus_type = esbocs            # Тип консенсуса (esbocs/pos/poa)

# === Топология ===
[topology]
root_nodes_count = 3               # Количество root нод
master_nodes_count = 3             # Количество master нод
full_nodes_count = 1               # Количество full нод

# === Сборка ===
[build]
build_type = debug                 # debug или release
cellframe_version = latest         # Версия Cellframe Node

# === Сетевые настройки ===
[network_settings]
base_rpc_port = 8545               # Базовый порт RPC
base_p2p_port = 31337              # Базовый порт P2P
base_http_port = 8079              # Базовый порт HTTP
node_port = 8079                   # Порт для внешних подключений
subnet = 172.20.0.0/16             # Docker subnet

# === Консенсус ===
[consensus]
min_validators = 2                 # Минимум валидаторов
new_round_delay = 45               # Задержка между раундами
collecting_level = 10.0            # Уровень сбора голосов
auth_certs_prefix = stagenet.master # Префикс сертификатов

# === Балансировщик ===
[balancer]
enabled = true                     # Включить балансировщик
type = http                        # Тип балансировщика (http)
uri = f0intlt4eyl03htogu           # URI балансировщика
max_links_response = 10            # Макс. количество ссылок в ответе
request_delay = 20                 # Задержка между запросами

# === Функции ===
[features]
monitoring = false                 # Мониторинг
tests = false                      # Тестовый режим
crash_artifacts = true             # Сбор артефактов при крашах

# === Пути ===
[paths]
cache_dir = ../testing/cache       # Директория кэша
artifacts_dir = ../testing/artifacts # Директория артефактов

# === Логирование ===
[logging]
log_dir = ../testing/logs          # Директория логов
log_level = info                   # Уровень логирования (debug/info/warning/error)
scenario_logs = true               # Логировать выполнение сценариев
retain_days = 7                    # Хранить логи N дней

# === Артефакты ===
[artifacts]
collect_node_logs = true           # Собирать логи нод
collect_health_logs = true         # Собирать health check логи
collect_crash_dumps = true         # Собирать core dumps
retain_days = 30                   # Хранить артефакты N дней

# === Таймауты (в секундах) ===
[timeouts]
startup = 600                      # Таймаут запуска сети
health_check = 600                 # Таймаут health check
command = 30                       # Таймаут выполнения команд

# === Источник ноды ===
[node_source]
type = local                       # local/url/repository
local_path = ../test_build/cellframe-node.deb  # Путь к локальному .deb
# url = https://...                # URL для загрузки
# repository_url = https://...     # Git репозиторий для сборки
```

## 🎯 Интеграция в свой проект

### Использование run.sh (Рекомендуется)

```bash
#!/bin/bash
# Простая обёртка для вашего проекта

cd tests
./run.sh --e2e
```

### Использование stage-env напрямую

```bash
#!/bin/bash
set -euo pipefail

cd tests/stage-env

# Запуск сети
./stage-env start --wait

# Запуск тестов
./stage-env run-tests ../e2e/

# Остановка
./stage-env stop
```

### Настройка топологии

Топология сети настраивается через секцию `[topology]` в `stage-env.cfg`:

```ini
[topology]
root_nodes_count = 3     # Root ноды (seed nodes, bootstrap)
master_nodes_count = 3   # Master ноды (validators)
full_nodes_count = 1     # Full ноды (без валидации)
```

Или используйте готовые топологии:

```bash
./stage-env start --topology default  # По умолчанию (из конфига: 3 root + 3 master + 1 full = 7 нод)
./stage-env start --topology minimal  # 1 root нода для быстрых тестов
```

**Примечание:** Фактическое количество нод зависит от конфигурации в `[topology]` секции `stage-env.cfg`.

## 📊 Артефакты и отчеты

После каждого прогона в `testing/artifacts/<run_id>/`:

```
e2e_20251023_150000/
├── reports/
│   ├── report.md            # Markdown отчет
│   └── report.pdf           # PDF отчет (pandoc)
├── stage-env-logs/          # Логи stage-env
├── node-logs/               # Логи Docker контейнеров
├── core-dumps/              # Core dumps (если были)
├── health-logs/             # Health check логи
└── summary.json             # JSON сводка
```

## 🔍 Решение проблем

### Проблемы с Docker

```bash
# Проверка Docker
docker ps
docker compose version

# Перезапуск Docker
sudo systemctl restart docker
```

### Проблемы с портами

```bash
# Проверка занятых портов
ss -tlnp | grep 8079

# Остановка через run.sh
cd tests
./run.sh --stop

# Или напрямую
cd tests/stage-env
./stage-env stop --volumes
```

### Проблемы с Python

```bash
cd tests/stage-env

# Пересоздать venv
rm -rf .venv
./stage-env --help  # Автоматически создаст venv заново
```

### Логи для отладки

```bash
cd tests/stage-env

# Verbose режим
./stage-env --verbose start

# Логи конкретной ноды
./stage-env logs node-1 --tail 100

# Follow логи в реальном времени
./stage-env logs node-1 --follow

# Статус всех нод
./stage-env status
```

## 📚 Подробная документация

### Для QA инженеров

- **[Tutorial](scenarios/Tutorial.md)** - 8 уроков с упражнениями для изучения языка сценариев
- **[Cookbook](scenarios/Cookbook.md)** - Готовые рецепты для типовых задач
- **[Glossary](scenarios/Glossary.md)** - Полный справочник: все команды, параметры, примеры

### Готовые примеры

- `tests/stage-env/scenarios/common/` - Переиспользуемые шаблоны (network_minimal.yml, network_full.yml)
- `tests/stage-env/scenarios/features/` - Реальные тесты функциональности
- `tests/stage-env/scenarios/suites/` - Наборы тестов для комплексной проверки

## 🤝 Участие в разработке

1. Форк репозитория
2. Создайте feature branch (`git checkout -b feature/amazing-feature`)
3. Commit изменений (`git commit -m 'Add amazing feature'`)
4. Push в branch (`git push origin feature/amazing-feature`)
5. Создайте Pull Request

## 📜 Лицензия

См. LICENSE в корне проекта.

## 🔗 Ссылки

- [Cellframe Node](https://github.com/demlabs-cellframe/cellframe-node)
- [DAP SDK](https://github.com/demlabs-cellframe/dap-sdk)
- [Python Cellframe](https://github.com/demlabs-cellframe/python-cellframe)


---

**Язык:** Русский | [English](../en/README.md)
