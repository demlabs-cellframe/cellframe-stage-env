# Stage-Env E2E и Functional Tests

## 📋 Описание

Комплексные E2E (end-to-end) и функциональные тесты для системы `stage-env` и её скриптов управления.

## 🗂️ Структура

```
tests/stage-env/tests/
├── e2e/                              # E2E тесты (сквозное тестирование)
│   ├── test_config_edge_cases.sh    # Краевые случаи конфигураций
│   └── test_stage_env_lifecycle.sh  # Полный жизненный цикл stage-env
│
├── functional/                       # Функциональные тесты
│   ├── test_run_sh.sh               # Тестирование run.sh скрипта
│   └── test_clean_sh.sh             # Тестирование clean.sh скрипта
│
└── README.md                         # Эта документация
```

## 🎯 E2E Тесты

### test_config_edge_cases.sh

Проверяет обработку краевых случаев в конфигурационных файлах:

**Тестируемые случаи:**
- ✅ Отсутствующий конфигурационный файл
- ✅ Пустой конфигурационный файл
- ✅ Невалидные номера портов (границы диапазона)
- ✅ Некорректный формат network_id
- ✅ Нулевое количество валидаторов
- ✅ Невалидные IP-адреса
- ✅ Конфликтующие настройки нод
- ✅ Отсутствующие обязательные секции
- ✅ Невалидный collecting_level (вне диапазона 0-100)
- ✅ Некорректный синтаксис INI
- ✅ URL-тип без указания URL
- ✅ Экстремально большие таймауты
- ✅ Минимальная валидная конфигурация
- ✅ Специальные символы в имени сети
- ✅ Отрицательные значения таймаутов

**Запуск:**
```bash
cd tests/stage-env
./tests/e2e/test_config_edge_cases.sh
```

**Ожидаемый результат:** Все невалидные конфигурации должны быть корректно отклонены с понятными сообщениями об ошибках.

---

### test_stage_env_lifecycle.sh

Проверяет полный жизненный цикл работы с stage-env:

**Тестируемые операции:**
1. Валидация конфигурации
2. Проверка статуса (остановлена)
3. Запуск сети
4. Проверка статуса (запущена)
5. Проверка Docker контейнеров
6. Генерация конфигурационных файлов
7. Генерация docker-compose файла
8. Создание директорий логов
9. Остановка сети
10. Проверка остановки контейнеров
11. Идемпотентность (двойная остановка)
12. Очистка
13. Проверка очистки данных
14. Удаление docker-compose файла
15. Полный цикл (интеграционный тест)

**Запуск:**
```bash
cd tests/stage-env
./tests/e2e/test_stage_env_lifecycle.sh
```

**Требования:**
- Docker должен быть запущен
- Конфигурация `config/stage-env.cfg` должна существовать
- Достаточно места на диске для создания тестовой сети

---

## 🔧 Функциональные тесты

### test_run_sh.sh

Тестирует скрипт запуска тестов `scripts/run.sh`:

**Проверяемая функциональность:**
- ✅ Вывод справки (`--help`)
- ✅ Наличие всех опций в справке
- ✅ Обработка некорректных опций
- ✅ Флаг `--stop`
- ✅ Флаг `--skip-build`
- ✅ Обнаружение конфигурации stage-env
- ✅ Обнаружение wrapper скрипта
- ✅ Структура директорий тестов
- ✅ Комбинированные флаги
- ✅ Флаг `--e2e`
- ✅ Флаг `--functional`
- ✅ Флаг `--clean`
- ✅ Работа из разных директорий
- ✅ Проверка предусловий
- ✅ Определение типа источника нод
- ✅ Флаг `--regression`
- ✅ Флаг `--keep-running`
- ✅ Исполняемость скрипта
- ✅ Наличие bash shebang
- ✅ Обработка ошибок

**Запуск:**
```bash
cd tests/stage-env
./tests/functional/test_run_sh.sh
```

---

### test_clean_sh.sh

Тестирует скрипт очистки `clean.sh`:

**Проверяемая функциональность:**
- ✅ Исполняемость скрипта
- ✅ Базовая очистка (без флагов)
- ✅ Очистка директории данных
- ✅ Очистка директории конфигов
- ✅ Сохранение снапшотов (базовая очистка)
- ✅ Полная очистка (`--all`)
- ✅ Удаление снапшотов (полная очистка)
- ✅ Удаление артефактов (полная очистка)
- ✅ Удаление docker-compose файла
- ✅ Удаление CLI кеша
- ✅ Остановка контейнеров перед очисткой
- ✅ Идемпотентность (двойной запуск)
- ✅ Пересоздание директорий
- ✅ Работа из разных директорий
- ✅ Наличие bash shebang
- ✅ Информация об использовании
- ✅ Обработка ошибок Docker
- ✅ Вывод сообщений очистки
- ✅ Код возврата при успехе
- ✅ Обработка прав доступа

**Запуск:**
```bash
cd tests/stage-env
./tests/functional/test_clean_sh.sh
```

---

## 🚀 Запуск всех тестов

### Запуск через run_tests.sh

```bash
cd tests/stage-env
bash tests/run_tests.sh e2e tests/e2e/
bash tests/run_tests.sh functional tests/functional/
```

### Запуск напрямую

```bash
cd tests/stage-env

# E2E тесты
./tests/e2e/test_config_edge_cases.sh
./tests/e2e/test_stage_env_lifecycle.sh

# Функциональные тесты
./tests/functional/test_run_sh.sh
./tests/functional/test_clean_sh.sh
```

