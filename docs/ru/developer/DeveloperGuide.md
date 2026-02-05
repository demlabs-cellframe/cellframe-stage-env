# Руководство Разработчика Stage-Env

## Установка и Настройка

### Требования
- Python 3.10+
- Docker 20.10+
- Docker Compose 2.0+
- Git

### Установка
```bash
# Клонировать репозиторий
git clone https://gitlab.demlabs.net/cellframe/cellframe-stage-env.git
cd cellframe-stage-env

# Установить зависимости
pip install -r requirements.txt

# Проверить установку
./stage-env --help
```

## Интеграция Нового Проекта

### Структура Проекта
```
your-project/
├── tests/
│   ├── stage-env/          # Submodule Stage-Env
│   ├── run.sh              # Скрипт запуска
│   ├── clean.sh            # Скрипт очистки
│   └── scenarios/          # Ваши сценарии
│       ├── genesis/
│       └── functional/
└── .gitlab-ci.yml
```

### Добавление Submodule
```bash
cd your-project
git submodule add https://gitlab.demlabs.net/cellframe/cellframe-stage-env.git tests/stage-env
git submodule update --init --recursive
```

### Создание run.sh
```bash
#!/bin/bash
# tests/run.sh

set -e

# Переход в директорию stage-env
cd "$(dirname "$0")/stage-env"

# Конфигурация
export STAGE_ENV_PROJECT_ROOT="$(pwd)/../.."
export STAGE_ENV_SCENARIOS_DIR="$(pwd)/../scenarios"

# Запуск
./stage-env start "$@"
```

```bash
chmod +x tests/run.sh
```

### Создание clean.sh
```bash
#!/bin/bash
# tests/clean.sh

set -e

cd "$(dirname "$0")/stage-env"

# Остановка и очистка
./stage-env clean --full

# Удаление артефактов
rm -rf ../testing/artifacts/*

echo "Cleanup complete"
```

```bash
chmod +x tests/clean.sh
```

### Конфигурация (.env)
```bash
# tests/stage-env/.env

# Путь к проекту
STAGE_ENV_PROJECT_ROOT=/path/to/your-project

# Путь к сценариям
STAGE_ENV_SCENARIOS_DIR=/path/to/your-project/tests/scenarios

# Сетевая конфигурация
STAGE_ENV_NETWORK_NAME=stagenet
STAGE_ENV_ROOT_NODES=3
STAGE_ENV_MASTER_NODES=3

# Docker
STAGE_ENV_COMPOSE_PROJECT=your-project-stage

# Логирование
STAGE_ENV_LOG_LEVEL=INFO
```

## Примеры

### Минимальный Сценарий
```yaml
# tests/scenarios/minimal.yml
name: Minimal Test
description: Basic connectivity test

test:
  - docker_op: start
    services: [node-1]
    wait_for_ip: true
  
  - wait_network: online
    nodes: [node-1]
  
  - cli: "node dump"
    node: node-1
    contains: "Node addr:"
```

### Сценарий Genesis
```yaml
# tests/scenarios/genesis/phase1.yml
name: Genesis Phase 1
description: Zerochain genesis

variables:
  network_name: stagenet
  native_ticker: TCELL

test:
  - group: Network Setup
    steps:
      - docker_op: start
        services: "{{all_nodes}}"
        wait_for_ip: true
      
      - wait_network: online
        nodes: "{{all_nodes}}"
  
  - group: Token Declaration
    steps:
      - cli: "token_decl -t {{native_ticker}}"
        node: "{{first_root}}"
        save_hash: token_hash
      
      - wait_for_datum: "{{token_hash}}"
        chain: zerochain
```

### Функциональный Тест
```yaml
# tests/scenarios/functional/wallet_ops.yml
name: Wallet Operations
description: Test wallet creation and operations

test:
  - loop: 3
    steps:
      - cli: "wallet new -w wallet{{iteration}}"
        save_wallet: "addr{{iteration}}"
      
      - print: "Created wallet{{iteration}}: {{addr{{iteration}}}}"
  
  - cli: "wallet list"
    contains: "wallet0"
    contains: "wallet1"
    contains: "wallet2"
```

## Возможные Проблемы и Решения

### 1. Docker Permissions
**Проблема:**
```
ERROR: Cannot connect to Docker daemon
```

**Решение:**
```bash
# Добавить пользователя в группу docker
sudo usermod -aG docker $USER

# Перелогиниться
newgrp docker
```

### 2. Port Conflicts
**Проблема:**
```
ERROR: Port 8079 already in use
```

**Решение:**
```bash
# Найти процесс
lsof -i :8079

# Или изменить порты в config
# tests/stage-env/config/network.yml
node_base_port: 9079
```

