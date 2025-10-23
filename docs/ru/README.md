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

### Минимальный пример

```bash
# 1. Запуск тестовой сети (автоматически установит зависимости)
cd tests
./stage-env/stage-env start

# 2. Проверка статуса
./stage-env/stage-env status

# 3. Запуск тестов
./stage-env/stage-env run-tests scenarios/

# 4. Остановка
./stage-env/stage-env stop
```

### Запуск через run.sh

```bash
# Полный цикл: сборка + тесты + отчеты
cd tests
./run.sh --e2e

# Результаты в testing/artifacts/e2e_*/reports/
```

## 📖 Документация

### Для QA инженеров

- **[Scenarios Tutorial](docs/scenarios/Tutorial.md)** - Пошаговое обучение языку сценариев
- **[Scenarios Cookbook](docs/scenarios/Cookbook.md)** - Готовые рецепты для типовых задач
- **[Scenarios Glossary](docs/scenarios/Glossary.md)** - Полный справочник языка

### Для разработчиков

- **[Architecture](docs/Architecture.md)** - Архитектура системы
- **[Integration](docs/Integration.md)** - Интеграция в проект
- **[CI/CD](docs/CICD.md)** - Настройка CI/CD

## 📁 Структура проекта

```
stage-env/
├── stage-env                # Bash wrapper (точка входа)
├── stage_env.py             # Python CLI (Typer)
├── stage-env.cfg            # Конфигурация (в tests/)
│
├── src/                     # Python модули
│   ├── config/              # Управление конфигурацией
│   ├── docker/              # Docker Compose интеграция
│   ├── network/             # Топологии и сеть
│   ├── build/               # Сборка артефактов
│   ├── certs/               # Генерация сертификатов
│   └── utils/               # Логирование, отчеты, артефакты
│
├── config/                  # Конфигурационные файлы
│   ├── topologies/          # Шаблоны сетевых топологий
│   └── templates/           # Jinja2 шаблоны конфигов
│
├── scenarios/               # YAML тест-сценарии
│   ├── common/              # Переиспользуемые шаблоны
│   └── features/            # Feature-specific тесты
│
└── docs/                    # Документация
    ├── scenarios/           # Документация по сценариям
    └── ...                  # Прочая документация
```

## 🎨 Основные команды

```bash
# === Управление сетью ===
stage-env start              # Запустить сеть
stage-env start --no-wait    # Запуск без ожидания ONLINE
stage-env stop               # Остановить сеть
stage-env restart            # Перезапустить
stage-env status             # Показать статус нод

# === Тестирование ===
stage-env run-tests <dir>    # Запустить тесты из директории
stage-env run-tests test.yml # Запустить конкретный сценарий

# === Мониторинг ===
stage-env logs node-1        # Показать логи ноды
stage-env logs node-1 -f     # Follow логи
stage-env exec node-1 "cmd"  # Выполнить команду в ноде

# === Артефакты и отчеты ===
stage-env collect-artifacts e2e --exit-code=0

# === Сборка ===
stage-env build              # Собрать Cellframe Node
stage-env build --clean      # Чистая сборка

# === Сертификаты ===
stage-env certs --nodes 7    # Сгенерировать сертификаты

# === Очистка ===
stage-env clean --all        # Очистить всё
stage-env stop --volumes     # Остановить и удалить volumes
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

### Запуск теста

```bash
./stage-env/stage-env run-tests scenarios/my_test.yml
```

### Готовые шаблоны

- `common/network_minimal.yml` - 1 нода
- `common/network_full.yml` - 7 нод (валидаторы + full node)
- `common/wallet_setup.yml` - Готовый кошелёк

## 🔧 Конфигурация

Основная конфигурация находится в `tests/stage-env.cfg`:

```ini
[network]
name = stagenet
network_id = 0x1234

[paths]
cache_dir = ../testing/cache
artifacts_dir = ../testing/artifacts

[artifacts]
collect_node_logs = true
collect_health_logs = true
collect_crash_dumps = true
retain_days = 30

[timeouts]
startup = 600
health_check = 600
command = 30
```

## 🎯 Интеграция в свой проект

### Пример run.sh

```bash
#!/bin/bash
set -euo pipefail

STAGE_ENV="./stage-env/stage-env"
STAGE_ENV_CONFIG="./stage-env.cfg"

# Сборка (опционально)
# cmake -B build && make -C build

# Запуск сети
"$STAGE_ENV" --config="$STAGE_ENV_CONFIG" start

# Запуск тестов
"$STAGE_ENV" --config="$STAGE_ENV_CONFIG" run-tests scenarios/

# Сбор артефактов
"$STAGE_ENV" --config="$STAGE_ENV_CONFIG" collect-artifacts e2e --exit-code=$?

# Остановка
"$STAGE_ENV" --config="$STAGE_ENV_CONFIG" stop
```

### Настройка топологии

Создайте `config/topologies/my-network.json`:

```json
{
  "network": {
    "name": "mynet",
    "network_id": "0x5678"
  },
  "topology": {
    "validators": {
      "count": 5,
      "role": "validator",
      "consensus_participation": true
    },
    "full_nodes": {
      "count": 2,
      "role": "full",
      "consensus_participation": false
    }
  }
}
```

Запустите:

```bash
./stage-env start --topology my-network
```

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

## 🔍 Troubleshooting

### Проблемы с Docker

```bash
# Проверка Docker
docker ps
docker-compose version

# Перезапуск Docker
sudo systemctl restart docker
```

### Проблемы с портами

```bash
# Проверка занятых портов
ss -tlnp | grep 8079

# Остановка всех контейнеров
./stage-env stop --volumes
```

### Проблемы с Python

```bash
# Пересоздать venv
rm -rf .venv
./stage-env --help  # Создаст venv заново
```

### Логи для отладки

```bash
# Verbose режим
./stage-env --verbose start

# Логи конкретной ноды
./stage-env logs node-1 --tail 100

# Статус всех нод
./stage-env status
```

## 📚 Подробная документация

- **[Tutorial](docs/scenarios/Tutorial.md)** - Пошаговое руководство для QA
- **[Cookbook](docs/scenarios/Cookbook.md)** - Рецепты для типовых задач
- **[Glossary](docs/scenarios/Glossary.md)** - Полный справочник языка сценариев

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
