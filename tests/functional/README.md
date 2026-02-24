# Functional Tests

Функциональные тесты для скриптов управления stage-env.

## 📋 Содержание

- `test_run_sh.sh` - Тестирование скрипта запуска тестов (scripts/run.sh)
- `test_clean_sh.sh` - Тестирование скрипта очистки (clean.sh)

## 🚀 Запуск

```bash
# Все функциональные тесты
cd tests/stage-env
bash tests/run_tests.sh functional tests/functional/

# Конкретный тест
./tests/functional/test_run_sh.sh
./tests/functional/test_clean_sh.sh
```

## 📚 Подробная документация

См. [E2E README](../e2e/README.md) для полной документации по всем тестам.
