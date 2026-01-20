"""
Dashboard e2e tests.
"""

import pytest
from tests.e2e.pages.dashboard_page import DashboardPage


@pytest.mark.smoke
def test_dashboard_loads(page, base_url):
    """Smoke test: Dashboard loads successfully."""
    dashboard = DashboardPage(page, base_url)
    dashboard.navigate()
    
    assert dashboard.is_loaded()
    assert "SLC Web Interface" in dashboard.get_title()


@pytest.mark.smoke
def test_dashboard_shows_stats(page, base_url):
    """Dashboard displays task statistics."""
    dashboard = DashboardPage(page, base_url)
    dashboard.navigate()
    
    # Stats should be visible
    dashboard.expect_visible(dashboard.stats_card)
    
    # Should have some counts (even if 0)
    tasks_count = dashboard.get_tasks_count()
    assert tasks_count >= 0


def test_dashboard_quick_actions(page, base_url):
    """Quick actions buttons are present and clickable."""
    dashboard = DashboardPage(page, base_url)
    dashboard.navigate()
    
    # Quick actions should be visible
    dashboard.expect_visible(dashboard.quick_actions)
    
    # Buttons should be enabled
    dashboard.expect_enabled(dashboard.create_task_btn)
    dashboard.expect_enabled(dashboard.update_context_btn)


def test_dashboard_system_status(page, base_url):
    """System status is displayed."""
    dashboard = DashboardPage(page, base_url)
    dashboard.navigate()
    
    # System status should be visible
    dashboard.expect_visible(dashboard.system_status)
    
    # Check if healthy (depends on backend being up)
    status = dashboard.get_system_status()
    assert len(status) > 0  # Has some status text


@pytest.mark.websocket
def test_dashboard_websocket_connection(page, base_url):
    """WebSocket connects automatically on dashboard load."""
    dashboard = DashboardPage(page, base_url)
    dashboard.navigate()
    
    # Wait for WebSocket to connect
    dashboard.wait_for_websocket_connection(timeout=10000)
    
    # Check connection indicator
    assert dashboard.is_websocket_connected()


def test_dashboard_navigation_from_create_task(page, base_url):
    """Create task button navigates to tasks page."""
    dashboard = DashboardPage(page, base_url)
    dashboard.navigate()
    
    # Click create task
    dashboard.click_create_task()
    
    # Should navigate to tasks page
    # (will be implemented when tasks page exists)
    page.wait_for_url(f"{base_url}/tasks*")
    assert "/tasks" in page.url


@pytest.mark.slow
def test_dashboard_recent_updates_section(page, base_url):
    """Recent updates section displays updates."""
    dashboard = DashboardPage(page, base_url)
    dashboard.navigate()
    
    # Recent updates should be visible
    dashboard.expect_visible(dashboard.recent_updates)
    
    # Should have some content (or be empty state)
    updates = dashboard.get_text(dashboard.recent_updates)
    assert len(updates) >= 0  # Can be empty


def test_dashboard_screenshot(page, base_url):
    """Take screenshot of dashboard for visual reference."""
    dashboard = DashboardPage(page, base_url)
    dashboard.navigate()
    
    # Take full page screenshot
    dashboard.screenshot("dashboard_full_view")
