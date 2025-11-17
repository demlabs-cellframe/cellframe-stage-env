# Исследование мультиподписи в Cellframe

## Проблема

При попытке реализовать распределенную мультиподпись для токенов (2 из 3 consensus) была обнаружена фундаментальная проблема в текущей реализации `token_decl` и `token_decl_sign`.

## Проделанная работа

1. ✅ **Добавлен параметр `-pub_certs`** в `token_decl` (строка ~5000 в `dap_chain_node_cli_cmd.c`)
   - Парсит список публичных сертификатов
   - Извлекает публичные ключи через `dap_cert_to_pkey`
   - Добавляет их в TSD секцию токена как `DAP_CHAIN_DATUM_TOKEN_TSD_TYPE_TOTAL_PKEYS_ADD`
   - Логирует: "Processing -pub_certs" и "Added N public keys from certificates"

2. ✅ **Проверена корректность работы**
   - Публичные ключи успешно добавляются в TSD
   - Размер TSD правильно обновляется (`tsd_total_size`)
   - Токен успешно создается и помещается в mempool

3. ✅ **Обновлена документация**
   - `tests/stage-env/docs/MULTI_SIG_TOKEN_SETUP.md` с примерами
   - Описаны все параметры и способы отладки

## Обнаруженная проблема

### Текущая реализация `token_decl`

```c
// Строка 5469 в dap_chain_node_cli_cmd.c
l_datum_token->signs_total = l_signs_total; // Значение из параметра -signs_total
```

**Проблема:** Поле `signs_total` устанавливается в значение параметра (например, 3), но фактически добавляются только те подписи, которые указаны в `-certs` (например, 1).

### Последствия

Когда `token_decl_sign` пытается добавить вторую подпись:

1. Извлекает токен из mempool
2. Видит `signs_total = 3`
3. Пытается **проверить** все 3 существующих подписи перед добавлением новой
4. **Находит только 1 реальную подпись**
5. Указатель на "вторую подпись" попадает в мусор/TSD данные
6. **Ошибка:** "Datum ... with datum token has wrong signature 2, break process and exit"

### Код проверки подписей

```c
// Строки 2700-2705 в dap_chain_node_cli_cmd.c (token_decl_sign)
for (i = 1; i <= l_tmp_signs_total; i++){
    dap_sign_t *l_sign = (dap_sign_t *)(l_datum_token->tsd_n_signs + l_tsd_size + l_signs_size);
    if( dap_sign_verify(l_sign, l_datum_token, sizeof(*l_datum_token) + l_tsd_size) ) {
        log_it(L_WARNING, "Wrong signature %zu for datum_token with key %s in mempool!", i, l_datum_hash_out_str);
        // ERROR
    }
}
```

## Архитектурная проблема

### Требование текущей реализации

Для создания токена с `-signs_total 3` нужно передать **ВСЕ 3 приватных сертификата** сразу:

```bash
token_decl ... -certs pvt.root.0,pvt.root.1,pvt.root.2
```

### Реальность распределенной системы

В stage-env (и в реальном Cellframe):
- Каждый узел имеет только **свой** приватный сертификат в `/opt/cellframe-node/var/lib/ca/`
- Публичные сертификаты других узлов в `/opt/cellframe-node/share/ca/`
- **Физически невозможно** собрать все приватные сертификаты на одном узле

### Вывод

**Текущая реализация `token_decl` + `token_decl_sign` НЕ поддерживает распределенную мультиподпись!**

## Возможные решения

### Решение 1: Модификация логики `token_decl` (РЕКОМЕНДУЕТСЯ)

**Изменения:**

1. При создании токена с `-signs_total 3 -certs pvt.root.0`:
   - Установить `signs_total = 1` (фактическое количество подписей)
   - Сохранить "требуемое количество подписей" в TSD секцию (например, `DAP_CHAIN_DATUM_TOKEN_TSD_TYPE_REQUIRED_SIGNS`)

2. Модифицировать `token_decl_sign`:
   - При добавлении подписи: `signs_total++`
   - НЕ проверять еще не добавленные подписи
   - Проверять только `signs_total` существующих подписей

3. Добавить проверку при финализации токена:
   - Сравнить `signs_total` с "требуемым количеством" из TSD
   - Токен валиден только если `signs_total >= required_signs`

**Плюсы:**
- Поддержка распределенной мультиподписи
- Обратная совместимость (старые токены продолжат работать)

**Минусы:**
- Требует изменений в core logic cellframe-node
- Нужно тестирование всех сценариев

### Решение 2: Копирование приватных сертификатов (ВРЕМЕННОЕ)

**Для stage-env:**

1. Модифицировать `ConfigGenerator` для копирования всех root приватных сертификатов на root-1:
   ```python
   # В generator.py
   for root_id in range(1, root_count + 1):
       src = f"cache/certs/pvt.{network}.root.{root_id}.dcert"
       dst = f"cache/configs/node1/var/lib/ca/"
       shutil.copy(src, dst)
   ```

2. Использовать все сертификаты в `token_decl`:
   ```yaml
   - cli: "token_decl ... -certs pvt.stagenet.root.0,pvt.stagenet.root.1,pvt.stagenet.root.2"
   ```

**Плюсы:**
- Работает с текущей реализацией cellframe-node
- Простая модификация только stage-env

**Минусы:**
- **НЕ подходит для production!**
- Нарушает принцип распределенной системы
- Не решает реальную проблему мультиподписи

### Решение 3: Отказ от постепенной мультиподписи

Использовать только single-sig токены в stage-env тестах.

**Плюсы:**
- Не требует изменений

**Минусы:**
- Не тестирует мультиподпись
- Не решает проблему для production

## Рекомендации

1. **Немедленно (для stage-env):** Использовать Решение 2 для продолжения разработки других функций
   
2. **Среднесрочно:** Реализовать Решение 1 в cellframe-node core
   
3. **Долгосрочно:** Добавить полноценную поддержку распределенной мультиподписи с:
   - Координацией между узлами
   - Таймаутами на сбор подписей
   - Rollback при недостатке подписей

## Статус

- ✅ Параметр `-pub_certs` реализован и работает
- ✅ Публичные ключи корректно добавляются в TSD
- ❌ Распределенная мультиподпись НЕ работает из-за архитектурных ограничений
- ⏸️ Требуется решение от команды Cellframe по стратегии мультиподписи

## Файлы

- Модифицированный код: `cellframe-sdk/modules/net/dap_chain_node_cli_cmd.c` (строка 4998)
- Документация: `tests/stage-env/docs/MULTI_SIG_TOKEN_SETUP.md`
- YAML сценарий: `tests/stage-env/scenarios/genesis/phase1_zerochain.yml`
- Логи исследования: Последний запуск в `tests/testing/logs/stage-env_20251117_170807.log`

## См. также

- Issue tracker: [создать issue в cellframe-node репозитории]
- Cellframe Wiki: https://wiki.cellframe.net/


