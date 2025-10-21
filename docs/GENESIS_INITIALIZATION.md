# 🌟 Genesis Initialization Guide

Руководство по инициализации genesis состояния для Cellframe Stagenet.

## 📋 Обзор

Genesis initialization - это процесс первичной настройки сети после запуска нод, включающий:

1. **Настройка root nodelists** - корневые ноды добавляют друг друга в nodelists
2. **Создание validator stake orders** - регистрация валидаторов в сети
3. **Регистрация node aliases в GDB** - добавление записей для node discovery
4. **Переключение нод в online режим** - активация сетевых соединений

## 🔑 Ключевые концепции

### Root Node Nodelists

**Что это**: Nodelist - это локальный список нод, с которыми нода может соединяться. Каждая нода поддерживает свой nodelist в памяти.

**Зачем нужны для root нод**:
- Root (seed) ноды - это bootstrap узлы сети, управляющие топологией
- Они должны **сразу знать друг о друге** при старте
- Каждая root нода добавляет **сначала себя**, потом **все остальные root ноды** в свой nodelist
- Остальные ноды (master, full) добавляются в nodelist **динамически** по запросу через команды

**Команда**:
```bash
nodelist add -net stagenet -addr 0123::4567::89AB::CDEF -host 172.20.0.11 -port 8079
```

**Порядок добавления для root ноды**:
1. Добавить себя в nodelist (самоидентификация)
2. Добавить все остальные root ноды

### Validator Stake Orders

**Что это**: Stake orders - это записи в Global DB, которые определяют условия работы валидатора:
- `value_min` - минимальная сумма стейка (в datoshi)
- `value_max` - максимальная сумма стейка (в datoshi)
- `tax` - процент комиссии валидатора
- `cert` - сертификат для подписи блоков
- `node_addr` - адрес ноды валидатора

**Зачем нужны**: 
- ESBocs consensus **требует** наличие stake order для каждого валидатора
- Код проверяет `minimum_fee` из order при инициализации консенсуса (строка 665 в `dap_chain_cs_esbocs.c`)
- Без order валидатор **не может** участвовать в консенсусе (получит ошибку "Switch off validator mode")

**Исключение - PoA mode**:
- `poa_mode=true` в `main.cfg` **должен** пропускать проверку `minimum_fee`
- Но в текущей версии SDK (bug) эта проверка выполняется **всегда**
- Поэтому даже в PoA режиме мы создаём orders для stagenet

### Node Aliases в GDB

**Что это**: Записи в Global DB формата `node_alias.<node_addr> = <ip:port>`

**Зачем нужны**:
- Позволяют нодам находить друг друга по validator адресу
- ESBocs использует `validators_addrs` (hex адреса) для формирования консенсуса
- Ноды должны знать `IP:PORT` для каждого validator адреса из конфига

**Формат**:
```bash
global_db set -net stagenet node_alias.0123::4567::89AB::CDEF 172.20.0.11:8079
```

## 🚀 Автоматическая инициализация

Stage-env **автоматически** выполняет genesis initialization при запуске:

```bash
./stage-env start
```

**Что происходит**:

1. **Запуск нод** - Docker Compose поднимает контейнеры
2. **Ожидание готовности** - Health checker проверяет доступность нод
3. **Настройка root nodelists**:
   ```python
   await self.genesis._setup_root_nodelists(validator_nodes)
   ```
   - Каждая root нода добавляет себя в nodelist
   - Затем добавляет все остальные root ноды
   - Команда: `nodelist add -net stagenet -addr <addr> -host <ip> -port <port>`
   
4. **Создание validator orders**:
   ```python
   await self.genesis.initialize(node_configs)
   ```
   - Для каждой root ноды (validator) создаётся order
   - Команда: `srv_stake order create validator`
   - Параметры: `value_min=100`, `value_max=10000`, `tax=10`
   
5. **Регистрация node aliases**:
   ```python
   await self.genesis.register_node_aliases(node_configs)
   ```
   - Для каждой ноды регистрируется `node_alias.<addr> = <ip:port>`
   
6. **Переключение в online**:
   ```bash
   net -net stagenet go online
   ```
   - Явно активируется сетевой режим для всех нод

## 📝 Конфигурация

### PoA Mode (main.cfg)

```ini
[esbocs]
# PoA mode - bypass stake order requirements for new stagenet
poa_mode=true
```

**Важно**: В текущей версии SDK это **не работает полностью** - проверка `minimum_fee` всё равно выполняется. Поэтому stage-env создаёт orders даже с `poa_mode=true`.

### Validators Addresses (main.cfg)

```ini
[esbocs]
# Validator addresses (dynamically filled from validator certs)
validators_addrs=VALIDATORS_ADDRS_PLACEHOLDER
```

Заполняется автоматически при генерации конфигов из `validator_addr.txt` файлов.

### Auto Online (cellframe-node.cfg)

```ini
[general]
# Auto bring up links and sync everything over them
auto_online=true
```