### Запуск всех bash тестов

```bash
cd tests/stage-env

# Запуск всех E2E тестов
for test in tests/e2e/test_*.sh; do
    echo "Running $test..."
    bash "$test"
done

# Запуск всех функциональных тестов
for test in tests/functional/test_*.sh; do
    echo "Running $test..."
    bash "$test"
done
```

---

## 📊 Интерпретация результатов

### Формат вывода

Каждый тест выводит результаты в следующем формате:

```
[INFO] Test X: Description
[PASS] Test result
[FAIL] Error description
[WARN] Warning message
[SKIP] Reason for skipping

========================================
Test Summary
========================================
Passed:  15
Failed:  0
Skipped: 0
========================================
Total:   15
========================================
```

### Коды возврата

- `0` - все тесты прошли успешно
- `1` - один или более тестов провалились
- `> 1` - критическая ошибка выполнения

---

## 🔍 Helper функции

Все тесты используют общие helper функции из `/tests/helpers.sh`:

### Логирование
- `log_info` - информационное сообщение
- `log_success` - успешный тест
- `log_error` - ошибка теста
- `log_warning` - предупреждение
- `log_skip` - пропущенный тест

### Assertions
- `assert_success` - проверка успешного выполнения
- `assert_failure` - проверка провала команды
- `assert_equals` - сравнение значений
- `assert_contains` - проверка содержания строки
- `assert_file_exists` - проверка существования файла
- `assert_dir_exists` - проверка существования директории

### Утилиты
- `wait_for_condition` - ожидание условия
- `wait_for_file` - ожидание создания файла
- `wait_for_port` - ожидание доступности порта
- `require_command` - проверка наличия команды
- `require_docker` - проверка Docker
- `require_file` - проверка наличия файла

---

## 🐛 Отладка

### Включение подробного вывода

Добавьте в начало скрипта:
```bash
set -x  # Печать выполняемых команд
```

### Запуск отдельной тестовой функции

```bash
cd tests/stage-env

# Отредактируйте тест, закомментировав все кроме нужной функции
# Или извлеките функцию в отдельный скрипт
source tests/helpers.sh
source tests/e2e/test_config_edge_cases.sh

# Вызовите конкретную функцию
test_missing_config
```

### Проверка состояния после теста

```bash
# Проверка Docker контейнеров
docker ps -a --filter "name=cf-"

# Проверка файловой системы
ls -la ../testing/cache/
ls -la ../testing/logs/

# Проверка docker-compose
ls -la docker-compose.generated.yml
```

---

## 🛠️ Разработка новых тестов

### Шаблон теста

```bash
#!/bin/bash
set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_ENV_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TESTS_ROOT="$(dirname "$(dirname "$STAGE_ENV_DIR")")"

# Source helpers
source "$TESTS_ROOT/helpers.sh"

# Test setup
setup_test "My New Test Suite"

# Cleanup function
cleanup() {
    # Ваша логика очистки
    log_info "Cleanup..."
}
trap cleanup EXIT

# ============================================================================
# Test 1: Description
# ============================================================================
test_something() {
    log_info "Test 1: Testing something"
    
    if [ condition ]; then
        log_success "Test passed"
        ((TESTS_PASSED++))
    else
        log_error "Test failed"
        ((TESTS_FAILED++))
    fi
}

# Run tests
test_something

# Summary
teardown_test "My New Test Suite"
print_test_summary
exit $?
```

### Лучшие практики

1. **Изоляция тестов** - каждый тест должен быть независим
2. **Очистка ресурсов** - используйте `trap cleanup EXIT`
3. **Информативные сообщения** - ясно описывайте что тестируется
4. **Обработка ошибок** - используйте `set -euo pipefail`
5. **Таймауты** - используйте `timeout` для долгих операций
6. **Идемпотентность** - тесты должны давать одинаковый результат при повторных запусках

---

## 📝 Отчеты об ошибках

При обнаружении проблем укажите:

1. Имя теста
2. Команду запуска
3. Полный вывод теста
4. Версию Docker
5. ОС и версию
6. Содержимое `config/stage-env.cfg`

---

## 🔗 Связанная документация

- [Stage-Env Documentation](../../docs/en/README.md)
- [Testing Architecture](../TESTING_ARCHITECTURE.md)
- [Run.sh Guide](../../docs/en/RunShGuide.md)
- [Scenario Testing](../../docs/en/scenarios/README.md)

---

## ✅ CI/CD Integration

Эти тесты можно интегрировать в CI/CD pipeline:

```yaml
# Пример для GitLab CI
test:bash:e2e:
  stage: test
  script:
    - cd tests/stage-env
    - ./tests/e2e/test_config_edge_cases.sh
    - ./tests/e2e/test_stage_env_lifecycle.sh
  artifacts:
    when: always
    paths:
      - tests/testing/logs/
      - tests/testing/artifacts/

test:bash:functional:
  stage: test
  script:
    - cd tests/stage-env
    - ./tests/functional/test_run_sh.sh
    - ./tests/functional/test_clean_sh.sh
```

---

## 📞 Поддержка

Для вопросов и предложений:
- Создайте issue в репозитории
- Обратитесь к команде разработки
- Проверьте существующую документацию

---

**Последнее обновление:** 2026-01-22
