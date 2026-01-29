# Учебник по тестовым сценариям

**Современное руководство по написанию декларативных E2E тестов для Cellframe Node**

Добро пожаловать! Этот учебник научит вас писать автоматизированные тесты используя YAML-based язык сценариев. Знания программирования не требуются.

## 📚 Содержание

1. [Введение](#введение)
2. [Урок 1: Первый тест](#урок-1-первый-тест)
3. [Урок 2: Использование defaults](#урок-2-использование-defaults)
4. [Урок 3: Переменные и извлечение данных](#урок-3-переменные-и-извлечение-данных)
5. [Урок 4: Операции с токенами](#урок-4-операции-с-токенами)
6. [Урок 5: Надёжное ожидание с wait_for_datum](#урок-5-надёжное-ожидание-с-wait_for_datum)
7. [Урок 6: Переиспользование компонентов через includes](#урок-6-переиспользование-компонентов-через-includes)
8. [Урок 7: Тестовые наборы (suites)](#урок-7-тестовые-наборы-suites)
9. [Лучшие практики](#лучшие-практики)

---

## Введение

### Что такое тестовый сценарий?

Тестовый сценарий - это YAML файл, описывающий:
- **Метаданные** - имя, описание, теги
- **Сеть** - топология (обычно просто `topology: default`)
- **Setup** - подготовительные шаги (опционально)
- **Test** - основные тестовые действия
- **Check** - проверка результатов (опционально)

### Минимальный пример

```yaml
name: Проверка версии
description: Проверить что CLI отвечает на команду version

network:
  topology: default

test:
  - cli: version
    contains: "Cellframe"
```

Этот сценарий:
1. Использует дефолтную топологию (3 root + 3 master + 1 full нода)
2. Выполняет `cellframe-node-cli version` на node1
3. Проверяет что вывод содержит "Cellframe"

### Как запустить?

```bash
# Один сценарий
cd tests
./stage-env/stage-env run-tests e2e/my_test.yml

# Целый suite
./stage-env/stage-env run-tests e2e/token/

# Через run.sh (полный цикл)
./run.sh
```

---

## Урок 1: Первый тест

**Задача:** Создать кошелёк и проверить его существование.

**Решение** (`lesson1_wallet.yml`):

```yaml
name: Урок 1 - Создание кошелька
description: Изучаем базовые CLI команды
tags: [tutorial, lesson1, wallet]

# Используем default топологию (network опционально - по умолчанию 'topology: default')
network:
  topology: default

test:
  # Шаг 1: Создать кошелёк
  - cli: wallet new -w my_first_wallet
    node: node1         # Выполнить на node1 (по умолчанию)
    expect: success     # Ожидать успешный результат (по умолчанию)
    wait: 1s            # Подождать 1 секунду после команды

  # Шаг 2: Проверить что создался
  - cli: wallet list
    contains: my_first_wallet
```

**Что происходит:**
1. stage-env восстанавливает чистое состояние сети из snapshot (~2s)
2. `wallet new` выполняется через `docker exec node1 cellframe-node-cli wallet new -w my_first_wallet`
3. Система ждёт 1 секунду
4. `wallet list` выполняется
5. Вывод проверяется на наличие "my_first_wallet"

**💡 Ключевые моменты:**
- `node: node1` - по умолчанию, можно опустить
- `expect: success` - по умолчанию, можно опустить
- `wait: 1s` - даёт время на завершение операции

---

## Урок 2: Использование defaults

**Задача:** Уменьшить повторения используя иерархические defaults.

**Без defaults:**

```yaml
test:
  - cli: token list
    node: node1
    wait: 3s
  
  - cli: wallet list
    node: node1
    wait: 3s
  
  - cli: version
    node: node1
    wait: 3s
```

**С defaults:**

```yaml
# Глобальные defaults - применяются ко всем шагам
defaults:
  node: node1
  wait: 3s

test:
  - cli: token list
  - cli: wallet list
  - cli: version
  
  # Переопределение для конкретного шага
  - cli: token info -name TEST
    wait: 10s    # Этот шаг ждёт 10s вместо 3s
```

**Преимущества:**
- Меньше повторений
- Проще поддерживать
- Понятное намерение

**Иерархия defaults:**
1. **Глобальные** (`defaults:` на верхнем уровне)
2. **Секции** (`setup:` / `test:` / `check:` могут иметь свои defaults)
3. **Группы** (группировка шагов с локальными defaults)
4. **Шаг** (параметры конкретного шага переопределяют всё)

---

## Урок 3: Переменные и извлечение данных

**Задача:** Извлечь адрес кошелька и использовать в последующих шагах.

**Современный подход с save_wallet:**

```yaml
name: Урок 3 - Извлечение данных
description: Извлечение и использование адреса кошелька

network:
  topology: default

test:
  # Шаг 1: Создать кошелёк
  - cli: wallet new -w test_wallet
  
  # Шаг 2: Получить адрес с автоматической валидацией
  - cli: wallet info -w test_wallet
    save_wallet: my_address
    # Одна строка! Авто-извлечение и валидация base58 + checksum
  
  # Шаг 3: Использовать извлечённый адрес
  - cli: balance -addr {{my_address}}
    save: balance_result

check:
  - cli: wallet info -w test_wallet
    contains: "{{my_address}}"    # Проверить что адрес в выводе
```

**Save хелперы:**
- `save_wallet: var` - извлекает и валидирует wallet address 
- `save_hash: var` - извлекает и валидирует hash (0x[hex]{64})
- `save_node: var` - извлекает и валидирует node address 
- `save: var` - сохраняет весь вывод

**Сравнение:**

```yaml
# ✅ Современный - чисто и понятно
- cli: wallet info -w test
  save_wallet: addr

# ❌ Старый - verbose (устарел)
# `extract_to` устарел. Используйте `save_wallet`, `save_hash`, `save_node` и т.д.
```

---

## Урок 4: Операции с токенами

**Задача:** Создать токен, эмитировать и проверить.

```yaml
name: Урок 4 - Операции с токенами
description: Полный workflow работы с токеном

# Подключаем общие компоненты
includes:
  - common/create_test_cert.yml  # Создаёт test_cert для подписи
  - common/set_net_default.yml   # Автоматически добавляет -net

setup:
  # Создать кошелёк для получения токенов
  - cli: wallet new -w my_wallet
  
  - cli: wallet info -w my_wallet
    save_wallet: wallet_addr

test:
  # Шаг 1: Объявить токен
  - cli: token_decl -token LESSON4 -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
    save: token_hash
    wait: 3s
  
  # Шаг 2: Эмитировать токены
  - cli: token_emit -token LESSON4 -value 10000 -addr {{wallet_addr}} -certs test_cert
    save: emission_tx
    wait: 3s

check:
  # Проверить что токен существует
  - cli: token info -name LESSON4
    contains: "LESSON4"
```

**💡 Ключевые моменты:**
- `create_test_cert.yml` создаёт сертификат ОДИН раз на уровне suite (не для каждого сценария)
- `set_net_default.yml` добавляет `-net stagenet` автоматически
- `-certs test_cert` явно используется для операций подписи
- `save:` автоматически сохраняет hash для token/emission команд

---

## Урок 5: Надёжное ожидание с wait_for_datum

**Задача:** Дождаться обработки транзакции в блокчейне.

**❌ Старый способ (ненадёжный):**

```yaml
test:
  - cli: token_emit -token TEST -value 1000 -addr {{addr}} -certs test_cert
    save: tx_hash
  
  - wait: 30s  # Сколько? Мало = нестабильный тест, много = медленно
```

**✅ Современный способ:**

```yaml
test:
  - cli: token_emit -token TEST -value 1000 -addr {{addr}} -certs test_cert
    save: tx_hash
  
  # Интеллектуальное ожидание - мониторит реальный lifecycle датума
  - wait_for_datum: "{{tx_hash}}"
```

**Как работает wait_for_datum:**
1. **0.5s** - проверяет появление датума в mempool (если нет → REJECTED, fail fast!)
2. **До 120s** - ждёт включения датума в блок
3. **До 180s** - ждёт распространения блока по сети
4. Возвращается немедленно по завершении (без лишнего ожидания!)

**Пример с несколькими датумами:**

```yaml
test:
  - cli: token_decl -token T1 -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
    save: token1
  
  - cli: token_decl -token T2 -total_supply 2000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
    save: token2
  
  # Ждать оба токена
  - wait_for_datum:
      - "{{token1}}"
      - "{{token2}}"
```

---

## Урок 6: Переиспользование компонентов через includes

**Задача:** Использовать общие компоненты для уменьшения дублирования.

**Общие includes в `tests/common/`:**
- `create_test_cert.yml` - Создаёт временный сертификат для подписи
- `set_net_default.yml` - Автоматически добавляет `-net {{network_name}}`
- `wallets/create_wallet.yml` - Создаёт тестовый кошелёк
- `networks/single_node.yml` - Минимальная топология

**Пример:**

```yaml
name: Урок 6 - Includes
description: Переиспользуемые компоненты

includes:
  - common/create_test_cert.yml
  - common/set_net_default.yml
  - common/wallets/create_wallet.yml

# Теперь доступны:
# - переменная test_cert
# - переменная wallet_addr
# - -net автоматически добавляется к CLI командам

test:
  # сертификат и -net добавлены автоматически!
  - cli: token_decl -token INC -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
```

**Создание своего include:**

`tests/common/my_template.yml`:
```yaml
# Переиспользуемый шаблон для создания токена

setup:
  - cli: token_decl -token {{token_name}} -total_supply {{supply}} -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert

variables:
  token_created: true
```

Использование:
```yaml
includes:
  - common/my_template.yml

variables:
  token_name: MYTOKEN
  supply: 5000000

test:
  - cli: token list
    contains: "{{token_name}}"
```

---

## Урок 7: Тестовые наборы (suites)

**Задача:** Организовать связанные тесты в suites с общим setup.

**Структура suite:**
```
tests/e2e/token/
├── token.yml              # Suite descriptor
├── 001_token_decl.yml     # Тестовый сценарий
├── 002_token_emit.yml     # Тестовый сценарий
└── 003_token_list.yml     # Тестовый сценарий
```

**Suite descriptor** (`token.yml`):

```yaml
suite: "Token Operations Suite"
description: "E2E тесты для жизненного цикла токенов"
tags: [e2e, token]

# Default сеть для всех сценариев в этом suite
network:
  topology: default

# Общие includes - применяются ко всем сценариям
includes:
  - common/create_test_cert.yml
  - common/set_net_default.yml

# Suite-level setup - выполняется ОДИН раз перед всеми сценариями
setup:
  - wait: 5s
```

**Индивидуальный сценарий** (`001_token_decl.yml`):

```yaml
name: Объявление токена
description: Тест создания токена

# НЕ нужны includes! Наследуются от suite descriptor
# НЕ нужна network! Наследуется от suite

test:
  - cli: token_decl -token TEST -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert
    save: token_hash

check:
  - cli: token info -name TEST
    contains: "TEST"
```

**Преимущества:**
- Сертификат создаётся ОДИН раз на suite (не для каждого сценария)
- Общий setup разделяется между сценариями
- Чистое состояние сети восстанавливается между suites (через snapshots)
- Логическая группировка связанных тестов

---

## Лучшие практики

### 1. Эффективно используйте defaults

```yaml
# ✅ Хорошо
defaults:
  node: node1
  wait: 3s

test:
  - cli: token list
  - cli: wallet list
  - cli: version

# ❌ Плохо - повторения
test:
  - cli: token list
    node: node1
    wait: 3s
  - cli: wallet list
    node: node1
    wait: 3s
```

### 2. Используйте wait_for_datum вместо фиксированных wait

```yaml
# ✅ Хорошо - надёжно и быстро
- cli: token_emit -token TEST -value 1000 -addr {{addr}} -certs test_cert
  save: tx
- wait_for_datum: "{{tx}}"

# ❌ Плохо - медленно и ненадёжно
- cli: token_emit -token TEST -value 1000 -addr {{addr}} -certs test_cert
- wait: 30s  # Слишком долго? Слишком мало?
```

### 3. Правильно извлекайте данные

```yaml
# ✅ Хорошо - короткий save helper
- cli: wallet info -w my_wallet
  save_wallet: addr

# ❌ Плохо - сохраняет весь вывод
- cli: wallet info -w my_wallet
  save: wallet_output
  # Теперь нужно парсить вручную
```

### 4. Используйте includes для общего setup

```yaml
# ✅ Хорошо - переиспользуемо
includes:
  - common/create_test_cert.yml
  - common/set_net_default.yml

# ❌ Плохо - дублирование setup в каждом тесте
setup:
  - tool: cert create test_cert sig_dil
# ... то же самое в 50 тестах
```

### 5. Группируйте тесты в suites

```yaml
# ✅ Хорошо - suite descriptor
# tests/e2e/token.yml
suite: "Token Suite"
includes:
  - common/create_test_cert.yml

# Затем отдельные тесты не повторяют includes

# ❌ Плохо - каждый тест включает одно и то же
# 001_test.yml, 002_test.yml, 003_test.yml все имеют:
includes:
  - common/create_test_cert.yml
```

### 6. Будьте явными с обязательными параметрами

```yaml
# ✅ Хорошо - явно и понятно
- cli: token_decl -token TEST -total_supply 1000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs test_cert

# ❌ Плохо - полагаемся на скрытые defaults
- cli: token_decl -token TEST -total_supply 1000000
# Где -decimals, -signs_total? Неясно!
```

### 7. Используйте описательные имена

```yaml
# ✅ Хорошо
name: "Перевод токенов между двумя кошельками"
description: "Создать токен, эмитировать в wallet1, перевести в wallet2, проверить балансы"

# ❌ Плохо
name: "Тест 001"
description: "Тест токенов"
```

---

## 🎓 Поздравляем!

Теперь вы знаете:
- ✅ Базовую структуру сценария
- ✅ Использование defaults для уменьшения дублирования
- ✅ Извлечение данных с валидацией
- ✅ Workflow операций с токенами
- ✅ Надёжное ожидание через wait_for_datum
- ✅ Переиспользование компонентов через includes
- ✅ Организацию тестов в suites

### Что дальше?

1. **[Cookbook](Cookbook.md)** - Готовые рецепты для типовых задач
2. **[Glossary](Glossary.md)** - Полный справочник языка
3. **Реальные сценарии** - Изучите примеры в директории `scenarios/`

### Справочные материалы

- **Реальные E2E тесты:** `../../../e2e/` - production тестовые сценарии
- **Genesis сценарии:** `tests/stage-env/scenarios/genesis/` - продвинутые примеры динамических топологий
- **Общие includes:** `tests/stage-env/scenarios/common/` - переиспользуемые шаблоны
- **Примеры suites:** `tests/stage-env/scenarios/suites/` - паттерны организации suites

Удачи в тестировании! 🚀

---

**Обновлено:** 2026-01-29
**Язык:** Русский | [English](../../en/scenarios/Tutorial.md)
