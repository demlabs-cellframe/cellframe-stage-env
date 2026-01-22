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
| test_issue_no_unnecessary_rebuild.py | 🔴 FAILING | Ненужная пересборка при каждом запуске |

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
