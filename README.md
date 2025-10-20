# Stage Environment - Portable Testing Infrastructure

**Самодостаточный модуль для E2E тестирования блокчейн приложений**

Stage Environment - это портативная инфраструктура для запуска и тестирования Cellframe Node в изолированной Docker среде. Модуль полностью автономен и может быть перенесён в любой проект.

## 🎯 Ключевые особенности

- ✅ **Полностью автономен** - управляет своим venv, зависимостями, Docker
- ✅ **Портативен** - скопируйте в любой проект и всё заработает
- ✅ **Универсален** - не привязан к конкретным типам тестов
- ✅ **Современный стек** - Python 3, Typer, Docker SDK, async/await
- ✅ **Artifacts collection** - автоматический сбор core dumps, логов, метрик
- ✅ **Rich UI** - красивый terminal output с таблицами и цветами

## 🏗️ Архитектура

```
stage-env/
├── stage-env              # Bash wrapper (auto venv, dependencies)
├── stage_env.py           # Python CLI (typer)
├── src/                   # Python modules
│   ├── utils/             # Logging, CLI helpers
│   ├── config/            # Configuration loading (Pydantic)
│   ├── docker/            # Docker Compose management
│   ├── monitoring/        # Health checks, artifacts collection
│   ├── network/           # Network topology management
│   ├── build/             # Build management
│   └── certs/             # Certificate generation
├── config/                # Configuration files
│   ├── topologies/        # Network topologies (JSON)
│   └── templates/         # Config templates (Jinja2)
├── tests/base/            # Base self-check tests
├── cache/                 # All temporary files
│   ├── build/             # Build artifacts
│   ├── certs/             # Generated certificates
│   ├── logs/              # Application logs
│   ├── crash-artifacts/   # Core dumps, backtraces
│   └── monitoring/        # Metrics
└── requirements.txt       # Python dependencies
```

## 🚀 Quick Start

### Установка

```bash
# Просто скопируйте stage-env в ваш проект
cp -r tests/stage-env /your/project/

# Или используйте напрямую
cd tests/stage-env
```

### Использование

```bash
# stage-env автоматически создаст venv и установит зависимости при первом запуске

# Сборка артефактов
./stage-env build

# Генерация сертификатов
./stage-env certs --network stagenet --nodes 4 --validators 3

# Запуск тестовой сети
./stage-env start --topology default --wait

# Проверка статуса
./stage-env status

# Просмотр логов
./stage-env logs node1 --tail 100

# Выполнение команды в ноде
./stage-env exec node1 "cellframe-node-cli net list"

# Запуск тестов
./stage-env run-tests tests/functional tests/scenarios

# Очистка
./stage-env clean --all

# Остановка
./stage-env stop
```

## 📊 Команды CLI

### Build Management

```bash
# Сборка
./stage-env build                    # Debug build
./stage-env build --release          # Release build
./stage-env build --clean            # Clean build
./stage-env build --jobs 8           # Parallel jobs
```

### Certificate Management

```bash
# Генерация сертификатов
./stage-env certs                              # Default (4 nodes, 3 validators)
./stage-env certs --nodes 10 --validators 5   # Custom
./stage-env certs --force                      # Regenerate
```

### Network Management

```bash
# Запуск
./stage-env start                           # Start with default topology
./stage-env start --topology minimal        # Use minimal topology
./stage-env start --rebuild                 # Rebuild before start
./stage-env start --clean                   # Clean everything before start

# Управление
./stage-env stop                            # Stop network
./stage-env restart                         # Restart all
./stage-env restart node1                   # Restart specific node
./stage-env status                          # Show network status
```

### Monitoring & Debugging

```bash
# Логи
./stage-env logs node1                      # Show logs
./stage-env logs node1 --follow             # Follow logs
./stage-env logs node1 --tail 500           # Last 500 lines

# Выполнение команд
./stage-env exec node1 "cellframe-node-cli version"
./stage-env exec node1 "ps aux"
```

### Testing

```bash
# Запуск тестов
./stage-env run-tests tests/functional             # Functional tests
./stage-env run-tests tests/scenarios              # E2E scenarios
./stage-env run-tests tests/custom                 # Custom tests
./stage-env run-tests dir1 dir2 dir3               # Multiple directories

# С фильтрацией
./stage-env run-tests tests/functional -k "test_utxo"    # Filter by pattern
./stage-env run-tests tests/functional -p                # Parallel execution
```

### Cleanup

```bash
./stage-env clean --build                   # Clean build artifacts
./stage-env clean --certs                   # Clean certificates
./stage-env clean --all                     # Clean everything
```

## 🌐 Network Topologies

Топологии определяются в `config/topologies/*.json`:

