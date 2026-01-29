# Отладка Сценариев

## Операнд Print

### Базовое Использование
```yaml
- print: "Starting test"
- print: "=================================="
```

### С Переменными
```yaml
- cli: "wallet new"
  save_wallet: addr
- print: "Created wallet: {{addr}}"
```

### Сложные Данные
```yaml
- python: |
    data = {"key": "value", "num": 42}
    ctx.set_variable('result', data)
- print: "Result: {{result}}"
# Вывод: Result: {'key': 'value', 'num': 42}
```

### Отладка Условий
```yaml
- print: "Balance: {{balance}}, Condition: {{balance > 1000}}"
- if: "{{balance > 1000}}"
  then:
    - print: "Sufficient balance"
```

### В Циклах
```yaml
- for: i
  in: "range(5)"
  eval: true
  steps:
    - print: "Iteration {{i}}, node: {{node_list[i]}}"
```

**Новое в v2.1.0:** Полная поддержка всех типов данных в print.

## Уровни Логирования

### Установка Через Environment
```bash
export STAGE_ENV_LOG_LEVEL=DEBUG
./stage-env start
```

### Уровни
- `DEBUG` - Все детали (CLI команды, waiters, шаги)
- `INFO` - Основные события (default)
- `WARNING` - Предупреждения
- `ERROR` - Только ошибки

### Структурированное Логирование
Все логи в формате structured logging:
```
2026-01-29T12:00:00.123456Z [info] cli_command command='wallet new' node=node1
2026-01-29T12:00:01.234567Z [info] cli_success duration=1.1s output_lines=5
```

## Типичные Проблемы

### 1. Шаблон Не Подставляется
```yaml
# ПЛОХО: одинарные кавычки блокируют Jinja2
- cli: '{{command}}'

# ХОРОШО: двойные кавычки
- cli: "{{command}}"

# ХОРОШО: без кавычек (если нет спецсимволов)
- cli: {{command}}
```

### 2. Переменная Не Найдена
```yaml
# Проверка существования
- if: "ctx.has_variable('wallet')"
  then:
    - cli: "wallet info -w {{wallet}}"
  else:
    - print: "ERROR: wallet variable not set!"

# С default значением
- print: "Wallet: {{wallet|default('NOT_SET')}}"
```

### 3. CLI Не Готов
```yaml
# СТАРОЕ: ручное ожидание
- wait: "5s"
- cli: "node dump"

# НОВОЕ: автоматические ретраи (v2.1.0)
- cli: "node dump"
  save_node: addr
  # Автоматически повторяется до 10 раз
```

### 4. Datum Не Обрабатывается
```yaml
# ПЛОХО: фиксированное ожидание
- cli: "token_decl -t NEWTOKEN"
  save_hash: token_hash
- wait: "30s"

# ХОРОШО: интеллектуальное ожидание
- cli: "token_decl -t NEWTOKEN"
  save_hash: token_hash
- wait_for_datum: "{{token_hash}}"
  timeout_total: 120
```

### 5. Config Не Применяется
```yaml
# ПЛОХО: restart не перезагружает конфиг
- config: "{{network}}/main"
  set:
    is_add_directly: "true"
- docker_op: restart
  services: "{{all_nodes}}"

# ХОРОШО: stop + start
- config: "{{network}}/main"
  set:
    is_add_directly: "true"
- docker_op: stop
  services: "{{all_nodes}}"
- docker_op: start
  services: "{{all_nodes}}"
  wait_for_ip: true
- wait_network: online
  nodes: "{{all_nodes}}"
```

### 6. Global DB Не Синхронизирован
```yaml
# ПЛОХО: фиксированное ожидание
- docker_op: restart
  services: "{{all_nodes}}"
- wait: "40s"

# ХОРОШО: интеллектуальное ожидание
- docker_op: restart
  services: "{{all_nodes}}"
- wait_network: online
  nodes: "{{all_nodes}}"
- wait: global_db_sync
  nodes: "{{all_nodes}}"
  timeout: 60
```

