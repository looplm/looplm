"""Abstract base connector class for all LoopLM integrations."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class BaseConnector(ABC):
    """Base class that all LoopLM connectors must implement."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Verify that API credentials are valid and the service is reachable."""
        ...

    @abstractmethod
    async def fetch_traces(self, since: datetime, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch raw traces from the external platform."""
        ...

    @abstractmethod
    async def fetch_trace_detail(self, trace_id: str) -> dict[str, Any]:
        """Fetch full detail for a single trace, including observations/spans."""
        ...

    @abstractmethod
    def normalize_trace(self, raw_trace: dict[str, Any]) -> dict[str, Any]:
        """Convert a raw platform trace into LoopLM's normalized format."""
        ...

    @abstractmethod
    async def sync(self, since: datetime) -> list[dict[str, Any]]:
        """Full sync flow: fetch traces, normalize, and return raw traces."""
        ...