Должен автоматически переключать ноды в online при старте, но не всегда работает. Genesis initializer выполняет `net go online` явно.

## 🔧 Ручная инициализация

Если нужно выполнить genesis initialization вручную:

### 1. Настройка Root Node Nodelist

```bash
# Войти в контейнер root ноды
docker exec -it cellframe-stage-node1 bash

# Добавить себя в nodelist (node_addr из node_addr.txt)
cellframe-node-cli nodelist add \
  -net stagenet \
  -addr 0123::4567::89AB::CDEF \
  -host 172.20.0.11 \
  -port 8079

# Добавить другие root ноды
cellframe-node-cli nodelist add \
  -net stagenet \
  -addr ABCD::EF01::2345::6789 \
  -host 172.20.0.12 \
  -port 8079

# Проверить nodelist
cellframe-node-cli nodelist dump -net stagenet
```

**Важно**: Для остальных нод (master, full) nodelist заполняется **динамически** через команды в сценариях, не при genesis инициализации.

### 2. Создание Validator Order

```bash
# Войти в контейнер первой ноды
docker exec -it cellframe-stage-node1 bash

# Создать validator order
cellframe-node-cli srv_stake order create validator \
  -net stagenet \
  -value_min 100000000000000000000 \
  -value_max 10000000000000000000000 \
  -tax 10 \
  -cert stagenet.master.0 \
  -node_addr 0123::4567::89AB::CDEF \
  -H hex
```

**Параметры**:
- `value_min` / `value_max` - в datoshi (1 token = 10^18 datoshi)
- `tax` - процент (10 = 10%)
- `cert` - имя сертификата валидатора (без `.dcert`)
- `node_addr` - hex адрес из `validator_addr.txt`
- `-H hex` - формат вывода хеша order

### 3. Регистрация Node Alias

```bash
# Зарегистрировать node alias
cellframe-node-cli global_db set \
  -net stagenet \
  node_alias.0123::4567::89AB::CDEF \
  172.20.0.11:8079
```

### 4. Переключение в Online

```bash
# Перейти в online режим
cellframe-node-cli net -net stagenet go online

# Проверить статус
cellframe-node-cli net -net stagenet get status
```

## 🐛 Troubleshooting

### "No valid order found" ошибка

```
[ERR] No valid order found was signed by this validator delegated key. Switch off validator mode.
```

**Причина**: Отсутствует validator order для этой ноды.

**Решение**:
1. Проверить наличие order: `srv_stake order list validator -net stagenet`
2. Создать order вручную (см. выше)
3. Перезапустить ноду: `./stage-env restart node1`

### "Can't open cert file" ошибка

```
[ERR] Can't open cert file '/opt/cellframe-node/var/lib/ca/stagenet.master.1.dcert'
```

**Причина**: Сертификат валидатора отсутствует в `/var/lib/ca`.

**Решение**:
1. Проверить кеш сертификатов: `ls cache/data/node2/lib/ca/`
2. Пересоздать сертификаты: `./stage-env start --clean`

### Ноды не соединяются (active: 0)

```
[net.stagenet] links (opened (local_addr): 0 connected: 0 active: 0)
```

**Причина**: Отсутствуют node_alias записи в GDB или неправильный `seed_nodes_hosts`.

**Решение**:
1. Проверить node_alias: `global_db get -net stagenet node_alias.*`
2. Проверить `seed_nodes_hosts` в `stagenet.cfg` - должен быть формат `[IP:PORT,IP:PORT]`
3. Вручную зарегистрировать node aliases (см. выше)

### Validator mode отключается

```
[NOTICE] [cs-esbocs] Switched off validating for this node
```

**Причина**: 
- Отсутствует validator order
- Или `blocks-sign-cert` не установлен в `stagenet.cfg`

**Решение**:
1. Проверить `blocks-sign-cert` в `etc/network/stagenet.cfg`: должен быть `blocks-sign-cert=stagenet.master.N`
2. Создать validator order (см. выше)
3. Проверить сертификат: `cert dump -cert stagenet.master.0`

## 📚 Дополнительные ресурсы

- **Code**: `tests/stage-env/src/network/genesis.py` - реализация genesis initializer
- **Config**: `tests/stage-env/config/templates/chains/main.cfg` - конфигурация ESBocs
- **Docs**: `tests/stage-env/docs/ARCHITECTURE.md` - архитектура stage-env

## 🔗 Связанные команды

```bash
# Проверить статус валидаторов
cellframe-node-cli net -net stagenet get status

# Проверить nodelist (кто добавлен в список)
cellframe-node-cli nodelist dump -net stagenet

# Список validator orders
cellframe-node-cli srv_stake order list validator -net stagenet -full

# Список node aliases
cellframe-node-cli global_db get -net stagenet node_alias.*

# Проверить консенсус
cellframe-node-cli block list -chain main -net stagenet

# Логи ноды
docker logs -f cellframe-stage-node1
```

