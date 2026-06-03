"""Abstract base connector class for all LoopLM integrations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal, Optional


Phase = Literal[
    "fetching_traces",
    "processing_traces",
    "fetching_scores",
    "processing_scores",
]


@dataclass
class SyncProgress:
    """A single progress event emitted by a connector during sync."""

    phase: Phase
    message: str
    current: Optional[int] = None
    total: Optional[int] = None


ProgressCallback = Callable[[SyncProgress], Awaitable[None]]


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
    async def sync(
        self,
        since: datetime,
        on_progress: ProgressCallback | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """Full sync flow: fetch traces, normalize, and return raw traces."""
        ...
