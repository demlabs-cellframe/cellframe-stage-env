"""
Base Page Object Model class.
All page objects inherit from this.
"""

from playwright.sync_api import Page, expect


class BasePage:
    """
    Base class for all Page Objects.
    Provides common functionality for all pages.
    """
    
    def __init__(self, page: Page, base_url: str = "http://localhost:5173"):
        """
        Initialize base page.
        
        Args:
            page: Playwright page instance
            base_url: Base URL of the application
        """
        self.page = page
        self.base_url = base_url
        self.url_path = "/"  # Override in subclasses
    
    def navigate(self) -> None:
        """Navigate to the page."""
        url = f"{self.base_url}{self.url_path}"
        self.page.goto(url)
        self.wait_for_load()
    
    def wait_for_load(self) -> None:
        """
        Wait for page to load.
        Override in subclasses for specific wait conditions.
        """
        # Default: wait for network idle
        self.page.wait_for_load_state("networkidle")
    
    def get_title(self) -> str:
        """Get page title."""
        return self.page.title()
    
    def is_loaded(self) -> bool:
        """
        Check if page is loaded.
        Override in subclasses for specific checks.
        """
        return self.page.url.startswith(self.base_url)
    
    # === Common element interactions ===
    
    def click(self, selector: str) -> None:
        """Click element."""
        self.page.click(selector)
    
    def fill(self, selector: str, value: str) -> None:
        """Fill input field."""
        self.page.fill(selector, value)
    
    def select(self, selector: str, value: str) -> None:
        """Select dropdown option."""
        self.page.select_option(selector, value)
    
    def check(self, selector: str) -> None:
        """Check checkbox."""
        self.page.check(selector)
    
    def uncheck(self, selector: str) -> None:
        """Uncheck checkbox."""
        self.page.uncheck(selector)
    
    def get_text(self, selector: str) -> str:
        """Get element text."""
        return self.page.text_content(selector) or ""
    
    def get_value(self, selector: str) -> str:
        """Get input value."""
        return self.page.input_value(selector)
    
    def is_visible(self, selector: str) -> bool:
        """Check if element is visible."""
        return self.page.is_visible(selector)
    
    def is_enabled(self, selector: str) -> bool:
        """Check if element is enabled."""
        return self.page.is_enabled(selector)
    
    def wait_for_selector(self, selector: str, timeout: int = 30000) -> None:
        """Wait for selector to appear."""
        self.page.wait_for_selector(selector, timeout=timeout)
    
    def wait_for_text(self, text: str, timeout: int = 30000) -> None:
        """Wait for text to appear."""
        self.page.wait_for_selector(f'text="{text}"', timeout=timeout)
    
    # === Common assertions (with Playwright expect) ===
    
    def expect_visible(self, selector: str) -> None:
        """Assert element is visible."""
        expect(self.page.locator(selector)).to_be_visible()
    
    def expect_hidden(self, selector: str) -> None:
        """Assert element is hidden."""
        expect(self.page.locator(selector)).to_be_hidden()
    
    def expect_text(self, selector: str, text: str) -> None:
        """Assert element contains text."""
        expect(self.page.locator(selector)).to_contain_text(text)
    
    def expect_value(self, selector: str, value: str) -> None:
        """Assert input has value."""
        expect(self.page.locator(selector)).to_have_value(value)
    
    def expect_enabled(self, selector: str) -> None:
        """Assert element is enabled."""
        expect(self.page.locator(selector)).to_be_enabled()
    
    def expect_disabled(self, selector: str) -> None:
        """Assert element is disabled."""
        expect(self.page.locator(selector)).to_be_disabled()
    
    # === Screenshot helpers ===
    
    def screenshot(self, name: str) -> None:
        """Take screenshot."""
        self.page.screenshot(path=f"test-results/{name}.png")
    
    def screenshot_element(self, selector: str, name: str) -> None:
        """Take screenshot of specific element."""
        self.page.locator(selector).screenshot(path=f"test-results/{name}.png")
