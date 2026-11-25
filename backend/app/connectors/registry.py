from __future__ import annotations

from app.connectors.base import BaseConnector, ConnectorNotFoundError


class ConnectorRegistry:
    """
    Central registry mapping provider identifiers to BaseConnector subclasses.
    """

    def __init__(self) -> None:
        self._connectors: dict[str, type[BaseConnector]] = {}

    def register(
        self,
        connector_cls: type[BaseConnector],
        *,
        overwrite: bool = False,
    ) -> type[BaseConnector]:
        """
        Register a BaseConnector subclass under its ``provider`` identifier.
        Can be used directly or as a class decorator.
        """
        if not isinstance(connector_cls, type) or not issubclass(
            connector_cls, BaseConnector
        ):
            raise TypeError("Registered class must inherit from BaseConnector.")

        provider_key = (connector_cls.provider or "").strip().lower()
        if not provider_key:
            raise ValueError(
                f"Connector {connector_cls.__name__} must define a non-empty 'provider'."
            )

        existing = self._connectors.get(provider_key)
        if existing is not None and existing is not connector_cls and not overwrite:
            raise ValueError(
                f"Connector provider {provider_key!r} is already registered to {existing.__name__}."
            )

        self._connectors[provider_key] = connector_cls
        return connector_cls

    def get(self, provider: str) -> BaseConnector:
        """Instantiate and return the connector registered for ``provider``."""
        provider_key = (provider or "").strip().lower()
        connector_cls = self._connectors.get(provider_key)
        if connector_cls is None:
            raise ConnectorNotFoundError(
                f"No connector registered for provider {provider!r}."
            )
        return connector_cls()

    def is_registered(self, provider: str) -> bool:
        """Return True if ``provider`` is registered."""
        return (provider or "").strip().lower() in self._connectors

    def list_providers(self) -> list[str]:
        """Return sorted list of registered provider keys."""
        return sorted(self._connectors.keys())


connector_registry = ConnectorRegistry()
