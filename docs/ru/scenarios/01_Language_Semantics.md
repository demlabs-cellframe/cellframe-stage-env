# Семантика Языка

## Обзор

Язык сценариев Stage-Env — это декларативный DSL (Domain-Specific Language) для тестирования блокчейн-систем.

## Основные Принципы

### 1. Декларативная Природа
Описывайте **что** тестировать, а не **как**:
```yaml
- wait_for_datum: "{{tx_hash}}"  # Декларативно
```

Не нужно писать циклы опроса — система сама знает, как ждать.

### 2. Fail-Fast
Сценарии останавливаются на первой ошибке:
```yaml
- cli: "wallet info -w missing"
  expect: success  # Падает здесь, останавливает выполнение
```

Это позволяет быстро находить проблемы.

### 3. Template-First
Все строки поддерживают Jinja2:
```yaml
- cli: "tx_create -from {{wallet}}"
```

Шаблонизация — не опция, а основа языка.

## Области Видимости Переменных

### Глобальные
```yaml
variables:
  network_name: stagenet
  native_ticker: TCELL
```

Доступны во всём сценарии.

### На Уровне Шага
```yaml
- cli: "wallet new"
  save_wallet: addr  # Доступна как {{addr}}
```

Создаются при выполнении шага.

### На Уровне Сьюта (общие)
```yaml
# suite.yml (descriptor)
suite: "My Suite"
variables:
  shared_var: value
```

Доступны во всех сценариях сьюта.

### Предопределённые (ScenarioGlobalContext)
Автоматически доступны:

**Топология:**
- `{{all_nodes}}` — список всех нод
- `{{root_nodes}}` / `{{master_nodes}}` / `{{full_nodes}}` — по роли
- `{{first_root}}` / `{{last_root}}` — первая/последняя root
- `{{first_master}}` / `{{last_master}}` — первая/последняя master
- `{{seed_nodes}}` / `{{validator_nodes}}` — seed/validator списки
- `{{root_indices}}` / `{{master_indices}}` / `{{full_indices}}` / `{{all_indices}}`

**Количества:**
- `{{node_count}}` / `{{root_count}}` / `{{master_count}}` / `{{full_count}}`

**Сеть:**
- `{{network_name}}` / `{{topology_name}}` / `{{native_ticker}}`
- `{{node_port}}` / `{{node_ip}}` / `{{node_ips}}`
- `{{node_ip_root-1}}` / `{{node_ip_master-2}}` — IP конкретных нод

**Per-node IP (авто-генерация):**
- `{{node_ip_full-1}}` / `{{node_ip_full-2}}` — IP full-нод

**Версия (авто-определяется из DEB):**
- `{{cf_version}}` / `{{cf_version_major}}` / `{{cf_version_minor}}`

**Внутренние:**
- `{{_service_node_ids}}` — map имени сервиса в числовой ID ноды
- `{{project_root}}` — абсолютный путь к корню проекта

**CLI параметры** (`-P KEY=VALUE`) доступны как `{{KEY}}`.

## Лучшие Практики

1. **Семантичные имена** - `wallet_alice`, не `w1`
2. **Группируйте шаги** - используйте `group`
3. **Используйте `print`** - для отладки
4. **Явные таймауты** - не полагайтесь на defaults
5. **Fail-fast проверки** - проверяйте сразу после действия

## Философия Дизайна

### Интеллектуальные Ожидания
```yaml
# ПЛОХО: тупое ожидание
- wait: "60s"

# ХОРОШО: интеллектуальное ожидание
- wait: global_db_sync
  nodes: "{{all_nodes}}"
```

### Автоматические Ретраи
CLI команды автоматически повторяются при ошибках инициализации:
```yaml
- cli: "node dump"
  save_node: addr
  # Автоматически повторяется до 10 раз
```

### Мониторинг Жизненного Цикла
```yaml
- wait_for_datum: "{{tx_hash}}"
  # Отслеживает: mempool → block → propagation
```

Система знает весь жизненный цикл датума.
