# Regression Tests

Регрессионные тесты для stage-env - проверка что исправленные баги не возвращаются.

## 📋 Текущие тесты

### test_issue_no_unnecessary_rebuild.py

**Статус:** ✅  5/5 тестов ПРОХОДЯТ (баг исправлен!)

**Проблема (была):**
`./run.sh` всегда пересобирал cellframe-node даже когда:
- Пакет существует и не изменился
- Снапшот с генезисом уже есть
- Пересборка не нужна

**Исправление:**
В `run.sh` (lines 248-266) добавлена проверка существования пакета:
```bash
DEB_PACKAGE=$(find "$TEST_BUILD_DIR" -name "cellframe-node*.deb" ...)
if [ -n "$DEB_PACKAGE" ]; then
    SHOULD_BUILD=false  # Пакет есть - не строим
else
    SHOULD_BUILD=true   # Пакета нет - строим
fi
```

**Тесты:**
1. ✅ `test_should_not_rebuild_when_package_exists` - PASSES (логика проверки пакета)
2. ✅ `test_run_sh_package_check_logic` - PASSES (логика run.sh)
3. ✅ `test_run_sh_bug_always_rebuilds` - PASSES (верификация исправления)
4. ✅ `test_run_sh_respects_skip_build_flag` - PASSES (флаг --skip-build)
5. ✅ `test_run_sh_respects_url_source_type` - PASSES (type=url)

**Все тесты проходят** ✅ - баг исправлен!

---

### test_cli_error_handling.py

**Статус:** ✅  5/5 тестов ПРОХОДЯТ (улучшена обработка ошибок!)

**Проблема (была):**
CLI команды возвращают ошибки в YAML формате, но система пыталась извлечь хеш из текста ошибки:
```
errors:
    code: 32
    message: Arbitrage transaction failed: Network 'stagenet' has no fee address configured...
```
Результат: `Failed to extract hash from output` вместо реальной ошибки.

**Исправление:**
В `cli.py` (lines 127-162) добавлена проверка YAML ошибок **перед** извлечением хеша:
```python
# Check if output contains error in YAML format
output_data = yaml.safe_load(output)
if isinstance(output_data, dict) and 'errors' in output_data:
    error_code = error_info.get('code', -1)
    if error_code != 0:
        raise ScenarioExecutionError(
            f"CLI command returned error (code {error_code}): {error_message}"
        )
```

**Тесты:**
1. ✅ `test_detects_yaml_error_with_code_32` - PASSES (детектирует error code 32)
2. ✅ `test_ignores_success_output` - PASSES (не ломает успешные команды)
3. ✅ `test_detects_error_code_zero_as_success` - PASSES (code 0 = успех)
4. ✅ `test_hash_pattern_matches_various_formats` - PASSES (паттерн хешей)
5. ✅ `test_hash_pattern_ignores_old_hash` - PASSES (игнорирует "Old:" хеши)

**Все тесты проходят** ✅ - ошибки теперь понятные!

## 🔧 Как использовать

### 1. Убедиться что тест фейлится (баг существует)

```bash
cd tests/stage-env
python -m pytest tests/regression/test_issue_no_unnecessary_rebuild.py -v

# Ожидаемый результат: 2 failed, 2 passed
```

### 2. Закоммитить тест

```bash
git add tests/regression/test_issue_no_unnecessary_rebuild.py
git commit -m "test: add regression test for unnecessary rebuild issue"
```

### 3. Исправить баг в run.sh

Смотри подсказки в failing тестах - они показывают что нужно исправить.

### 4. Убедиться что тест теперь проходит

```bash
python -m pytest tests/regression/test_issue_no_unnecessary_rebuild.py -v

# Ожидаемый результат: 4 passed ✅
```

### 5. Закоммитить исправление

```bash
git add tests/stage-env/scripts/run.sh
git commit -m "fix: skip unnecessary rebuild when package unchanged

- Check if package exists before triggering build
- Restore from snapshot when package unchanged
- Fixes test_issue_no_unnecessary_rebuild.py"
```

## 📊 Статус тестов

| Тест | Статус | Описание |
|------|--------|----------|
| test_issue_no_unnecessary_rebuild.py | ✅ 5/5 PASSING | Ненужная пересборка при каждом запуске |
| test_cli_error_handling.py | ✅ 5/5 PASSING | Улучшена обработка YAML ошибок из CLI |

## 🎯 Добавление новых регрессионных тестов

1. Создай файл `test_issue_<название>.py`
2. Напиши тест который **ФЕЙЛИТСЯ** и демонстрирует баг
3. Убедись что тест фейлится: `pytest tests/regression/test_issue_<название>.py`
4. Закоммить тест
5. Исправить баг
6. Убедиться что тест теперь **ПРОХОДИТ**
7. Закоммитить исправление

## 📝 Шаблон регрессионного теста

```python
"""
Regression test: Issue - <Описание проблемы>

⚠️  THIS TEST CURRENTLY FAILS - IT VERIFIES THE FIX
"""

import pytest

class TestIssue<Name>:
    """
    These tests currently FAIL because the bug exists.
    After fix, tests should PASS.
    """
    
    def test_bug_<description>(self):
        """
        ⚠️  Currently FAILS - demonstrates the bug
        ✅  Should PASS after fix
        """
        # Simulate buggy behavior
        actual = buggy_function()
        expected = correct_behavior()
        
        assert actual == expected, "BUG: <описание>"
```

## 🔗 См. также

- [E2E Tests README](../e2e/README.md)
- [Functional Tests README](../functional/README.md)
- [Testing Architecture](../TESTING_ARCHITECTURE.md)
