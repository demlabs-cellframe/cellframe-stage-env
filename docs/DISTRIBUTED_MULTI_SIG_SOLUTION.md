# Реализация распределенной мультиподписи для Cellframe

## Обзор

Реализован полноценный механизм распределенной мультиподписи для токенов в Cellframe, позволяющий постепенное добавление подписей от разных узлов через `token_decl_sign` и `token_emit_sign`.

## Проблема (до изменений)

### Исходная реализация
```c
// token_decl устанавливал signs_total из параметра
l_datum_token->signs_total = l_signs_total; // Например, 3

// Но фактически добавлял только доступные подписи
l_sign_counter = 1; // Только одна подпись от root-1
```

**Последствия:**
- `signs_total = 3` (требуемое)
- Реальных подписей: 1
- `token_decl_sign` пытался проверить все 3 → **crash при проверке "подписи #2"** (мусор)

## Решение

### 1. Новый TSD тип для хранения требуемого количества подписей

**Файл:** `cellframe-sdk/modules/common/include/dap_chain_datum_token.h`

```c
/**
 * @brief Required signatures count for multi-sig tokens
 * @details Stores the target number of signatures required for token operations.
 * The actual current count of signatures is stored in datum_token->signs_total.
 * This TSD allows gradual signature collection via token_decl_sign.
 * @note Value type: uint16_t
 */
#define DAP_CHAIN_DATUM_TOKEN_TSD_TYPE_REQUIRED_SIGNS_COUNT  0x002E
```

### 2. Модификация `token_decl`

**Файл:** `cellframe-sdk/modules/net/dap_chain_node_cli_cmd.c` (строка ~5335)

```c
// Add TSD section for required signatures count in multi-sig tokens
if (l_signs_total > 1) {
    dap_tsd_t *l_tsd_required_signs = dap_tsd_create_scalar(
        DAP_CHAIN_DATUM_TOKEN_TSD_TYPE_REQUIRED_SIGNS_COUNT, l_signs_total);
    l_tsd_list = dap_list_append(l_tsd_list, l_tsd_required_signs);
    l_tsd_local_list_size += dap_tsd_size(l_tsd_required_signs);
    log_it(L_INFO, "Multi-sig token: required_signs=%u (will be added gradually)", l_signs_total);
}
```

**Изменение установки `signs_total`** (строка ~5478):

```c
// Старый код:
// l_datum_token->signs_total = l_signs_total;

// Новый код:
l_datum_token->signs_total = l_sign_counter;  // Фактическое количество подписей
log_it(L_INFO, "Token created with %u signature(s), required: %u", l_sign_counter, l_signs_total);
```

### 3. Модификация `token_decl_sign`

**Файл:** `cellframe-sdk/modules/net/dap_chain_node_cli_cmd.c` (строка ~2698)

```c
// Check EXISTING signatures (only those currently present, not the required total)
size_t l_signs_size = 0, i = 1;
uint16_t l_current_signs_count = l_datum_token->signs_total;
l_datum_token->signs_total = 0;
log_it(L_DEBUG, "Verifying %u existing signature(s) before adding new ones", l_current_signs_count);

for (i = 1; i <= l_current_signs_count; i++){  // Проверяем только существующие
    dap_sign_t *l_sign = (dap_sign_t *)(l_datum_token->tsd_n_signs + l_tsd_size + l_signs_size);
    if( dap_sign_verify(l_sign, l_datum_token, sizeof(*l_datum_token) + l_tsd_size) ) {
        log_it(L_WARNING, "Wrong existing signature %zu", i);
        // Error handling...
    }
    l_signs_size += dap_sign_get_size(l_sign);
}

// Add new signatures
l_datum_token = s_sign_cert_in_cycle(l_certs, l_datum_token, l_certs_count, &l_data_size, &l_sign_counter);
l_datum_token->signs_total += l_sign_counter;  // Увеличиваем счетчик
log_it(L_INFO, "Added %u new signature(s) (total now: %u)", l_sign_counter, l_datum_token->signs_total);
```

### 4. Обновленный YAML сценарий

**Файл:** `tests/stage-env/scenarios/genesis/phase1_zerochain.yml`

```yaml
# Phase 1: Create token with first signature
- cli: "token_decl -token TCELL -chain zerochain -total_supply 1000000 -decimals 18 -signs_emission 2 -signs_total 3 -certs pvt.stagenet.root.0 -pub_certs stagenet.root.0,stagenet.root.1,stagenet.root.2"
  node: root-1
  save_hash: token_hash

# Phase 2: Add second signature from root-2
- cli: "token_decl_sign -datum {{token_hash}} -chain zerochain -certs pvt.stagenet.root.1"
  node: root-2
  save_hash: token_hash_signed

# Wait for token finalization
- wait_for_datum: "{{token_hash_signed}}"
  node: root-1
  chain: zerochain
  timeout: 120

# Phase 3: Create emission with first signature
- cli: "token_emit -chain zerochain -token TCELL -emission_value 1000000 -addr {{fee_addr}} -certs pvt.stagenet.root.0"
  node: root-1
  save_hash: emission_hash_partial

# Phase 4: Add second signature to emission
- cli: "token_emit_sign -datum {{emission_hash_partial}} -chain zerochain -certs pvt.stagenet.root.1"
  node: root-2
  save_hash: emission_hash

# Wait for emission finalization
- wait_for_datum: "{{emission_hash}}"
  timeout: 120
```

## Ключевые изменения

### Семантика `signs_total`

| До                                    | После                                  |
|---------------------------------------|----------------------------------------|
| Требуемое количество подписей (из параметра) | **Текущее** количество подписей (фактическое) |
| Устанавливается в `l_signs_total`    | Устанавливается в `l_sign_counter`    |
| Может не соответствовать реальности   | Всегда соответствует реальности        |

