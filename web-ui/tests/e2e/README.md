# E2E тесты для SLC Web Interface

Комплексные end-to-end тесты используя Playwright.

## 🎭 Playwright

Playwright - современный фреймворк для e2e тестирования веб-приложений.

### Преимущества:
- ✅ **Multi-browser**: Chromium, Firefox, WebKit
- ✅ **Auto-waiting**: Автоматическое ожидание элементов
- ✅ **Screenshots/Video**: При падении теста
- ✅ **Fast**: Параллельное выполнение
- ✅ **Python native**: Не wrapper
- ✅ **Dev tools**: Отличные инструменты отладки

## 🚀 Быстрый старт

### Установка

```bash
# Установка зависимостей
pip install playwright pytest-playwright

# Установка браузеров
playwright install
```

### Запуск тестов

```bash
# Все e2e тесты
pytest tests/e2e/

# Конкретный тест
pytest tests/e2e/tests/test_dashboard.py

# В headed режиме (видимый браузер)
pytest tests/e2e/ --headed

# Конкретный браузер
pytest tests/e2e/ --browser chromium
pytest tests/e2e/ --browser firefox
pytest tests/e2e/ --browser webkit

# Параллельно (быстрее)
pytest tests/e2e/ -n auto

# С видео при падении
pytest tests/e2e/ --video on
```

## 📁 Структура

```
tests/e2e/
├── conftest.py              # Pytest fixtures
├── playwright.config.py     # Playwright конфигурация
├── pages/                   # Page Object Model
│   ├── base_page.py        # Базовый класс
│   ├── dashboard_page.py   # Dashboard
│   ├── tasks_page.py       # Tasks management
│   ├── templates_page.py   # Templates browser
│   └── context_page.py     # Context visualization
├── tests/                   # Тесты
│   ├── test_dashboard.py   # Dashboard тесты
│   ├── test_tasks.py       # Tasks тесты
│   ├── test_templates.py   # Templates тесты
│   └── test_websocket.py   # WebSocket тесты
├── fixtures/                # Специализированные fixtures
│   ├── auth_fixtures.py    # Аутентификация
│   ├── data_fixtures.py    # Тестовые данные
│   └── server_fixtures.py  # Запуск серверов
└── utils/                   # Утилиты
    ├── helpers.py          # Helper функции
    └── wait_conditions.py  # Custom wait conditions
```

## 🎨 Page Object Model

Используем POM паттерн для переиспользования кода:

```python
from tests.e2e.pages.dashboard_page import DashboardPage

def test_dashboard_loads(page):
    dashboard = DashboardPage(page)
    dashboard.navigate()
    
    assert dashboard.is_loaded()
    assert dashboard.get_tasks_count() > 0
```

## 🔧 Fixtures

### Server Fixtures

```python
@pytest.fixture(scope="session")
def backend_server():
    """Запускает backend сервер для тестов."""
    # Запуск FastAPI
    yield server_url
    # Остановка

@pytest.fixture(scope="session")  
def frontend_server():
    """Запускает frontend сервер для тестов."""
    # Запуск Vite dev server
    yield frontend_url
    # Остановка
```

### Page Fixtures

```python
@pytest.fixture
def dashboard_page(page):
    """Dashboard page instance."""
    return DashboardPage(page)
```

## 📝 Написание тестов

### Базовый тест

```python
def test_dashboard_title(page):
    """Проверка что dashboard имеет правильный title."""
    page.goto("http://localhost:5173")
    
    # Playwright автоматически ждет загрузки
    title = page.title()
    assert "SLC Web Interface" in title
```

### С Page Object

```python
from tests.e2e.pages.tasks_page import TasksPage

def test_create_task(page):
    """Тест создания задачи."""
    tasks_page = TasksPage(page)
    tasks_page.navigate()
    
    # Создать задачу
    tasks_page.click_create_button()
    tasks_page.fill_task_form(
        title="Test Task",
        category="testing",
        priority="HIGH"
    )
    tasks_page.submit_form()
    
    # Проверить что задача создана
    assert tasks_page.has_task("Test Task")
```

### Тестирование WebSocket

```python
def test_realtime_updates(page):
    """Тест real-time обновлений через WebSocket."""
    page.goto("http://localhost:5173/dashboard")
    
    # Подождать WebSocket соединения
    page.wait_for_selector('[data-testid="ws-connected"]')
    
    # Создать задачу в другой вкладке/API
    create_task_via_api({"title": "New Task"})
    
    # Проверить что задача появилась без перезагрузки
    page.wait_for_selector('text="New Task"', timeout=5000)
```

## 🐛 Отладка

### Debug режим

```bash
# Пауза на каждом шаге
PWDEBUG=1 pytest tests/e2e/tests/test_dashboard.py
```

### Screenshots

```python
def test_with_screenshot(page):
    page.goto("http://localhost:5173")
    page.screenshot(path="screenshot.png")
```

### Tracing

```python
from playwright.sync_api import sync_playwright

def test_with_trace(page, context):
    context.tracing.start(screenshots=True, snapshots=True)
    
    # Тест...
    
    context.tracing.stop(path="trace.zip")
    # Открыть: playwright show-trace trace.zip
```

## 🔗 Интеграция со Stage-Env

E2E тесты интегрированы в stage-env тестовую инфраструктуру:

```bash
# Через stage-env (автоматический запуск backend/frontend)
cd tests/stage-env
./run.sh scenarios/web_e2e/dashboard_tests.yml
```

Stage-env автоматически:
1. Запускает backend в тестовом режиме
2. Запускает frontend в тестовом режиме
3. Ждет готовности серверов (health checks)
4. Запускает Playwright тесты
5. Собирает логи, скриншоты, видео
6. Останавливает серверы

## 📊 Coverage

E2E тесты покрывают критические user flows:
- ✅ Загрузка всех основных страниц
- ✅ CRUD операции с задачами
- ✅ Поиск и фильтрация шаблонов
- ✅ Визуализация графа контекста
- ✅ Real-time обновления через WebSocket
- ✅ Обработка ошибок
- ✅ Responsive layout (mobile/desktop)

## 🎯 Best Practices

1. **Используй data-testid**: `<div data-testid="task-item">...</div>`
2. **Page Object Model**: Переиспользуй page классы
3. **Автоматические ожидания**: Playwright сам ждет элементы
4. **Изоляция тестов**: Каждый тест независим
5. **Cleanup**: Удаляй тестовые данные после теста
6. **Параллельность**: Используй `-n auto` для скорости

## 🔗 Ссылки

- [Playwright Documentation](https://playwright.dev/python/)
- [pytest-playwright](https://playwright.dev/python/docs/test-runners)
- [Best Practices](https://playwright.dev/python/docs/best-practices)
