"""
Pytest configuration and fixtures for e2e tests.
"""

import pytest
from playwright.sync_api import Page, BrowserContext


# === Configuration ===

def pytest_configure(config):
    """Pytest configuration hook."""
    config.addinivalue_line(
        "markers", "smoke: mark test as smoke test (quick checks)"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow test"
    )
    config.addinivalue_line(
        "markers", "websocket: mark test as websocket test"
    )


# === Server Fixtures ===

@pytest.fixture(scope="session")
def backend_url():
    """Backend server URL."""
    # В stage-env это будет динамически определяться
    return "http://localhost:8000"


@pytest.fixture(scope="session")
def frontend_url():
    """Frontend server URL."""
    # В stage-env это будет динамически определяться
    return "http://localhost:5173"


@pytest.fixture(scope="session")
def base_url(frontend_url):
    """Base URL for tests (alias for frontend_url)."""
    return frontend_url


# === Browser Fixtures ===

@pytest.fixture
def context(context: BrowserContext):
    """Configure browser context."""
    # Set viewport (можно параметризовать для mobile/desktop)
    context.set_default_timeout(30000)  # 30 seconds
    
    # Add custom headers if needed
    # context.set_extra_http_headers({"X-Test": "true"})
    
    yield context


@pytest.fixture
def page(page: Page, base_url: str):
    """Configure page with base URL."""
    # Можно добавить global setup
    page.set_default_timeout(30000)
    
    # Navigate to base URL (опционально)
    # page.goto(base_url)
    
    yield page
    
    # Cleanup после каждого теста
    # page.close() - не нужно, playwright делает автоматически


# === Authentication Fixtures ===

@pytest.fixture
def authenticated_page(page: Page, base_url: str):
    """Page with authenticated user."""
    # TODO: Implement authentication when added
    # For now, just return page
    # page.goto(f"{base_url}/login")
    # page.fill('[name="username"]', "test_user")
    # page.fill('[name="password"]', "test_password")
    # page.click('button[type="submit"]')
    # page.wait_for_url(f"{base_url}/dashboard")
    
    yield page


# === Data Fixtures ===

@pytest.fixture
def test_task_data():
    """Test task data."""
    return {
        "title": "E2E Test Task",
        "category": "testing",
        "priority": "HIGH",
        "summary": "This is a test task created by e2e tests",
        "goals": ["Goal 1", "Goal 2"],
        "tags": ["e2e", "test"]
    }


@pytest.fixture
def cleanup_test_tasks(page: Page):
    """Cleanup test tasks after test."""
    created_task_ids = []
    
    yield created_task_ids
    
    # Cleanup logic here
    # for task_id in created_task_ids:
    #     delete_task(task_id)


# === Screenshot Fixtures ===

@pytest.fixture(autouse=True)
def screenshot_on_failure(request, page: Page):
    """Take screenshot on test failure."""
    yield
    
    if request.node.rep_call.failed:
        # Screenshot уже сделан Playwright автоматически
        # Но можно сделать дополнительный с custom именем
        screenshot_name = f"failure_{request.node.name}.png"
        page.screenshot(path=f"test-results/{screenshot_name}")


# === Pytest Hooks ===

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Make test result available in fixtures."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
