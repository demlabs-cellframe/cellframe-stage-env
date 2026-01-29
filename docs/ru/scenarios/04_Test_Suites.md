# Тест-Сьюты

## Структура Сьюта

```yaml
# suite_setup.yml
suite_name: Token Tests
suite_description: Комплексное тестирование токенов

suite_setup:
  variables:
    network_name: stagenet
    native_ticker: TCELL
    
  steps:
    - cli: "wallet new -w shared_wallet"
      save_wallet: suite_wallet
    # Доступно во всех сценариях

scenarios:
  - token/001_token_decl.yml
  - token/002_token_emit.yml
  - token/003_tx_create.yml
```

## Переменные Сьюта

### Определение
```yaml
suite_setup:
  variables:
    shared_var: value
    api_key: "secret"
```

### Использование в Сценариях
```yaml
# Любой сценарий в сьюте
test:
  - cli: "wallet info -w {{suite_wallet}}"
  - print: "API: {{api_key}}"
```

### Видимость
- Доступны во всех сценариях сьюта
- Не могут быть переопределены в сценариях
- Имеют приоритет над глобальными переменными

## Жизненный Цикл Сьюта

1. Парсинг suite_setup.yml
2. Выполнение suite_setup шагов
3. Сохранение переменных сьюта
4. Для каждого сценария:
   - Загрузка сценария
   - Слияние переменных сьюта
   - Выполнение сценария
   - Сбор результатов
5. Генерация отчёта по сьюту

## Конфигурация Сьюта

### Топология Сети
```yaml
suite_setup:
  network:
    topology: custom
    root_nodes: 3
    master_nodes: 3
    validators: 2
```

### Пакеты
```yaml
suite_setup:
  packages:
    - name: vim
      nodes: all
    - name: tcpdump
      nodes: [node1, node2]
```

### Файлы
```yaml
suite_setup:
  files:
    - src: config.txt
      dst: /opt/config.txt
      nodes: all
    - src: script.sh
      dst: /tmp/script.sh
      nodes: [node1]
      mode: "755"
```

## Продвинутые Паттерны

### Общий Setup
```yaml
suite_setup:
  steps:
    # Создать кошельки для всех тестов
    - for: i
      in: "range(5)"
      eval: true
      steps:
        - cli: "wallet new -w wallet{{i}}"
          save_wallet: "wallet{{i}}_addr"
```

### Shared Resources
```yaml
suite_setup:
  variables:
    shared_token: MYTOKEN
    
  steps:
    - cli: "token_decl -t {{shared_token}}"
      save_hash: token_hash
    - cli: "token_emit -t {{shared_token}}"
      save_hash: emission_hash
```

### Условный Setup
```yaml
suite_setup:
  steps:
    - if: "{{ctx.has_variable('ENABLE_FEATURE_X')}}"
      then:
        - cli: "enable feature_x"
```

## Лучшие Практики

1. **Общий setup в сьюте** - создавайте ресурсы один раз
2. **Используйте переменные сьюта** - для общих данных
3. **Держите сценарии независимыми** - не полагайтесь на порядок
4. **Семантичные имена** - `wallet_suite_alice`, не `w1`
5. **Документируйте зависимости** - в `suite_description`

## Пример Полного Сьюта

```yaml
# suite_setup.yml
suite_name: Genesis Complete Test Suite
suite_description: |
  Полное тестирование genesis процесса:
  - Phase 1: Zerochain genesis
  - Phase 2: ESBocs mainchain genesis

suite_setup:
  variables:
    network_name: stagenet
    native_ticker: TCELL
    decimals: 18
    total_supply: "1e+27"
    
  network:
    topology: full
    root_nodes: 3
    master_nodes: 3
    
  steps:
    - group: Network Initialization
      steps:
        - docker_op: start
          services: "{{all_nodes}}"
          wait_for_ip: true
        
        - wait_network: online
          nodes: "{{all_nodes}}"
    
    - group: Shared Wallets
      steps:
        - for: i
          in: "range(3)"
          eval: true
          steps:
            - cli: "wallet new -w root_wallet{{i}}"
              node: "node-{{i+1}}"
              save_wallet: "root_wallet{{i}}"

scenarios:
  - genesis/phase1_zerochain.yml
  - genesis/phase2_esbocs.yml
  - validation/block_validation.yml
  - validation/tx_validation.yml
```

## Отладка Сьютов

### Запуск Одного Сценария
```bash
./stage-env start --scenario genesis/phase1_zerochain.yml
```

### Пропуск Suite Setup
```bash
./stage-env start --skip-suite-setup
```

### Проверка Переменных
```yaml
# В любом сценарии
test:
  - python: |
      print("Suite variables:")
      for k, v in ctx.variables.items():
          if not k.startswith('_'):
              print(f"  {k}: {v}")
```