## Артефакты

### Структура
Логи собираются в:
```
tests/testing/artifacts/run_YYYYMMDD_HHMMSS/
├── logs/
│   ├── cellframe-stage-node-1.log
│   ├── cellframe-stage-node-2.log
│   └── ...
├── configs/
│   └── (конфиги нод)
└── reports/
    ├── report.md
    └── report.json
```

### Доступ к Логам
```bash
# Просмотр последнего лога ноды
tail -f tests/testing/artifacts/latest/logs/cellframe-stage-node-1.log

# Поиск ошибок
grep ERROR tests/testing/artifacts/latest/logs/*.log
```

## Режим Интерактивной Отладки

### Войти в Контейнер
```bash
# Войти в контейнер ноды
docker exec -it cellframe-stage-node-1 bash

# Проверить процесс
ps aux | grep cellframe

# Проверить конфиг
cat /opt/cellframe-node/etc/network/stagenet/zerochain.cfg
```

### Проверить Логи
```bash
# Лог ноды
tail -f /opt/cellframe-node/var/log/cellframe-node.log

# Искать ошибки
grep -i error /opt/cellframe-node/var/log/cellframe-node.log
```

### Запустить CLI Вручную
```bash
# В контейнере
cellframe-node-cli wallet list
cellframe-node-cli node dump -net stagenet
cellframe-node-cli mempool list -chain zerochain
```

### Проверить Global DB
```bash
# Проверить ноды в сети
cellframe-node-cli node list -net stagenet

# Проверить блоки
cellframe-node-cli block list -chain main

# Проверить транзакции
cellframe-node-cli ledger list txs -chain main
```

## Стратегии Отладки

### 1. Бинарный Поиск
Закомментируйте половину шагов:
```yaml
test:
  - step1
  - step2
  # - step3
  # - step4
  # - step5
```

Найдите проблемный блок, затем углубляйтесь.

### 2. Добавьте Print'ы
```yaml
test:
  - cli: "wallet new"
    save_wallet: addr
  - print: "DEBUG: wallet={{addr}}"
  
  - cli: "token_decl -w {{addr}}"
    save_hash: token_hash
  - print: "DEBUG: token_hash={{token_hash}}"
```

### 3. Проверьте Предусловия
```yaml
test:
  - cli: "node list -net {{network_name}}"
    save_to: node_list
  - print: "Nodes: {{node_list}}"
  
  - cli: "wallet list"
    save_to: wallet_list
  - print: "Wallets: {{wallet_list}}"
```

### 4. Изолируйте Проблему
Создайте минимальный сценарий:
```yaml
name: Minimal Repro
test:
  - docker_op: start
    services: [node-1]
    wait_for_ip: true
  
  - wait_network: online
    nodes: [node-1]
  
  - cli: "node dump"
    node: node-1
    save_node: addr
  
  - print: "SUCCESS: {{addr}}"
```

### 5. Используйте Python для Анализа
```yaml
test:
  - cli: "node list"
    save_to: raw_output
  
  - python: |
      import json
      output = ctx.get_variable('raw_output', '')
      print(f"Output length: {len(output)}")
      print(f"First 100 chars: {output[:100]}")
      
      # Анализ
      if "error" in output.lower():
          print("ERROR FOUND IN OUTPUT!")
```

## Performance Профилирование

### Измерение Времени
```yaml
test:
  - set: start_time
    value: "time.time()"
    eval: true
  
  - cli: "slow operation"
  
  - python: |
      import time
      start = float(ctx.get_variable('start_time'))
      elapsed = time.time() - start
      print(f"Operation took: {elapsed:.2f}s")
```

### Таймауты
```yaml
# Увеличьте таймаут для медленных операций
test:
  - wait: global_db_sync
    timeout: 120  # вместо default 60
  
  - wait_for_datum: "{{tx_hash}}"
    timeout_total: 300  # 5 минут
```
