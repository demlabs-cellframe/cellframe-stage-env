# Конструкции Языка

## Переменные

### Объявление
```yaml
variables:
  amount: 1000
  wallet: WkojSeUj...
  items: [1, 2, 3]
```

### Присваивание (set)
```yaml
- set: total
  value: "{{amount1 + amount2}}"
  eval: true
```

### Извлечение (CLI)
```yaml
- cli: "wallet new"
  save_wallet: address  # Извлечь адрес кошелька
  save_hash: tx_hash    # Извлечь 0x[hex] хэш
  save_token: ticker    # Извлечь тикер токена
  save_node: node_addr  # Извлечь адрес ноды
  save_to: raw_output   # Сохранить сырой вывод
```

### Доступ к Переменным
```yaml
# В YAML (Jinja2)
- cli: "wallet info -w {{wallet}}"

# В Python
- python: |
    val = ctx.get_variable('wallet')
    ctx.set_variable('new_var', val + '_suffix')
```

## Циклы

### for loop
```yaml
- for: item
  in: ["a", "b", "c"]
  steps:
    - print: "Item: {{item}}"
```

### for с range
```yaml
- for: i
  in: "range(3)"
  steps:
    - print: "Iteration {{i}}"
```

**Примечание:** Строковые значения `in` автоматически вычисляются как Python-выражения. `eval: true` не нужен (в отличие от `set` шагов).

### for по переменным
```yaml
- set: nodes
  value: ["node1", "node2", "node3"]
  
- for: node
  in: "{{nodes}}"
  steps:
    - cli: "node dump"
      node: "{{node}}"
```

### loop (устаревший)
```yaml
- loop: 3
  steps:
    - cli: "wallet new -w wallet{{iteration}}"
```

**Примечание:** `loop` оставлен для обратной совместимости. Используйте `for` в новом коде.

### while loop
```yaml
- while: "{{ctx.get_variable('count', 0) < 10}}"
  max_loops: 100
  steps:
    - cli: "check status"
      save_to: status
    - set: count
      value: "{{count + 1}}"
      eval: true
```

## Условия

### if-then-else
```yaml
- if: "{{balance > 0}}"
  then:
    - print: "Has balance: {{balance}}"
  else:
    - print: "No balance"
```

### if с ctx
```yaml
- if: "ctx.has_variable('wallet')"
  then:
    - cli: "wallet info -w {{wallet}}"
```

### switch-case
```yaml
- switch: "{{status}}"
  cases:
    "success":
      - print: "Operation succeeded"
    "pending":
      - wait: "5s"
      - cli: "check again"
    "error":
      - print: "Operation failed"
  default:
    - print: "Unknown status: {{status}}"
```

## Группы

Группы объединяют связанные шаги под общим именем и опциональными defaults.
Имя можно задать ключом `group:` или `name:` — оба варианта эквивалентны:

### Базовая Группа
```yaml
- group: Token Operations
  steps:
    - cli: "token_decl ..."
    - cli: "token_emit ..."

- name: Alternative syntax
  steps:
    - print: "Ключи 'group' и 'name' взаимозаменяемы"
```

### Группа с Defaults
```yaml
- group: Zerochain Setup
  defaults:
    chain: zerochain
    network: stagenet
  steps:
    - cli: "token_decl -t NEWTOKEN"
      # chain и network применятся автоматически
```

### Вложенные Группы
```yaml
- group: Outer
  defaults:
    timeout: 60
  steps:
    - group: Inner
      defaults:
        node: node1
      steps:
        - cli: "command"
          # timeout=60, node=node1
```

## Defaults

### Глобальные Defaults
```yaml
defaults:
  node: node1
  timeout: 60
  cli:
    net: stagenet
    chain: main
    token: TCELL
```

### Секционные Defaults
```yaml
setup:
  defaults:
    timeout: 120
  steps:
    - cli: "slow command"

test:
  defaults:
    timeout: 30
  steps:
    - cli: "fast command"
```

### Порядок Применения
1. Глобальные defaults (верхний уровень)
2. Секционные defaults (setup/test)
3. Групповые defaults
4. Параметры на уровне шага (наивысший приоритет)

```yaml
defaults:
  timeout: 60        # Приоритет 1

test:
  defaults:
    timeout: 30      # Приоритет 2
  steps:
    - group: G1
      defaults:
        timeout: 10  # Приоритет 3
      steps:
        - cli: "cmd"
          timeout: 5 # Приоритет 4 (используется)
```

## Helper Функции для set

### join_vars
```yaml
- set: addrs_list
  value: join_vars('addr_', 3, ',')
  eval: true
  # Результат: "val0,val1,val2"
```

### regex_extract
Извлекает первое совпадение (одну группу): `regex_extract(text, pattern, group=1) -> str`
```yaml
- set: hash
  value: regex_extract(output, r'hash:\s*(\w+)', 1)
  eval: true
```

### find_all
Возвращает список всех совпадений: `find_all(text, pattern) -> list`
```yaml
- set: _serials
  value: "find_all(raw_output, r'[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}')"
  eval: true

- set: first_serial
  value: "_serials[0]"
  eval: true
```

### concat
```yaml
- set: full_name
  value: concat(first_name, ' ', last_name)
  eval: true
```

### get_var
```yaml
- set: dynamic
  value: get_var('addr_' + str(i), 'default')
  eval: true
```

## Специальные Переменные

### iteration
Доступна в `loop`:
```yaml
- loop: 3
  steps:
    - print: "Iteration: {{iteration}}"
```

### item/i/key/value
Доступны в `for`:
```yaml
- for: item
  in: [1, 2, 3]
  steps:
    - print: "{{item}}"
```
