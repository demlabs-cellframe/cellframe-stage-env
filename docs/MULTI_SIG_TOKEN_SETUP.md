# Настройка мультиподписи для токенов

## Проблема

При создании токена с несколькими подписантами (`-signs_total > 1`), стандартная команда `token_decl` не предоставляла способа указать публичные ключи всех подписантов в TSD секции. Текущая реализация `token_decl` требует, чтобы все подписи были добавлены сразу при создании токена, что означает, что все приватные сертификаты должны быть доступны на одном узле.

## Решение

Добавлен новый параметр `-pub_certs` в команду `token_decl` для явного указания публичных сертификатов всех подписантов:
- Файл: `cellframe-sdk/modules/net/dap_chain_node_cli_cmd.c` (строка ~5000)
- Параметр: `-pub_certs <cert1,cert2,...>` - список публичных сертификатов

**Важно:** Текущая реализация требует передачи всех приватных сертификатов в параметре `-certs` при создании токена.

## Установка

### Пересобрать cellframe-node

```bash
cd /home/naeper/work/cellframe-node/build
cmake ..
make -j$(nproc)
```

## Использование

### Пример: Мультиподпись 2 из 3

**ВАЖНО:** Все приватные сертификаты должны быть доступны на узле, выполняющем `token_decl`.

```bash
# root-1 создает токен со всеми 3 подписями сразу
cellframe-node-cli token_decl \
  -token TCELL \
  -chain zerochain \
  -total_supply 1000000 \
  -decimals 18 \
  -signs_emission 2 \
  -signs_total 3 \
  -certs pvt.stagenet.root.0,pvt.stagenet.root.1,pvt.stagenet.root.2 \
  -pub_certs stagenet.root.0,stagenet.root.1,stagenet.root.2 \
  -net stagenet
```

**Примечание:** Параметр `-pub_certs` является расширением stage-env и добавляет публичные ключи в TSD секцию токена.

### В YAML сценариях

```yaml
# Create TCELL token declaration (2 of 3 consensus) with all signatures at once
- cli: "token_decl -token TCELL -chain zerochain -total_supply 1000000 -decimals 18 -signs_emission 2 -signs_total 3 -certs pvt.stagenet.root.0,pvt.stagenet.root.1,pvt.stagenet.root.2 -pub_certs stagenet.root.0,stagenet.root.1,stagenet.root.2"
  node: root-1
  save_hash: token_hash
```

## Параметры token_decl

### Обязательные
- `-token <TICKER>` - тикер токена  
- `-chain <CHAIN>` - имя цепи
- `-total_supply <AMOUNT>` - общий объем эмиссии
- `-decimals <N>` - количество десятичных знаков (18)
- `-signs_emission <N>` - минимальное количество подписей для эмиссии
- `-signs_total <N>` - общее количество подписантов
- `-certs <CERT>` - приватный сертификат для подписи
- `-pub_certs <CERT1,CERT2,...>` - публичные сертификаты всех подписантов

## Отладка

### "wrong signature 2" при token_decl_sign

**Причина:** Текущая реализация `token_decl` устанавливает `signs_total` в значение параметра, но добавляет только те подписи, которые указаны в `-certs`. Если указан `-signs_total 3`, но передан только один сертификат в `-certs`, то `signs_total = 3`, но реальных подписей только 1. При попытке проверить токен, код пытается проверить все 3 подписи и падает.

**Решение:**
1. Передавайте ВСЕ приватные сертификаты в `-certs` при создании токена:
   ```bash
   token_decl ... -certs pvt.root.0,pvt.root.1,pvt.root.2
   ```
2. НЕ используйте `token_decl_sign` для постепенного добавления подписей с текущей реализацией.

### Сертификат не найден

**Причина:** Приватный или публичный сертификат не существует на узле.

**Решение:**
1. Проверьте приватные: `ls /opt/cellframe-node/var/lib/ca/`
2. Проверьте публичные: `ls /opt/cellframe-node/share/ca/`
3. Используйте имена без расширения `.dcert`
4. Для stage-env: `pvt.stagenet.root.0`, `stagenet.root.0`, и т.д.

### Публичные ключи не добавлены в TSD

**Проверка:**
```bash
grep "Added.*public keys from certificates" /opt/cellframe-node/var/log/cellframe-node.log
```

Если не найдено, убедитесь, что:
1. Параметр `-pub_certs` указан корректно
2. Публичные сертификаты существуют в `/opt/cellframe-node/share/ca/`
3. Используете модифицированную версию cellframe-node

## См. также

- [scenarios/genesis/phase1_zerochain.yml](../scenarios/genesis/phase1_zerochain.yml) - Пример использования
- Cellframe Wiki: https://wiki.cellframe.net/
