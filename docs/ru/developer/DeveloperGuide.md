# Руководство Разработчика Stage-Env

## Установка и Настройка

### Требования
- Python 3.13+
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

cd "$(dirname "$0")"
STAGE_ENV="stage-env/stage-env"
CONFIG="stage-env.cfg"

case "$1" in
    --e2e)
        ./$STAGE_ENV --config=$CONFIG start --wait
        ./$STAGE_ENV --config=$CONFIG run-tests scenarios/e2e
        ;;
    --functional)
        ./$STAGE_ENV --config=$CONFIG start --wait
        ./$STAGE_ENV --config=$CONFIG run-tests scenarios/functional
        ;;
    --regression)
        ./$STAGE_ENV --config=$CONFIG start --wait
        ./$STAGE_ENV --config=$CONFIG run-tests scenarios/regression
        ;;
    *)
        echo "Usage: $0 {--e2e|--functional|--regression}"
        exit 1
        ;;
esac
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

### Конфигурация (stage-env.cfg)
Конфигурация в формате INI с секциями `[network]`, `[topology]`, `[node_source]`:

```ini
# tests/stage-env.cfg
[network]
name = stagenet
network_id = 0x1234

[topology]
root_nodes_count = 3
master_nodes_count = 3
full_nodes_count = 2

[node_source]
type = local
local_path = ../../build/cellframe-node.deb

[paths]
project_root = ../..
cache_dir = ../../cache
artifacts_dir = ../../cache/artifacts
```

Скопируйте шаблон из `stage-env/config/stage-env.cfg.default`.

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

# Или изменить порты в stage-env.cfg
# tests/stage-env.cfg, секция [network_settings]
base_rpc_port = 9545
base_p2p_port = 31337
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

# Запустить (например, E2E тесты)
./tests/run.sh --e2e
```

### 2. Отладка
```bash
# Включить DEBUG логи (в stage-env.cfg: [logging] log_level = debug)
./tests/run.sh --e2e

# Проверить артефакты
ls -la tests/cache/artifacts/run_*/
```

### 3. Итерация
```bash
# Очистить среду
./tests/clean.sh

# Запустить снова
./tests/run.sh --e2e
```

### 4. CI/CD Integration
```yaml
# .gitlab-ci.yml
stages:
  - test

stage-env-tests:
  stage: test
  image: python:3.13
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
    - ./run.sh --e2e
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