```json
{
  "network": {
    "name": "stagenet",
    "network_id": "0x1",
    "consensus": "esbocs"
  },
  "topology": {
    "root": {
      "count": 1,
      "role": "root",
      "consensus_participation": true,
      "description": "Root validator node"
    },
    "master": {
      "count": 2,
      "role": "master",
      "consensus_participation": true,
      "description": "Master validator nodes"
    },
    "full": {
      "count": 1,
      "role": "full",
      "consensus_participation": false,
      "description": "Full node"
    }
  },
  "network_settings": {
    "base_rpc_port": 8545,
    "base_p2p_port": 30303,
    "base_cf_port": 8079,
    "base_http_port": 8080,
    "base_ip": "172.20.0.10",
    "subnet": "172.20.0.0/16"
  }
}
```

### Создание своей топологии

```bash
# Скопируйте шаблон
cp config/topologies/default.json config/topologies/my-topology.json

# Отредактируйте параметры
vim config/topologies/my-topology.json

# Используйте
./stage-env start --topology my-topology
```

## 🧪 Testing

### Базовые тесты

```bash
# Запуск базовых тестов (самопроверка stage-env)
./stage-env run-tests tests/base
```

Базовые тесты проверяют:
- CLI доступность
- Импорт Python модулей
- Наличие requirements.txt
- Корректность структуры

### Интеграция с вашими тестами

stage-env агностичен к типам тестов - он просто запускает pytest для указанных директорий.

```bash
# Ваши функциональные тесты
./stage-env run-tests /path/to/your/functional/tests

# Ваши E2E сценарии
./stage-env run-tests /path/to/your/e2e/scenarios

# Несколько директорий
./stage-env run-tests /path1 /path2 /path3
```

## 🔧 Configuration


### Environment Variables

```bash
# Docker
export DOCKER_BUILDKIT=1           # Enable BuildKit
export COMPOSE_DOCKER_CLI_BUILD=1  # Use Docker CLI for builds

# Logging
export STAGE_ENV_LOG_LEVEL=DEBUG   # Verbose logging
export STAGE_ENV_LOG_JSON=1        # JSON logging for CI/CD
```

## 🐛 Artifacts Collection

При падении ноды автоматически собираются артефакты в `cache/crash-artifacts/<node>_<timestamp>/`:

- **Core dumps** - сжатые coredump файлы
- **Application logs** - логи из контейнера
- **Stack traces** - backtrace (если доступен gdb)
- **System info** - состояние системы на момент падения
- **Monitoring metrics** - метрики производительности
- **SUMMARY.json** - полный отчёт

```bash
# Просмотр артефактов
ls -lh cache/crash-artifacts/

# Анализ последнего падения
cd cache/crash-artifacts/node1_20251019_210000/
cat SUMMARY.json
```

## 📦 Портативность

### Перенос в другой проект

```bash
# 1. Скопируйте stage-env
cp -r tests/stage-env /new/project/testing/

# 2. Запустите (venv создастся автоматически)
cd /new/project/testing/stage-env
./stage-env --help

# 3. Настройте топологии под ваш проект
vim config/topologies/my-network.json

# 4. Готово!
./stage-env start --topology my-network
```

### Требования

- Python 3.8+
- Docker 20.10+
- Bash (для wrapper скрипта)

## 🔍 Troubleshooting

### venv не создаётся

```bash
# Проверьте Python
python3 --version

# Установите venv
sudo apt install python3-venv  # Debian/Ubuntu
sudo dnf install python3-virtualenv  # Fedora/RHEL
```

### Docker не доступен

```bash
# Проверьте Docker
docker --version
docker ps

# Добавьте пользователя в группу docker
sudo usermod -aG docker $USER
newgrp docker
```

### Зависимости не устанавливаются

```bash
# Принудительное переустановление
rm -rf .venv
./stage-env --help  # Пересоздаст venv
```

### Порты заняты

```bash
# Измените базовые порты в топологии
vim config/topologies/default.json

# Или используйте другую топологию
./stage-env start --topology minimal
```

## 📚 Advanced Usage

### Custom Topologies

Создайте сложные топологии с произвольными параметрами:

```json
{
  "topology": {
    "validators": {
      "count": 10,
      "role": "validator",
      "consensus_participation": true
    },
    "observers": {
      "count": 5,
      "role": "observer",
      "consensus_participation": false
    },
    "bridges": {
      "count": 2,
      "role": "bridge",
      "consensus_participation": false
    }
  }
}
```

## 🤝 Integration with CI/CD

```yaml
# .github/workflows/e2e-tests.yml
name: E2E Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Run E2E tests
        run: |
          cd tests/stage-env
          ./stage-env start --wait
          ./stage-env run-tests tests/scenarios
          ./stage-env stop
```

## 📝 License

See project root LICENSE file.

## 🔗 Links

- [Cellframe Node](https://github.com/demlabs-cellframe/cellframe-node)
- [DAP SDK](https://github.com/demlabs-cellframe/dap-sdk)
- [Python Cellframe](https://github.com/demlabs-cellframe/python-cellframe)
