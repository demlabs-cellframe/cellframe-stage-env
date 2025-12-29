# Print и Sprint Steps

## Введение

Новые типы шагов `print` и `sprint` добавлены для упрощения отладки и работы со строками в сценариях stage-env.

## PrintStep - Вывод отладочной информации

**Назначение**: Вывод сообщений в лог и консоль для отладки сценариев.

**Синтаксис**:
```yaml
- print: "сообщение с подстановкой {{переменных}}"
  level: info  # опционально: info, debug, warning, error
```

**Параметры**:
- `print` (обязательный): Строка для вывода, поддерживает подстановку переменных
- `level` (опциональный, по умолчанию `info`): Уровень логирования
  - `info` - информационное сообщение (ℹ️)
  - `debug` - отладочное сообщение (🔍)
  - `warning` - предупреждение (⚠️)
  - `error` - ошибка (❌)

**Примеры**:

```yaml
# Простой вывод
- print: "Starting token creation process"

# С подстановкой переменных
- print: "Token created with hash: {{token_hash}}"

# С уровнем предупреждения
- print: "emission_hash not found, using fallback"
  level: warning

# Отладочный вывод
- print: "DEBUG: Full event dump: {{emission_event_dump}}"
  level: debug
```

**Когда использовать**:
- Отладка сценариев
- Вывод промежуточных результатов
- Логирование важных событий
- Замена `bash: echo` для чистого вывода

## SprintStep - Форматирование и сохранение строк

**Назначение**: Форматирование строк с подстановкой переменных и сохранение результата в переменную (String Print).

**Синтаксис**:
```yaml
- sprint: "форматированная строка с {{переменными}}"
  save: variable_name  # обязательно
  print_also: false    # опционально
  level: info          # опционально
```

**Параметры**:
- `sprint` (обязательный): Строка для форматирования с подстановкой переменных
- `save` (обязательный): Имя переменной для сохранения результата
- `print_also` (опциональный, по умолчанию `false`): Также вывести в консоль
- `level` (опциональный, по умолчанию `info`): Уровень логирования если `print_also=true`

**Примеры**:

```yaml
# Создание составного сообщения
- sprint: "Processed {{items_count}} items in {{duration}}s"
  save: status_message

# С выводом в консоль
- sprint: "Node {{node_id}} address: {{node_address}}"
  save: node_info
  print_also: true
  level: info

# Формирование сложных строк
- sprint: "Certificate path: /opt/cellframe-node/var/lib/ca/pvt.{{network_name}}.root.{{cert_idx}}.dcert"
  save: cert_full_path

# Использование сохраненной переменной
- sprint: "Status: {{status_message}}"
  save: full_report
```

**Когда использовать**:
- Форматирование сложных строк из нескольких переменных
- Создание составных сообщений для последующего использования
- Подготовка данных для CLI команд
- Замена bash-скриптов для простого форматирования строк

## Best Practices

1. **Используйте `print` для отладки**
2. **Используйте `sprint` для формирования данных**
3. **Выбирайте правильный уровень логирования**
4. **Не злоупотребляйте выводом**

## ExitStep - Явное завершение сценария

**Назначение**: Явное завершение выполнения сценария с указанным кодом выхода.

**Синтаксис**:
```yaml
- exit: код_выхода  # 0 = успех, ≠0 = ошибка
  message: "опциональное сообщение"
```

**Параметры**:
- `exit` (обязательный): Код выхода (0 для успеха, не-ноль для ошибки)
- `message` (опциональный): Сообщение для отображения при выходе

**Примеры**:

```yaml
# Успешное завершение
- exit: 0
  message: "All checks passed successfully"

# Завершение с ошибкой
- exit: 1
  message: "Critical validation failed"

# Условное завершение
- if: "not emission_hash"
  then:
    - print: "ERROR: emission_hash not found in event dump"
      level: error
    - exit: 1
      message: "Missing emission_hash - cannot continue"

# Завершение без сообщения
- exit: 2
```

**Когда использовать**:
- Критические ошибки, требующие немедленной остановки
- Проверка предусловий, которые не выполнены
- Явное указание точки успешного завершения
- Замена bash `exit` команд

**Важно**:
- ❌ **БЕЗ FALLBACK'ОВ**: Если данные не найдены - exit с ошибкой
- ✅ **FAIL FAST**: Останавливаться немедленно при критической проблеме
- ✅ **ЯСНЫЕ КОДЫ**: 0 = успех, 1 = общая ошибка, 2+ = специфические ошибки
- ✅ **ИНФОРМАТИВНОСТЬ**: Всегда указывайте `message` для понимания причины

## Сравнение с другими подходами

### До (bash для exit):
```yaml
- if: "not emission_hash"
  then:
    - bash: "echo 'ERROR: emission_hash not found' && exit 1"
      node: "{{first_root}}"
```

### После (exit step):
```yaml
- if: "not emission_hash"
  then:
    - print: "ERROR: emission_hash not found"
      level: error
    - exit: 1
      message: "Missing emission_hash"
```

**Преимущества**:
- ✅ Не требует `node`
- ✅ Отдельный вывод и выход
- ✅ Структурированный exit code
- ✅ Понятная семантика

## Best Practices для Exit

1. **Используйте exit вместо fallback**:
   ```yaml
   # ❌ Плохо - fallback маскирует проблему
   - set: value
     value: "{{optional_value or 'default'}}"
   
   # ✅ Хорошо - fail fast
   - if: "not optional_value"
     then:
       - print: "ERROR: Required value not found"
         level: error
       - exit: 1
   ```

2. **Всегда указывайте message**:
   ```yaml
   # ❌ Плохо
   - exit: 1
   
   # ✅ Хорошо
   - exit: 1
     message: "Validation failed: missing required field 'token_hash'"
   ```

3. **Используйте разные коды для разных ошибок**:
   ```yaml
   - if: "not token_hash"
     then:
       - exit: 1
         message: "Token creation failed"
   
   - if: "not emission_hash"
     then:
       - exit: 2
         message: "Emission not found"
   
   - if: "not genesis_block"
     then:
       - exit: 3
         message: "Genesis block missing"
   ```

4. **Комбинируйте с print для отладки**:
   ```yaml
   - if: "error_condition"
     then:
       - print: "DEBUG: Current state - {{state_var}}"
         level: debug
       - print: "ERROR: Fatal error occurred"
         level: error
       - exit: 1
         message: "Cannot continue due to fatal error"
   ```

## Технические детали ExitStep

- **Реализация**: Python async executor с `ScenarioExecutionError`
- **Файлы**:
  - `src/scenarios/step/exit_step.py` - ExitStepExecutor
  - `src/scenarios/schema.py` - ExitStep модель
  - `src/scenarios/executor.py` - интеграция в ScenarioExecutor

- **Поведение**: Всегда вызывает `ScenarioExecutionError` для остановки выполнения
- **Логирование**: 
  - `exit: 0` → info level с ✅
  - `exit: ≠0` → error level с ❌