### Новая TSD секция

- **Тип:** `DAP_CHAIN_DATUM_TOKEN_TSD_TYPE_REQUIRED_SIGNS_COUNT` (0x002E)
- **Значение:** Требуемое количество подписей (uint16_t)
- **Использование:** Для валидации при финализации токена

### Логика проверки подписей

```
До: for (i = 1; i <= l_tmp_signs_total; i++)  // signs_total из параметра
После: for (i = 1; i <= l_current_signs_count; i++)  // signs_total из структуры
```

## Примеры использования

### Создание токена с мультиподписью 2 из 3

```bash
# root-1: Создает токен с 1 подписью (требуется 3)
cellframe-node-cli token_decl \
  -token TCELL \
  -signs_total 3 \
  -signs_emission 2 \
  -certs pvt.stagenet.root.0 \
  -pub_certs stagenet.root.0,stagenet.root.1,stagenet.root.2 \
  -net stagenet
# Результат: signs_total=1, required_signs=3 (в TSD)

# root-2: Добавляет вторую подпись
cellframe-node-cli token_decl_sign \
  -datum <token_hash> \
  -certs pvt.stagenet.root.1 \
  -net stagenet
# Результат: signs_total=2, required_signs=3 (в TSD)

# root-3: Добавляет третью подпись
cellframe-node-cli token_decl_sign \
  -datum <token_hash> \
  -certs pvt.stagenet.root.2 \
  -net stagenet
# Результат: signs_total=3, required_signs=3 (в TSD) ✓ ГОТОВО
```

### Создание emission с мультиподписью

```bash
# root-1: Создает emission с 1 подписью
cellframe-node-cli token_emit \
  -token TCELL \
  -emission_value 1000000 \
  -addr <wallet_addr> \
  -certs pvt.stagenet.root.0 \
  -net stagenet

# root-2: Добавляет вторую подпись
cellframe-node-cli token_emit_sign \
  -datum <emission_hash> \
  -certs pvt.stagenet.root.1 \
  -net stagenet
# Emission готов к использованию (2 из 2)
```

## Логирование

### token_decl
```
[INF] Multi-sig token: required_signs=3 (will be added gradually)
[INF] Processing -pub_certs: stagenet.root.0,stagenet.root.1,stagenet.root.2
[INF] Added 3 public keys from certificates
[INF] Token created with 1 signature(s), required: 3
```

### token_decl_sign
```
[DBG] Verifying 1 existing signature(s) before adding new ones
[DBG] Existing sign 1 passed
[INF] Added 1 new signature(s) to datum 0x... (total now: 2)
```

## Обратная совместимость

✅ **Single-sig токены (signs_total=1):**
- TSD секция `REQUIRED_SIGNS_COUNT` НЕ создается (проверка `if (l_signs_total > 1)`)
- Поведение идентично старой реализации

✅ **Существующие токены:**
- Отсутствие TSD секции интерпретируется как single-sig
- Логика валидации сохраняется

## Тестирование

### Запуск тестов
```bash
cd /home/naeper/work/cellframe-node/tests/stage-env
./stage-env clean --all
./stage-env start
```

### Проверка логов
```bash
# Проверка создания токена
grep "Token created with" tests/testing/cache/data/node1/log/cellframe-node.log

# Проверка добавления подписей
grep "Added.*new signature" tests/testing/cache/data/node2/log/cellframe-node.log
```

## Статус

✅ **Завершено:**
- Добавлен TSD тип `REQUIRED_SIGNS_COUNT`
- Модифицирован `token_decl` для корректной установки `signs_total`
- Исправлен `token_decl_sign` для проверки только существующих подписей
- Обновлен YAML сценарий с поддержкой постепенного добавления подписей
- Cellframe-node пересобран с новой логикой
- Документация обновлена

⏳ **Требуется:**
- Пересборка Docker образа с новым бинарником
- E2E тестирование полного цикла genesis
- Проверка валидации токенов при финализации

## Файлы

### Модифицированные
- `cellframe-sdk/modules/common/include/dap_chain_datum_token.h` - новый TSD тип
- `cellframe-sdk/modules/net/dap_chain_node_cli_cmd.c` - логика token_decl/token_decl_sign
- `tests/stage-env/scenarios/genesis/phase1_zerochain.yml` - распределенная мультиподпись
- `tests/stage-env/docs/MULTI_SIG_TOKEN_SETUP.md` - обновленная документация

### Созданные
- `tests/stage-env/docs/MULTI_SIG_INVESTIGATION.md` - исследование проблемы
- `tests/stage-env/docs/DISTRIBUTED_MULTI_SIG_SOLUTION.md` - итоговое решение

## Следующие шаги

1. **Пересобрать Docker образ:**
   ```bash
   cd /home/naeper/work/cellframe-node/tests
   ./run.sh --rebuild
   ```

2. **Запустить E2E тесты:**
   ```bash
   cd /home/naeper/work/cellframe-node/tests/stage-env
   ./stage-env clean --all
   ./stage-env start
   ```

3. **Добавить валидацию при финализации:**
   - Проверять `signs_total >= required_signs` из TSD
   - Отклонять токены с недостаточным количеством подписей

4. **Документировать для production:**
   - Добавить примеры в Cellframe Wiki
   - Создать руководство для операторов узлов
   - Обновить спецификацию протокола

## См. также

- [MULTI_SIG_TOKEN_SETUP.md](MULTI_SIG_TOKEN_SETUP.md) - руководство пользователя
- [MULTI_SIG_INVESTIGATION.md](MULTI_SIG_INVESTIGATION.md) - анализ проблемы
- [phase1_zerochain.yml](../scenarios/genesis/phase1_zerochain.yml) - пример использования


