"""
Dashboard Page Object Model.
"""

from tests.e2e.pages.base_page import BasePage


class DashboardPage(BasePage):
    """Dashboard page interactions."""
    
    def __init__(self, page, base_url="http://localhost:5173"):
        super().__init__(page, base_url)
        self.url_path = "/dashboard"
        
        # Selectors (data-testid preferred for stability)
        self.stats_card = '[data-testid="stats-card"]'
        self.tasks_stat = '[data-testid="tasks-stat"]'
        self.active_tasks = '[data-testid="active-tasks"]'
        self.completed_tasks = '[data-testid="completed-tasks"]'
        self.quick_actions = '[data-testid="quick-actions"]'
        self.create_task_btn = '[data-testid="create-task-btn"]'
        self.update_context_btn = '[data-testid="update-context-btn"]'
        self.recent_updates = '[data-testid="recent-updates"]'
        self.system_status = '[data-testid="system-status"]'
        self.ws_indicator = '[data-testid="ws-connected"]'
    
    def wait_for_load(self) -> None:
        """Wait for dashboard to load."""
        self.wait_for_selector(self.stats_card)
        self.wait_for_selector(self.system_status)
    
    def is_loaded(self) -> bool:
        """Check if dashboard is loaded."""
        return (
            self.is_visible(self.stats_card) and
            self.is_visible(self.system_status)
        )
    
    # === Stats ===
    
    def get_tasks_count(self) -> int:
        """Get total tasks count from stats."""
        text = self.get_text(self.tasks_stat)
        # Extract number from text (e.g., "15 Tasks" -> 15)
        return int(''.join(filter(str.isdigit, text)))
    
    def get_active_tasks_count(self) -> int:
        """Get active tasks count."""
        text = self.get_text(self.active_tasks)
        return int(''.join(filter(str.isdigit, text)))
    
    def get_completed_tasks_count(self) -> int:
        """Get completed tasks count."""
        text = self.get_text(self.completed_tasks)
        return int(''.join(filter(str.isdigit, text)))
    
    # === Quick Actions ===
    
    def click_create_task(self) -> None:
        """Click create task button."""
        self.click(self.create_task_btn)
    
    def click_update_context(self) -> None:
        """Click update context button."""
        self.click(self.update_context_btn)
    
    # === System Status ===
    
    def get_system_status(self) -> str:
        """Get system status text."""
        return self.get_text(self.system_status)
    
    def is_system_healthy(self) -> bool:
        """Check if system status is healthy."""
        status = self.get_system_status()
        return "healthy" in status.lower()
    
    # === WebSocket ===
    
    def is_websocket_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.is_visible(self.ws_indicator)
    
    def wait_for_websocket_connection(self, timeout: int = 10000) -> None:
        """Wait for WebSocket to connect."""
        self.wait_for_selector(self.ws_indicator, timeout=timeout)
    
    # === Recent Updates ===
    
    def has_recent_update(self, text: str) -> bool:
        """Check if recent updates contain specific text."""
        updates = self.get_text(self.recent_updates)
        return text in updates