### 3. Submodule Не Инициализирован
**Проблема:**
```
stage-env directory is empty
```

**Решение:**
```bash
git submodule update --init --recursive
```

### 4. Python Dependencies
**Проблема:**
```
ModuleNotFoundError: No module named 'pydantic'
```

**Решение:**
```bash
cd tests/stage-env
pip install -r requirements.txt
```

### 5. Scenario Parse Error
**Проблема:**
```
YAMLError: Invalid syntax at line 42
```

**Решение:**
```bash
# Проверить синтаксис
yamllint tests/scenarios/your-scenario.yml

# Распространённые ошибки:
# - Неправильные отступы (используйте 2 пробела)
# - Двойные/одинарные кавычки для шаблонов
# - Забытые двоеточия
```

## Workflow Разработки

### 1. Создание Сценария
```bash
# Создать файл
vim tests/scenarios/my-test.yml

# Запустить
./tests/run.sh --scenario my-test.yml
```

### 2. Отладка
```bash
# Включить DEBUG логи
export STAGE_ENV_LOG_LEVEL=DEBUG
./tests/run.sh --scenario my-test.yml

# Проверить артефакты
ls -la tests/testing/artifacts/latest/
```

### 3. Итерация
```bash
# Очистить среду
./tests/clean.sh

# Запустить снова
./tests/run.sh --scenario my-test.yml
```

### 4. CI/CD Integration
```yaml
# .gitlab-ci.yml
stages:
  - test

stage-env-tests:
  stage: test
  image: python:3.10
  services:
    - docker:dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  before_script:
    - apt-get update && apt-get install -y docker.io docker-compose
    - cd tests/stage-env
    - pip install -r requirements.txt
  script:
    - cd ..
    - ./run.sh --scenario genesis/phase1.yml
    - ./run.sh --scenario genesis/phase2.yml
  artifacts:
    when: always
    paths:
      - tests/testing/artifacts/
    expire_in: 7 days
```

## Best Practices

### 1. Версионирование Сценариев
```
scenarios/
├── v5/          # Для SDK 5.x
│   └── genesis/
└── v6/          # Для SDK 6.x
    └── genesis/
```

### 2. Переиспользование Кода
```yaml
# common/wallets.yml
wallet_setup: &wallet_setup
  - loop: 3
    steps:
      - cli: "wallet new -w wallet{{iteration}}"
        save_wallet: "addr{{iteration}}"

# Использование
test:
  - <<: *wallet_setup
```

### 3. Документирование Сценариев
```yaml
name: My Scenario
description: |
  Detailed description of what this scenario tests.
  
  Prerequisites:
  - Network must be running
  - Root nodes must be online
  
  Expected outcome:
  - Token created
  - Emission successful
  
variables:
  # Токен для тестирования
  test_token: MYTOKEN
```

### 4. Модульные Тесты
Разбивайте на небольшие сценарии:
```
scenarios/
├── 001_network_setup.yml
├── 002_token_creation.yml
├── 003_emission.yml
└── 004_tx_create.yml
```

### 5. Используйте Suite'ы
```yaml
# suite_setup.yml
suite_name: Full Genesis Suite
scenarios:
  - 001_network_setup.yml
  - 002_token_creation.yml
  - 003_emission.yml
```

## Расширение Stage-Env

### Добавление Нового Waiter
```python
# src/monitoring/waiter/custom_waiters.py
from .base import BaseWaiter

class MyCustomWaiter(BaseWaiter):
    def __init__(self, exec_cli, node, **kwargs):
        super().__init__(poll_interval=2.0)
        self.exec_cli = exec_cli
        self.node = node
    
    async def check(self) -> bool:
        exit_code, stdout, stderr = self.exec_cli(
            self.node.node_id,
            "my_custom_command",
            check_output=False
        )
        
        if exit_code == 0 and "expected" in stdout:
            return True
        return False
```

```python
# src/monitoring/unified/wait_registry.py
from ..waiter.custom_waiters import MyCustomWaiter

WaitRegistry.register("my_custom", MyCustomWaiter)
```

### Добавление Нового Operand
```python
# src/scenarios/schema.py
class MyCustomStep(BaseModel):
    my_custom: str
    param1: Optional[str] = None
```

```python
# src/scenarios/step/custom.py
class MyCustomStepExecutor(StepExecutor):
    async def execute(self, step: MyCustomStep, ctx: RuntimeContext):
        # Ваша логика
        pass
```

## Полезные Команды

```bash
# Список сценариев
ls -R tests/scenarios/

# Валидация сценария
./stage-env validate --scenario my-test.yml

# Запуск с фильтром
./stage-env start --tag genesis

# Генерация отчёта
./stage-env report --format pdf

# Экспорт конфигурации
./stage-env config --export > config.json
```
