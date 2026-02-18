"""
Abstract base class for storage backends.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class StorageBackend(ABC):
    """Abstract storage backend for signal persistence."""

    @abstractmethod
    async def initialize(self) -> None:
        """Create tables/collections if they don't exist."""

    @abstractmethod
    async def store(self, signal: Dict[str, Any]) -> str:
        """Store a signal and return its ID."""

    @abstractmethod
    async def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get the most recent signal for a symbol."""

    @abstractmethod
    async def get_history(
        self, symbol: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get signal history for a symbol with pagination."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if storage is available."""

    @abstractmethod
    async def cleanup(self, retention_days: int) -> int:
        """Delete signals older than retention_days. Returns count deleted."""
