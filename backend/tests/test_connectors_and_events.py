"""
S11 tests for Abstract Connector interface, ConnectorRegistry, FakeConnector,
normalized Event model, idempotent persistence, and tenant isolation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.connectors import (
    BaseConnector,
    ConnectorAuthError,
    ConnectorNotFoundError,
    ConnectorRegistry,
    FakeConnector,
    connector_registry,
)
from app.core.security import encrypt_credentials
from app.models.event import Event
from app.models.integration import Integration, IntegrationStatus
from app.models.organization import Organization
from app.schemas.event import NormalizedEvent
from app.services.event_service import (
    get_event_by_id,
    ingest_events,
    list_events,
    sync_connector_events,
)


# ---------------------------------------------------------------------------
# Connector ABC & Registry Tests
# ---------------------------------------------------------------------------


class TestConnectorInterfaceAndRegistry:
    """Verify abstract connector contract and registry behavior."""

    def test_base_connector_cannot_be_instantiated_directly(self):
        with pytest.raises(TypeError):
            BaseConnector()  # type: ignore[abstract]

    def test_global_registry_has_fake_connector(self):
        assert connector_registry.is_registered("fake")
        assert "fake" in connector_registry.list_providers()
        connector = connector_registry.get("FAKE")
        assert isinstance(connector, FakeConnector)
        assert connector.provider == "fake"

    def test_registry_unknown_provider_raises_not_found(self):
        with pytest.raises(ConnectorNotFoundError):
            connector_registry.get("nonexistent_provider")

    def test_registry_register_and_duplicate_guards(self):
        reg = ConnectorRegistry()

        class DummyConnector(BaseConnector):
            provider = "dummy"

            def validate_credentials(self, credentials: dict[str, Any]) -> bool:
                return True

            def fetch_events(
                self, credentials: dict[str, Any], since: datetime | None = None
            ) -> list[NormalizedEvent]:
                return []

            def normalize(self, raw_event: dict[str, Any]) -> NormalizedEvent:
                return NormalizedEvent(
                    source="dummy",
                    external_id=str(raw_event["id"]),
                    event_type="dummy.event",
                    occurred_at=datetime.now(timezone.utc),
                )

        class DuplicateDummyConnector(DummyConnector):
            pass

        class EmptyProviderConnector(DummyConnector):
            provider = ""

        reg.register(DummyConnector)
        assert isinstance(reg.get("dummy"), DummyConnector)

        with pytest.raises(ValueError, match="already registered"):
            reg.register(DuplicateDummyConnector)

        reg.register(DuplicateDummyConnector, overwrite=True)
        assert isinstance(reg.get("dummy"), DuplicateDummyConnector)

        with pytest.raises(ValueError, match="non-empty 'provider'"):
            reg.register(EmptyProviderConnector)

        with pytest.raises(TypeError):
            reg.register(object)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fake Connector Tests
# ---------------------------------------------------------------------------


class TestFakeConnector:
    """Verify FakeConnector credential checks, fetch_events, and normalization."""

    def test_validate_credentials_accepts_dict_and_rejects_fail_flag(self):
        conn = FakeConnector()
        assert conn.validate_credentials({}) is True
        assert conn.validate_credentials({"mode": "synthetic"}) is True

        with pytest.raises(ConnectorAuthError):
            conn.validate_credentials({"fail_auth": True})

        with pytest.raises(ConnectorAuthError):
            conn.validate_credentials("invalid")  # type: ignore[arg-type]

    def test_fetch_events_returns_normalized_events_and_filters_since(self):
        conn = FakeConnector()
        all_events = conn.fetch_events({})
        assert len(all_events) == 4
        assert all(isinstance(e, NormalizedEvent) for e in all_events)
        assert all(e.source == "fake" for e in all_events)
        assert all(e.occurred_at.tzinfo == timezone.utc for e in all_events)

        cutoff = all_events[2].occurred_at
        filtered = conn.fetch_events({}, since=cutoff)
        assert len(filtered) == 2
        assert all(e.occurred_at >= cutoff for e in filtered)

    def test_normalize_converts_naive_datetime_to_utc(self):
        conn = FakeConnector()
        naive_dt = datetime(2026, 11, 10, 8, 30, 0)
        evt = conn.normalize(
            {
                "external_id": "custom_01",
                "event_type": "custom.ping",
                "occurred_at": naive_dt,
                "payload": {"ok": True},
            }
        )
        assert evt.occurred_at.tzinfo == timezone.utc
        assert evt.external_id == "custom_01"
        assert evt.payload == {"ok": True}


# ---------------------------------------------------------------------------
# Event Model & Idempotent Persistence Tests
# ---------------------------------------------------------------------------


class TestEventModelAndIdempotency:
    """Verify Event schema, unique constraints, and idempotent ingestion."""

    def test_unique_constraint_enforced_at_database_level(self, db_session):
        org = Organization(name=f"Constraint Org {uuid.uuid4().hex[:8]}")
        db_session.add(org)
        db_session.flush()

        evt1 = Event(
            organization_id=org.id,
            source="razorpay",
            external_id="pay_123",
            event_type="payment.captured",
            occurred_at=datetime.now(timezone.utc),
            amount_cents=5000,
            currency="USD",
            payload={"method": "card"},
        )
        db_session.add(evt1)
        db_session.flush()

        evt_dup = Event(
            organization_id=org.id,
            source="razorpay",
            external_id="pay_123",
            event_type="payment.captured",
            occurred_at=datetime.now(timezone.utc),
            payload={},
        )
        db_session.add(evt_dup)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_sync_connector_events_is_idempotent(self, db_session):
        org = Organization(name=f"Idempotent Org {uuid.uuid4().hex[:8]}")
        db_session.add(org)
        db_session.flush()

        first = sync_connector_events(
            db_session,
            organization_id=org.id,
            provider="fake",
            credentials={},
        )
        assert first.total_received == 4
        assert first.inserted_count == 4
        assert first.skipped_count == 0

        # Re-syncing identical events skips all duplicates cleanly
        second = sync_connector_events(
            db_session,
            organization_id=org.id,
            provider="fake",
            credentials={},
        )
        assert second.total_received == 4
        assert second.inserted_count == 0
        assert second.skipped_count == 4

        stored = list_events(db_session, organization_id=org.id)
        assert len(stored) == 4

    def test_ingest_events_deduplicates_within_same_batch(self, db_session):
        org = Organization(name=f"Batch Dedup Org {uuid.uuid4().hex[:8]}")
        db_session.add(org)
        db_session.flush()

        now = datetime.now(timezone.utc)
        batch = [
            NormalizedEvent(
                source="github",
                external_id="gh_pr_99",
                event_type="pr.opened",
                occurred_at=now,
                payload={"pr": 99},
            ),
            NormalizedEvent(
                source="github",
                external_id="gh_pr_99",
                event_type="pr.opened",
                occurred_at=now + timedelta(seconds=1),
                payload={"pr": 99},
            ),
        ]

        res = ingest_events(db_session, organization_id=org.id, events=batch)
        assert res.total_received == 2
        assert res.inserted_count == 1
        assert res.skipped_count == 1

    def test_cascade_delete_organization_deletes_events(self, db_session):
        org = Organization(name=f"Cascade Org {uuid.uuid4().hex[:8]}")
        db_session.add(org)
        db_session.flush()

        sync_connector_events(
            db_session,
            organization_id=org.id,
            provider="fake",
            credentials={},
        )
        assert len(list_events(db_session, organization_id=org.id)) == 4

        org_id = org.id
        db_session.delete(org)
        db_session.flush()

        remaining = db_session.scalars(
            select(Event).where(Event.organization_id == org_id)
        ).all()
        assert len(remaining) == 0


# ---------------------------------------------------------------------------
# Multi-Tenant Event Isolation Tests
# ---------------------------------------------------------------------------


class TestEventTenantIsolation:
    """Verify strict per-organization scoping for Event reads and writes."""

    def test_same_external_id_allowed_across_different_organizations(self, db_session):
        org_a = Organization(name=f"Tenant A {uuid.uuid4().hex[:8]}")
        org_b = Organization(name=f"Tenant B {uuid.uuid4().hex[:8]}")
        db_session.add_all([org_a, org_b])
        db_session.flush()

        res_a = sync_connector_events(
            db_session,
            organization_id=org_a.id,
            provider="fake",
            credentials={},
        )
        res_b = sync_connector_events(
            db_session,
            organization_id=org_b.id,
            provider="fake",
            credentials={},
        )

        assert res_a.inserted_count == 4
        assert res_b.inserted_count == 4

        events_a = list_events(db_session, organization_id=org_a.id)
        events_b = list_events(db_session, organization_id=org_b.id)

        assert len(events_a) == 4
        assert len(events_b) == 4
        assert all(e.organization_id == org_a.id for e in events_a)
        assert all(e.organization_id == org_b.id for e in events_b)

        # Cross-tenant get_event_by_id returns None
        assert (
            get_event_by_id(
                db_session,
                organization_id=org_b.id,
                event_id=events_a[0].id,
            )
            is None
        )
        assert (
            get_event_by_id(
                db_session,
                organization_id=org_a.id,
                event_id=events_a[0].id,
            )
            is not None
        )

    def test_cross_tenant_integration_id_rejected(
        self, db_session, test_encryption_key
    ):
        org_a = Organization(name=f"Owner Org {uuid.uuid4().hex[:8]}")
        org_b = Organization(name=f"Other Org {uuid.uuid4().hex[:8]}")
        db_session.add_all([org_a, org_b])
        db_session.flush()

        integ_a = Integration(
            organization_id=org_a.id,
            provider="fake",
            status=IntegrationStatus.ACTIVE.value,
            credentials_encrypted=encrypt_credentials("{}", key=test_encryption_key),
        )
        db_session.add(integ_a)
        db_session.flush()

        with pytest.raises(ValueError, match="does not belong to this organization"):
            sync_connector_events(
                db_session,
                organization_id=org_b.id,
                provider="fake",
                credentials={},
                integration_id=integ_a.id,
            )
