# Корректировки СЛК задачи: Stage-Env Web UI

## ✅ Исправлено

### 1. Фокус задачи
- ❌ Было: Веб-интерфейс для SLC Agent  
- ✅ Стало: Веб-интерфейс для Stage-Env тестовой системы

### 2. Файлы и директории
- ✅ Переименован: `slc_web_interface.json` → `stage_env_web_ui.json`
- ✅ Перемещено: `slc-web-interface/` → `tests/stage-env/web-ui/`
- ✅ Обновлен: `.context/tasks/active.json` с правильной ссылкой

### 3. Backend структура

**Исправлено:**
```
app/core/
├── stage_env_executor.py  ✅ (было: slc_executor.py)
├── yaml_parser.py         ✅ (новое)
├── log_streamer.py        ✅ (новое)
└── ...

app/models/
├── scenario.py            ✅ (было: task.py)
├── test_execution.py      ✅ (новое)
├── test_result.py         ✅ (новое)
└── log_entry.py           ✅ (новое)

app/services/
├── scenario_service.py    ✅ (было: task_service.py)
├── test_service.py        ✅ (новое)
├── result_service.py      ✅ (новое)
└── log_service.py         ✅ (новое)
```

### 4. Frontend структура

**Исправлено:**
```
src/pages/
├── Dashboard.tsx          ✅ (обзор тестов)
├── Scenarios.tsx          ✅ (было: Tasks.tsx)
├── TestExecution.tsx      ✅ (было: Templates.tsx)
├── Results.tsx            ✅ (новое)
└── Logs.tsx              ✅ (новое)

src/services/
├── scenarioService.ts     ✅ (было: taskService.ts)
├── testService.ts         ✅ (новое)
├── resultService.ts       ✅ (новое)
└── logService.ts          ✅ (новое)
```

### 5. Features (ключевые изменения)

**Удалено (не относится к stage-env):**
- ❌ task_management
- ❌ template_browser  
- ❌ context_visualization
- ❌ analytics (SLC специфичные)

**Добавлено (для stage-env):**
- ✅ scenario_management - управление YAML сценариями
- ✅ test_execution - запуск и мониторинг тестов
- ✅ results_viewer - просмотр результатов
- ✅ log_viewer - просмотр логов
- ✅ scenario_graph - граф зависимостей сценариев

### 6. API Endpoints

**Исправлено:**
```yaml
# Удалено:
❌ /api/tasks/*
❌ /api/templates/*
❌ /api/context/*
❌ /api/analytics/*

# Добавлено:
✅ /api/scenarios/*        # Управление сценариями
✅ /api/tests/*            # Запуск тестов
✅ /api/results/*          # Результаты
✅ /api/logs/*             # Логи
✅ /ws/tests/{test_id}     # WebSocket для тестов
```

### 7. Integration

**Изменено:**
```python
# Было:
integration.slc_cli: "Прямые вызовы SLC команд"

# Стало:
integration.stage_env_cli: "Прямые вызовы stage-env CLI"
integration.scenario_parsing: "Парсинг YAML сценариев"
integration.log_streaming: "Real-time streaming логов"
```

## 📋 Что еще нужно обновить в задаче

### Оставшиеся упоминания SLC (TODO):

1. **Phases** - нужно обновить названия и описания:
   - Phase 1: "SLCExecutor" → "StageEnvExecutor"
   - Phase 2: "Tasks/Templates" → "Scenarios/Tests"
   - Phase 7: "Tasks UI" → "Scenarios UI"
   - Phase 8: "Templates" → "Test Execution"

2. **Example tests** секция:
   - "task_crud" → "scenario_crud"
   - "template_search" → "scenario_search"

3. **User flows**:
   - "create_task_flow" → "create_scenario_flow"
   - "browse_templates_flow" → "browse_scenarios_flow"

4. **Integration mapping**:
   - Обновить CLI команды на stage-env команды

5. **Success criteria**:
   - Заменить метрики SLC на метрики stage-env

## 🎯 Правильный фокус теперь

### Веб-интерфейс для Stage-Env предоставляет:

1. **Управление сценариями**
   - Просмотр YAML файлов из `tests/stage-env/scenarios/`
   - Создание/редактирование с Monaco Editor
   - Валидация YAML синтаксиса
   - Граф зависимостей между сценариями

2. **Запуск тестов**
   - Выбор сценария
   - Настройка параметров (env, vars)
   - Real-time мониторинг через WebSocket
   - Возможность остановки

3. **Результаты**
   - История всех запусков
   - Детальные результаты
   - Сравнение между запусками
   - Статистика и графики

4. **Логи**
   - Real-time streaming
   - Фильтрация по уровням
   - Поиск по логам
   - Скачивание

5. **Визуализация**
   - Граф зависимостей сценариев
   - Timeline выполнения
   - Тренды качества

## 🔧 Рекомендации по доработке

### 1. Создать отдельные документы:
```bash
tests/stage-env/web-ui/
├── ARCHITECTURE.md        # Архитектура веб-интерфейса
├── API_SPECIFICATION.md   # Детальная спецификация API
├── USER_GUIDE.md          # Руководство пользователя
└── DEVELOPER_GUIDE.md     # Руководство разработчика
```

### 2. Обновить существующий код:
```bash
# Переименовать файлы:
backend/app/core/slc_executor.py → stage_env_executor.py
backend/app/models/task.py → scenario.py

# Обновить импорты во всех файлах
# Обновить переменные и классы SLC* → StageEnv*
```

### 3. Актуализировать e2e тесты:
```bash
tests/e2e/pages/
├── dashboard_page.py      ✅ (актуален)
├── tasks_page.py          → scenarios_page.py (переименовать)
└── templates_page.py      → test_execution_page.py (переименовать)
```

### 4. Создать интеграцию с stage-env:
```python
# backend/app/core/stage_env_executor.py
class StageEnvExecutor:
    def __init__(self, stage_env_root: Path):
        self.root = stage_env_root
        self.run_script = stage_env_root / "run.sh"
        
    async def run_scenario(self, scenario_path: str):
        """Запуск сценария через ./run.sh"""
        
    async def list_scenarios(self):
        """Список сценариев из scenarios/"""
        
    async def parse_results(self, test_id: str):
        """Парсинг результатов из results/"""
```

## ✅ Итоговый checklist

- [x] Переименован файл задачи
- [x] Перемещена директория проекта
- [x] Обновлен active.json
- [x] Исправлен фокус задачи (description, goals)
- [x] Обновлена backend структура
- [x] Обновлена frontend структура
- [x] Исправлена features секция
- [x] Обновлены API endpoints
- [x] Создан STAGE_ENV_WEB_UI_OVERVIEW.md
- [ ] TODO: Обновить phases descriptions
- [ ] TODO: Обновить example tests
- [ ] TODO: Обновить user flows
- [ ] TODO: Переименовать существующий код
- [ ] TODO: Обновить e2e тесты названия

## 📝 Резюме

**Основная задача теперь корректно сфокусирована на stage-env!**

Все базовые секции обновлены, но для полной корректности нужно пройтись по всем phases и примерам, заменив упоминания SLC на stage-env. 

Созданная инфраструктура (Playwright, FastAPI, React) полностью переиспользуется - нужна только адаптация под stage-env специфику.
