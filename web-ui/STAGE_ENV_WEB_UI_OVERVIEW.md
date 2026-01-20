# Stage-Env Web UI - Веб-интерфейс для тестовой системы

## 🎯 Назначение

Веб-интерфейс для **stage-env** - тестовой системы Cellframe Node.

### Что это НЕ:
- ❌ НЕ веб-интерфейс для SLC Agent
- ❌ НЕ система управления контекстом

### Что это ЕСТЬ:
- ✅ Веб-интерфейс для управления stage-env тестами
- ✅ Визуализация выполнения тестов в real-time
- ✅ Редактор YAML сценариев
- ✅ Просмотр логов и результатов
- ✅ Граф зависимостей тестовых сценариев

## 🏗️ Архитектура

```
tests/stage-env/web-ui/
├── backend/              # FastAPI REST API
│   └── app/
│       ├── api/routes/
│       │   ├── scenarios.py    # Управление сценариями
│       │   ├── tests.py        # Запуск тестов
│       │   ├── results.py      # Результаты
│       │   └── logs.py         # Логи
│       ├── core/
│       │   ├── stage_env_executor.py  # Интеграция со stage-env CLI
│       │   └── yaml_parser.py         # Парсинг YAML сценариев
│       └── models/
│           ├── scenario.py     # Модели сценариев
│           └── test_result.py  # Модели результатов
│
├── frontend/             # React + Vite + TypeScript
│   └── src/
│       ├── pages/
│       │   ├── Dashboard.tsx         # Обзор тестов
│       │   ├── Scenarios.tsx         # Список сценариев
│       │   ├── TestExecution.tsx     # Мониторинг выполнения
│       │   ├── Results.tsx           # Результаты тестов
│       │   └── Logs.tsx              # Просмотр логов
│       └── components/
│           ├── ScenarioEditor.tsx    # YAML редактор
│           ├── TestMonitor.tsx       # Real-time монитор
│           └── LogViewer.tsx         # Просмотр логов
│
└── tests/e2e/            # Playwright e2e тесты
    └── tests/
        ├── test_dashboard.py         # ✅ 8 тестов готово
        ├── test_scenarios.py         # TODO
        └── test_test_execution.py    # TODO
```

## 🔑 Ключевые функции

### 1. Управление сценариями
- Просмотр всех YAML сценариев из `tests/stage-env/scenarios/`
- Создание новых сценариев через web UI
- Редактирование с подсветкой синтаксиса и валидацией
- Граф зависимостей между сценариями

### 2. Запуск тестов
- Выбор сценария для запуска
- Настройка параметров запуска
- Real-time мониторинг выполнения через WebSocket
- Возможность остановки тестов

### 3. Результаты тестов
- История всех запусков
- Детальные результаты каждого теста
- Сравнение результатов между запусками
- Статистика и графики

### 4. Логи
- Real-time streaming логов
- Фильтрация по уровням (DEBUG, INFO, ERROR)
- Поиск по логам
- Скачивание логов

### 5. Визуализация
- Граф зависимостей сценариев
- Timeline выполнения тестов
- Статистика по времени выполнения
- Тренды качества

## 🔗 Интеграция со Stage-Env

### Backend интеграция

```python
# app/core/stage_env_executor.py
class StageEnvExecutor:
    """Executor для stage-env CLI команд."""
    
    async def run_scenario(self, scenario_path: str):
        """Запуск тестового сценария."""
        cmd = ["./run.sh", scenario_path]
        # Real-time streaming output через WebSocket
        
    async def list_scenarios(self):
        """Список всех сценариев."""
        # Парсинг tests/stage-env/scenarios/
        
    async def parse_results(self, test_id: str):
        """Парсинг результатов теста."""
        # Чтение из tests/stage-env/results/
```

### Frontend интеграция

```typescript
// services/stageEnvService.ts
export class StageEnvService {
  async runScenario(scenarioPath: string) {
    // POST /api/tests/run
  }
  
  async monitorExecution(testId: string) {
    // WebSocket /ws/tests/{testId}
  }
  
  async getResults(testId: string) {
    // GET /api/results/{testId}
  }
}
```

## 🎭 E2E тесты

Используем **Playwright** для e2e тестирования веб-интерфейса:

```bash
# Запуск e2e тестов
cd tests/e2e
pytest tests/ -v

# Smoke тесты (быстрые)
pytest tests/ -m smoke
```

**Готовые тесты:**
- ✅ Dashboard loads и отображает статистику
- ✅ Quick actions работают
- ✅ WebSocket соединение
- ⏳ Scenarios list (TODO)
- ⏳ Test execution monitoring (TODO)
- ⏳ Results viewing (TODO)

## 🚀 Запуск

### Development

```bash
# Backend
cd backend
poetry install
poetry run uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

### Production

```bash
docker-compose up -d
```

## 📊 Текущий статус

**Phase 0: E2E Infrastructure** - 60% готово ✅
- ✅ Playwright setup
- ✅ Base Page Object Model
- ✅ Dashboard тесты (8 тестов)
- ⏳ Scenarios тесты
- ⏳ Stage-env integration

**Phase 1: Backend Foundation** - 85% готово ✅
- ✅ FastAPI structure
- ✅ Core components (exceptions, logging, executor)
- ✅ Base models and responses
- ✅ Dependency injection
- ⏳ Stage-env executor (нужно адаптировать)

**Следующие шаги:**
1. Переименовать SLCExecutor → StageEnvExecutor
2. Создать модели для Scenario, TestResult
3. Адаптировать API endpoints для stage-env
4. Обновить frontend для stage-env UI
5. Создать YAML editor компонент
6. Добавить log viewer компонент

## 🔧 Файлы для переименования/адаптации

```bash
# Backend
backend/app/core/slc_executor.py → stage_env_executor.py
backend/app/config.py → обновить пути на tests/stage-env
backend/app/models/task.py → scenario.py

# Frontend  
frontend/src/services/slcService.ts → stageEnvService.ts
frontend/src/pages/Tasks.tsx → Scenarios.tsx
frontend/src/pages/Templates.tsx → TestExecution.tsx

# E2E
tests/e2e/pages/tasks_page.py → scenarios_page.py
tests/e2e/tests/test_tasks.py → test_scenarios.py
```

## 📝 Резюме

Задача **исправлена**: теперь фокус на **веб-интерфейсе для stage-env**, а не для SLC Agent.

Вся созданная инфраструктура (Playwright, POM, FastAPI, базовые компоненты) остается актуальной и будет адаптирована для stage-env!
