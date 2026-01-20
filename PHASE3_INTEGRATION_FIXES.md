# Phase 3: Исправление интеграционных тестов

## 📊 Текущий статус
- **Всего:** 56 тестов
- **Passed:** 35 ✅ (62.5%)
- **Failed:** 19 ❌ (33.9%)
- **Errors:** 2 ❌ (3.6%)

## 🎯 Задачи исправления

### Группа 1: ConfigLoader API mismatches (6 тестов)
**Проблема:** Тесты создают YAML файлы, ConfigLoader ожидает INI

#### test_build_integration.py (3 failed)
- `test_build_manager_uses_config_paths`
- `test_build_artifacts_placed_in_config_location`
- `test_build_config_validation_integration`

**Решение:** Создавать конфиг в INI формате вместо YAML

#### test_filesystem_integration.py (1 failed)
- `test_all_modules_respect_config_paths`

**Решение:** Создавать конфиг в INI формате

### Группа 2: NetworkManager/ConfigLoader initialization (4 теста)
**Проблема:** NetworkManager требует инициализированный ConfigLoader

#### test_docker_network_integration.py (3 failed)
- `test_compose_generates_for_network_manager`
- `test_network_manager_uses_container_manager`

**Решение:** Инициализировать ConfigLoader перед созданием NetworkManager

### Группа 3: BaseScenarioParser API changes (6 тестов)
**Проблема:** `BaseScenarioParser.__init__()` требует дополнительный аргумент

#### test_scenario_pipeline.py (5 failed)
- `test_parser_to_executor_flow`
- `test_full_scenario_execution_pipeline`
- `test_scenario_with_variables_integration`
- `test_scenario_step_execution_integration`
- `test_invalid_scenario_rejected_by_parser`

#### test_error_handling_integration.py (1 failed)
- `test_scenario_validation_catches_errors`

**Решение:** Проверить сигнатуру BaseScenarioParser и передать нужные аргументы

### Группа 4: Monitor API changes (4 теста)
**Проблема:** DatumMonitor и ValidatorMonitor требуют дополнительные аргументы

#### test_monitoring_integration.py (4 failed)
- `test_datum_monitor_with_container_integration`
- `test_monitor_collects_data_from_containers`
- `test_validator_monitor_integration`
- `test_monitoring_logs_to_filesystem`

**Решение:** Проверить сигнатуры классов и передать нужные аргументы

### Группа 5: Container naming mismatches (2 теста)
**Проблема:** Ожидается `cellframe-node-node1`, получается `cellframe-stage-node-1`

#### test_docker_network_integration.py (2 failed)
- `test_container_manager_with_network_lifecycle`
- `test_container_exec_with_network_context`

**Решение:** Обновить ожидаемые имена контейнеров

### Группа 6: ScenarioExecutor API (1 тест)
**Проблема:** AttributeError в scenario executor

#### test_scenario_pipeline.py (1 failed)
- `test_step_failure_propagates_to_executor`

**Решение:** Проверить API ScenarioExecutor

### Группа 7: Missing fixtures (2 errors)
**Проблема:** fixture 'temp_base_path' not found

#### test_docker_network_integration.py (2 errors)
- `test_network_creation_failure_propagates`
- `test_container_not_found_in_network`

**Решение:** Добавить fixture `temp_base_path` в conftest.py

## 📝 План действий

1. ✅ Проанализировать API изменения
2. ⏳ Добавить missing fixture
3. ⏳ Исправить ConfigLoader тесты (INI format)
4. ⏳ Исправить NetworkManager initialization
5. ⏳ Исправить BaseScenarioParser calls
6. ⏳ Исправить Monitor API calls
7. ⏳ Исправить container naming
8. ⏳ Исправить ScenarioExecutor call
9. ⏳ Запустить все тесты и проверить

**Цель:** 56/56 passed (100%)
