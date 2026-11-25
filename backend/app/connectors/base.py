from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.schemas.event import NormalizedEvent


class ConnectorError(Exception):
    """Base exception for connector failures."""


class ConnectorAuthError(ConnectorError):
    """Raised when connector credentials are missing, malformed, or rejected."""


class ConnectorNotFoundError(ConnectorError):
    """Raised when requesting a provider not registered in ConnectorRegistry."""


class BaseConnector(ABC):
    """
    Abstract base interface that all PulseOps data connectors must implement.

    Each connector binds to a distinct ``provider`` key (e.g., ``fake``,
    ``razorpay``, ``github``, ``csv``) and produces validated ``NormalizedEvent``
    records ready for idempotent persistence.
    """

    provider: str = ""

    @abstractmethod
    def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        """
        Validate provider credentials before executing data syncs.

        Returns True when valid; raises ConnectorAuthError or returns False
        when invalid.
        """

    @abstractmethod
    def fetch_events(
        self,
        credentials: dict[str, Any],
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        """
        Fetch and normalize events from the upstream source since ``since``.
        """

    @abstractmethod
    def normalize(self, raw_event: dict[str, Any]) -> NormalizedEvent:
        """
        Convert a provider-specific raw event dictionary into a NormalizedEvent.
        """
