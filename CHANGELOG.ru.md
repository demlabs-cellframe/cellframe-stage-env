# Changelog — Stage-Env

> [English version](CHANGELOG.md)

## [1.2] — 2026-03-04

### Новые возможности

#### Динамическое создание нод из сьютов (`node_compose`, `node_compose_gen`)

Сьют может добавлять ноды Cellframe сверх базовой топологии без ручной правки
Docker Compose.

`node_compose` — явное описание отдельных нод:

```yaml
node_compose:
  vpn-server-1:
    role: full
    source: genesis         # genesis | node-<id> | fresh
    packages: "iperf3 tcpdump"
    setup:
      - cli: "srv_vpn enable"
        node: vpn-server-1
```

`node_compose_gen` — параметрическая генерация по шаблону:

```yaml
node_compose_gen:
  - prefix: vpn-client
    count: "{{vpn_client_count}}"
    role: full
    source: genesis
    packages: "iperf3"
```

Раскрывается в `vpn-client-1`, `vpn-client-2`, ..., ID назначаются автоматически
после последней ноды базовой топологии.

#### Произвольные Docker-сервисы (`docker_compose`)

Встраивание сторонних контейнеров (iperf, redis, grafana и пр.) прямо
в дескриптор сьюта:

```yaml
docker_compose:
  iperf-server:
    image: networkstatic/iperf3
    command: ["-s"]
    networks:
      vpntest:
        ipv4_address: 172.22.0.100
```

#### Гибкие includes с inline-переопределениями

`includes` теперь принимает как файловые пути, так и inline-блоки данных,
что позволяет переопределять переменные между файловыми включениями:

```yaml
includes:
  - ../common/vpn_defaults.yml       # vpn_client_count: 3
  - variables:                        # override
      vpn_client_count: 5
  - ../common/vpn_nodes.yml          # использует 5
```

#### Self-Contained Cert-Generator

Multi-stage `Dockerfile.cert-generator` клонирует SDK-репозитории при сборке.
Не требует монтирования SDK с хоста — бинарник запечён в образ.
Конфигурируется через `SDK_BRANCH`, `CELLFRAME_SDK_REPO`, `DAP_SDK_REPO`.
`CMakeLists.txt` упрощён: линковка против `cellframe_sdk` и `dap-sdk` shared libs
вместо ручного перечисления 15+ статических библиотек.

#### Glob-паттерны для локальных пакетов

`local_path` в конфиге поддерживает shell glob (`*.deb`, `build-*/*.deb`).
Выбирается последний match (по алфавиту) для детерминизма.

#### JSON CLI Output Parsing (SDK 6.0+)

`NodeStateManager` и `DockerComposeManager` парсят JSON-формат статуса.
Fallback на текстовый формат (5.x) при ошибке JSON — совместимость
с SDK 5.x и 6.0+.

#### Автоопределение версии genesis-сценариев

Фреймворк определяет мажорную версию Cellframe Node из DEB-пакета и
автоматически выбирает genesis-сценарии `v5.x/` или `v6.x/`.
Переменные `cf_version_major`, `cf_version_minor` доступны в рантайме.

#### Динамическое имя сети

Убрано хардкоженное `stagenet`. Поля `WaitForDatumStep.network` и
`NetworkWaitStep.network` по умолчанию `"{{network_name}}"` — имя
берётся из конфигурации.

#### Новые операции `docker_op`

- `pause` / `unpause` — заморозка/разморозка контейнера для имитации потери связи
- `logs` — получение логов с `tail:` (кол-во строк) и `save:` (в переменную)
- `exec` — выполнение команды в контейнере с `save:`

```yaml
- docker_op: pause
  services: "node-1"

- docker_op: logs
  services: "node-1"
  tail: 50
  save: node_logs

- docker_op: exec
  services: "node-1"
  command: "pgrep cellframe-node"
  save: pid_output
```

#### Расширения `snapshot`

- Операция `verify` — проверяет существование снэпшота без исключения
- Поле `save:` — сохраняет результат (`True`/`False`) в переменную

```yaml
- snapshot: verify
  name: cdb_ready
  save: has_cdb_snapshot
```

#### Расширения `wait`

- `group:` / `key:` — ожидание синхронизации GlobalDB по группе/ключу
- `optional: true` — timeout не бросает исключение (для retry-циклов)

#### Операнд `dpkg`

Установка DEB-пакетов на ноды прямо из сценария:

```yaml
- dpkg: /path/to/package.deb
  nodes: ["node-1", "node-2"]
```

#### Кастомные операнды (`CustomOperandStep`)

Система расширяемых операндов — регистрация новых операндов через
`operand_registry` без изменения ядра фреймворка.

#### `StepGroup`: alias `group:` / `name:`

Оба ключа эквивалентны для именования группы:

