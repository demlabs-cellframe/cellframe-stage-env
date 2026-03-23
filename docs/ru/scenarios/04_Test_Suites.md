# Тест-Сьюты

## Формат Suite Descriptor

Тестовые сьюты используют YAML-дескриптор с полем `suite:`. Дескриптор определяет общие метаданные, переменные, includes, setup-шаги и список сценариев.
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

## E2E Дескрипторы Сьютов

E2E тесты используют облегчённый формат дескриптора с полем `suite:`.

### Размещение Файлов

```
# Паттерн A: Внешний дескриптор
tests/e2e/cdb/
├── kelvpn.yml            ← дескриптор рядом с директорией
└── kelvpn/
    ├── test_connect.yml
    └── test_auth.yml

# Паттерн B: Внутренний дескриптор
tests/e2e/cdb/
└── kelvpn/
    ├── suite.yml          ← дескриптор внутри директории
    ├── test_connect.yml
    └── test_auth.yml
```

### Формат Дескриптора

```yaml
suite: "KelVPN Client E2E Tests"
description: "Тесты KelVPN клиента"
tags: [e2e, kelvpn]

network:
  topology: default

variables:
  serial_count: 5
  cdb_endpoint: "http://node9:8079"

scenarios:
  - test_connect.yml
  - test_auth.yml

includes:
  - common/cdb-plugin-setup.yml

setup:
  - cli: "vpn_cdb version"
    node: node9
```

### Includes — Файловые Пути и Inline-Блоки

Список `includes` принимает как **пути к файлам** (строки), так и **inline-блоки данных** (словари). Записи обрабатываются в порядке объявления, что позволяет переопределять переменные между файловыми включениями:

```yaml
includes:
  - ../common/vpn_defaults.yml       # устанавливает vpn_client_count: 3
  - variables:                        # переопределение перед следующим include
      vpn_client_count: 5
  - ../common/vpn_nodes.yml          # использует vpn_client_count = 5
  - ../common/vpn_service_setup.yml
```

Inline-блоки могут содержать любые ключи, поддерживаемые включаемыми YAML-файлами: `variables`, `node_compose`, `node_compose_gen`, `defaults` и т.д.

### Приоритет Переменных

1. Переменные топологии (IP-адреса, имя сети) — наивысший
2. Секция `variables:` сценария
3. Секция `variables:` дескриптора сьюта — наименьший (дефолты)

Includes обрабатываются по порядку. Переменные каждого include вливаются под собственные переменные сьюта (значения сьюта имеют приоритет). Ранние includes задают значения по умолчанию, которые могут быть переопределены позднее.

---

## Динамическое Создание Нод

Сьюты могут динамически добавлять ноды Cellframe сверх базовой топологии через `node_compose` и `node_compose_gen`.

### node_compose — Явное Описание Нод

Определение отдельных нод в виде словаря, где ключи — имена Docker Compose сервисов:

```yaml
node_compose:
  vpn-server-1:
    id: 9                   # опционально — назначается автоматически
    role: full              # root | master | full (по умолчанию: full)
    source: genesis         # genesis | node-<id> | fresh (по умолчанию: genesis)
    packages: "iperf3 tcpdump"  # deb-пакеты через пробел
    config_overrides:       # опциональные переопределения конфига
      server:
        enabled: true
    setup:                  # опциональные шаги настройки после запуска ноды
      - cli: "srv_vpn enable"
        node: vpn-server-1

  vpn-client-1:
    source: genesis
    packages: "iperf3"
```

**Режимы source:**
- `genesis` — восстановление из базового genesis-снэпшота сьюта (по умолчанию)
- `node-N` — клонирование конфигов и данных существующей ноды N
- `fresh` — пустые директории, копируется только базовый `cellframe-node.cfg`

### node_compose_gen — Параметрическая Генерация

Генерация нескольких нод по шаблону с префиксом и счётчиком:

```yaml
node_compose_gen:
  - prefix: vpn-server
    count: "{{vpn_server_count}}"   # int или ссылка на {{переменную}}
    role: full
    source: genesis
    packages: "iperf3 tcpdump"

  - prefix: vpn-client
    count: "{{vpn_client_count}}"
    role: full
    source: genesis
    packages: "iperf3"
```

Раскрывается в `vpn-server-1`, `vpn-server-2`, ..., `vpn-client-1`, `vpn-client-2` и т.д. ID назначаются последовательно после последней ноды базовой топологии.

