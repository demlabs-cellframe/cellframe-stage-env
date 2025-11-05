"""
Base class for checkers (validation operations).

Checkers are used for immediate validation checks, unlike waiters which poll
until a condition is met. Checkers verify state and raise exceptions on failure.
"""

from abc import ABC, abstractmethod


class BaseChecker(ABC):
    """
    Base class for checkers (used in genesis and validation).
    
    Checkers perform immediate validation and raise exceptions on failure.
    Unlike waiters, they don't poll - they check once and fail fast.
    
    Usage:
        class MyChecker(BaseChecker):
            async def check(self) -> bool:
                # Check condition
                return is_valid
            
            async def verify(self):
                # Optional: override verify() for custom error handling
                if not await self.check():
                    raise RuntimeError("Validation failed")
        
        checker = MyChecker(...)
        await checker.verify()  # Raises exception if check fails
    """
    
    @abstractmethod
    async def check(self) -> bool:
        """
        Check if condition is valid.
        
        Returns:
            True if validation passes, False otherwise
        """
        pass
    
    async def verify(self) -> None:
        """
        Verify condition and raise exception on failure.
        
        By default, calls check() and raises RuntimeError if False.
        Subclasses can override for custom error messages.
        
        Raises:
            RuntimeError: If validation fails
        """
        if not await self.check():
            raise RuntimeError("Validation check failed")