```yaml
- group: "Verify certs"    # OK
- name: "Verify certs"     # тоже OK
```

#### Regex в `contains`

CLI-проверки поддерживают регулярные выражения в `contains`:

```yaml
- cli: "block list"
  contains: "have blocks: [1-9]"
```

### Исправления

- **eval() Namespace Unification** — переменные и builtins объединены в один
  dict для `eval()`. Выражения `len(items) == 3` и `range(max_nodes)` теперь
  работают корректно
- **CLI Parser Always Initialized** — дефолты применяются даже без
  `global_defaults.cli`
- **CLI Defaults Applied Without Options Whitelist** — дефолты добавляются
  для команд, не попавших в кэш help
- `expect_output:` (молча игнорировалось Pydantic) заменено на `contains:`
  во всех genesis/e2e сценариях
- Синтаксис `for: { var: x, in: [...] }` исправлен на корректный
  `for: x` / `in: [...]`
- `expect:` удалено из `check:` секций (CLICheck не поддерживает это поле)
- `ToolStep` — добавлена подстановка переменных в `node` (`ctx.substitute`)
- `Validator` — исправлена работа с `SectionConfig`/`CheckSectionConfig`,
  добавлена защита от `SuiteDescriptor`
- CLI check executor — ловит `asyncio.TimeoutError` вместо
  `subprocess.TimeoutExpired`
- RPC step — `ctx.substitute()` вызывается только для строковых параметров
- Bash step — защита от `None` timeout (fallback на 300с)
- Нормализация булевых значений в конфигах

### Шаблоны конфигурации

Реорганизация под мультиверсионность:

```
config/templates/
├── v5.x/cellframe-node.cfg.j2
├── v6.x/cellframe-node.cfg.j2
├── network.cfg.j2             (ранее stagenet.cfg.j2)
└── chains/
    ├── main.cfg.j2
    └── zerochain.cfg.j2
```

### Документация

Значительно расширена (EN + RU):

- **02_Language_Constructs** — while loop, for по переменным, if с ctx,
  вложенные группы, helper-функции (`join_vars`, `concat`, `get_var`,
  `regex_extract`, `find_all`), специальные переменные
- **03_All_Operands** — `logs`, `exec`, `dpkg`, `pause`/`unpause`, `cp`
- **04_Test_Suites** — node_compose, node_compose_gen, docker_compose,
  inline includes, shared include pattern, debugging suites
- **Glossary / Architecture** — DockerOpStep, StepGroup актуализированы
- Исправлены: `snapshot: save` → `create`, `max_iterations` → `max_loops`,
  дублирующиеся TOC, битые ссылки

### Тестирование

- +43 unit-теста (58 → 101)
- Новые модули: `test_core_advanced.py`, `test_custom_operands.py`,
  `test_cli_parser_advanced.py`

### Статистика

- **99 файлов** затронуто
- **+7 149 / −1 588** строк
- **27 коммитов**

---

## [1.1] — 2026-01-29

### Новые возможности

#### Print Operand
- `print` шаг для отладки сценариев с Jinja2-шаблонами

```yaml
- print: "Token hash: {{token_hash}}"
```

#### Multi-Node Global DB Sync
- `global_db_sync` поддерживает несколько нод одновременно
- Параллельная проверка вместо последовательной — **3x** ускорение

#### Block Created Waiter
- `block_created` для мониторинга создания блоков с параметром `min_blocks`

#### Интеллектуальные waiters в genesis-сценариях
- Фиксированные `wait: "Ns"` заменены на интеллектуальное ожидание
  с мониторингом состояния

### Исправления

- **CLI Readiness** — retry с exponential backoff при `node dump`
  после `wait_network: online` (до 10x быстрее)
- **Config Not Applied After Restart** — `docker_op: restart` заменён на
  `stop` + `start` для корректной перезагрузки конфигов
- **Global DB Sync Single Node** — проверка всех нод вместо одной первой
- **is_add_directly** — параметр корректно устанавливается в genesis для
  mainchain
- **MDBX race condition** — workaround перед `node dump`

### Производительность

| Операция | Было | Стало |
|----------|------|-------|
| Multi-node GDB sync (6 нод) | 180s | 60s |
| CLI ready wait | 5s fixed | 0.5-5s dynamic |
| Datum processing | 13s fixed | ~3s intelligent |
| Genesis scenarios | ~5 мин | ~2 мин |

### Документация

- Полный набор документации EN + RU (6 разделов по сценариям,
  Developer Guide, Architecture)
- Система сборки PDF (`docs/build.sh`)

### Тестирование

- +13 новых тестов
- Исправлено 10 падающих тестов
- E2E, functional и regression тест-фреймворки

---

## [1.0] — 2026-01-20

Первый стабильный релиз. См. историю git.