### Паттерн Общих Включений

Определяйте значения по умолчанию и генераторы нод в переиспользуемых includes:

```yaml
# common/vpn_defaults.yml
variables:
  vpn_server_count: 2
  vpn_client_count: 3
```

```yaml
# common/vpn_nodes.yml
node_compose_gen:
  - prefix: vpn-server
    count: "{{vpn_server_count}}"
    role: full
    source: genesis
    packages: "iperf3 tcpdump"
  - prefix: vpn-client
    count: "{{vpn_client_count}}"
    role: full
    source: genesis
    packages: "iperf3"
```

```yaml
# stress/suite.yml
includes:
  - ../common/vpn_defaults.yml
  - variables:                        # переопределение для этого сьюта
      vpn_client_count: 5
  - ../common/vpn_nodes.yml
```

---

## docker_compose_gen — Параметрическая Генерация Сервисов

Генерация нескольких не-cellframe контейнеров по шаблону:

```yaml
docker_compose_gen:
  - prefix: clientd
    count: "{{clientd_count}}"     # int или {{переменная}}
    image: "debian:bookworm-slim"  # Игнорируется при наличии build
    build:
      context: ../docker
      dockerfile: Dockerfile.clientd
      args: { BUILD_TYPE: Release }
    command: ["sleep", "infinity"]
    restart: "unless-stopped"
    packages: "iperf3 curl"        # apt пакеты
    cap_add: [NET_ADMIN]
    devices: ["/dev/net/tun:/dev/net/tun"]
    volumes: ["../configs:/etc/app:ro"]
    privileged: false
    environment:
      APP_MODE: client
```

Первый сервис получает полное `build` определение; остальные используют образ через `pull_policy: never`. `INSTANCE_ID` переменная окружения инжектится автоматически (1, 2, …N).

---

## docker_compose — Дополнительные Сервисы

Вливание произвольных Docker Compose сервисов в генерируемый `docker-compose.yml`:

```yaml
docker_compose:
  iperf-server:
    image: networkstatic/iperf3
    command: ["-s"]
    restart: "no"
    networks:
      vpntest:
        ipv4_address: 172.22.0.100

  redis:
    image: redis:7-alpine
    networks:
      vpntest:
```

Сервисы вливаются напрямую в Docker Compose файл. Имя сети должно совпадать с `[network].name` из `stage-env.cfg`.

Специальное поле `packages` можно добавить к сервисам Cellframe нод — оно удаляется перед merge в Compose и указанные deb-пакеты устанавливаются на все ноды Cellframe при старте:

```yaml
docker_compose:
  monitoring:
    image: grafana/grafana
    packages: "prometheus-node-exporter"  # ставится на все cf-ноды
    networks:
      vpntest:
```

---

## Полный Пример Стресс-Сьюта

```yaml
suite: VPN Stress Tests
description: >
  Комплексный стресс-тест: нагрузка множества клиентов, нагрузка блокчейна,
  мультихоп, переключение аплинков, обфускация трафика и сетевые сбои.
tags: [stress, vpn, load, e2e]

restore_snapshot: vpn_stress_state

includes:
  - ../common/vpn_defaults.yml
  # Переопределение:
  # - variables:
  #     vpn_client_count: 5
  - ../common/vpn_nodes.yml
  - ../common/vpn_service_setup.yml
  - ../common/fault_injection_helpers.yml

variables:
  iperf_duration: 120
  iperf_parallel: 4

docker_compose:
  iperf-server:
    image: networkstatic/iperf3
    command: ["-s"]
    restart: "no"
    networks:
      vpntest:
        ipv4_address: 172.22.0.100

scenarios:
  - test_multi_client_load.yml
  - test_blockchain_load.yml
  - test_multihop.yml
  - test_multi_uplink.yml
  - test_obfuscation.yml
  - test_network_faults.yml
```

---

## Лучшие Практики

1. **Общий setup в сьюте** — создавайте ресурсы один раз
2. **Используйте переменные сьюта** — для общих данных
3. **Держите сценарии независимыми** — не полагайтесь на порядок
4. **Семантичные имена** — `wallet_suite_alice`, не `w1`
5. **Разделяйте defaults и генераторы** — паттерн `vpn_defaults.yml` + `vpn_nodes.yml`
6. **Используйте inline переопределения** — для кастомизации shared includes в конкретном сьюте
7. **Предпочитайте node_compose_gen** — для однотипных нод вместо ручного node_compose

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
