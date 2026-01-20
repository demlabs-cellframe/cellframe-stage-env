# SLC Web Interface

Веб-интерфейс для управления Smart Layered Context (SLC) системой.

## 🎯 Описание

Полнофункциональный веб-интерфейс для SLC Agent, предоставляющий:
- REST API на Python (FastAPI) для всех SLC команд
- Современный фронтенд на React + Vite + TypeScript + Material-UI
- Real-time обновления через WebSocket
- Визуализацию графа зависимостей контекста
- Интерактивное управление задачами и шаблонами
- Систему мониторинга и аналитики

## 🏗️ Архитектура

```
slc-web-interface/
├── backend/          # FastAPI REST API
│   ├── app/
│   │   ├── api/      # API endpoints
│   │   ├── core/     # Core функциональность (SLCExecutor, file watcher)
│   │   ├── models/   # Pydantic модели
│   │   └── services/ # Бизнес-логика
│   └── tests/        # Pytest тесты
├── frontend/         # React + Vite + TypeScript
│   ├── src/
│   │   ├── pages/    # Страницы (Dashboard, Tasks, Templates, etc.)
│   │   ├── components/ # React компоненты
│   │   ├── services/ # API клиенты
│   │   ├── store/    # Zustand state management
│   │   └── types/    # TypeScript типы
│   └── tests/        # Vitest тесты
├── docker/           # Docker конфигурация
├── nginx/            # Nginx конфигурация
└── docs/             # Документация
```

## 🚀 Технологический стек

### Backend
- **Framework**: FastAPI (Python 3.11+)
- **Async**: asyncio + uvicorn
- **Validation**: Pydantic v2
- **WebSocket**: FastAPI WebSocket
- **Logging**: structlog
- **Testing**: pytest + pytest-asyncio

### Frontend
- **Framework**: React 18
- **Build Tool**: Vite
- **Language**: TypeScript
- **UI Library**: Material-UI (MUI) v5
- **State Management**: Zustand
- **Routing**: React Router v6
- **HTTP Client**: Axios
- **Visualization**: React Flow (граф зависимостей)
- **Code Editor**: Monaco Editor
- **Testing**: Vitest + React Testing Library

## 📋 Требования

- Python 3.11+
- Node.js 18+ (для фронтенда)
- Poetry (для Python зависимостей)
- SLC CLI установлен и доступен

## 🔧 Быстрый старт

### Backend

```bash
cd backend
poetry install
cp .env.example .env
# Отредактируйте .env файл под ваше окружение
poetry run uvicorn app.main:app --reload
```

Backend будет доступен на http://localhost:8000

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
# Отредактируйте .env файл (API URL и т.д.)
npm run dev
```

Frontend будет доступен на http://localhost:5173

## 🧪 Тестирование

### Backend тесты

```bash
cd backend
poetry run pytest
poetry run pytest --cov=app --cov-report=html
```

### Frontend тесты

```bash
cd frontend
npm run test
npm run test:coverage
```

## 📊 Фазы разработки

1. ✅ **Backend Foundation** - Основа бэкенда (FastAPI, SLCExecutor, модели)
2. ⏳ **Core API** - REST API endpoints для задач, шаблонов, контекста
3. ⏳ **WebSocket** - Real-time обновления
4. ⏳ **Services & Caching** - Бизнес-логика и кэширование
5. ⏳ **Frontend Foundation** - Основа фронтенда (React, TypeScript, MUI)
6. ⏳ **State Management** - Zustand stores и WebSocket интеграция
7. ⏳ **Dashboard & Tasks** - UI для управления задачами
8. ⏳ **Templates & Context** - Браузер шаблонов и визуализация контекста
9. ⏳ **Analytics** - Аналитика и статистика
10. ⏳ **Polish & Testing** - Полировка и тестирование (>90% backend, >80% frontend)
11. ⏳ **Deployment** - Docker, nginx, CI/CD, мониторинг

## 🔒 Безопасность

- **Command Whitelisting**: Только разрешённые SLC команды могут быть выполнены
- **Input Validation**: Pydantic на backend, TypeScript на frontend
- **CORS**: Настраиваемая CORS политика
- **Rate Limiting**: Защита от abuse (SlowAPI)
- **File Access**: Ограничен только .context/ директорией
- **Authentication**: JWT tokens (опционально для production)

## 📈 Мониторинг

В production доступны:
- Health checks: `/health`, `/health/ready`
- Metrics: Application и system метрики
- Structured logging: JSON формат с structlog
- Alerting: Критические ошибки и производительность

## 🐳 Docker Deployment

```bash
docker-compose up -d
```

Поднимает:
- Backend (FastAPI + uvicorn)
- Frontend (nginx + static build)
- Nginx reverse proxy

## 📚 Документация

- **API Documentation**: http://localhost:8000/docs (OpenAPI/Swagger)
- **ReDoc**: http://localhost:8000/redoc
- **Задача СЛК**: `.context/tasks/slc_web_interface.json`

## 🎨 Философия разработки

Проект следует принципам СЛК системы:
- ✅ **FAIL-FAST**: Никаких fallback'ов, явные ошибки
- ✅ **NO MOCKS**: Только реальные интеграции с SLC CLI
- ✅ **TYPE SAFETY**: Строгая типизация (Python type hints, TypeScript)
- ✅ **PRODUCTION-READY**: С первого раза делаем правильно
- ✅ **TEST COVERAGE**: Backend >90%, Frontend >80%

## 🤝 Contributing

См. `CONTRIBUTING.md` для guidelines по контрибуциям.

## 📝 Лицензия

См. LICENSE файл в корне проекта.

## 🔗 Связанные ресурсы

- [SLC CLI](../slc) - Smart Layered Context CLI
- [Cellframe Node](../) - Основной проект
- [SLC Документация](../.context/README.md)
