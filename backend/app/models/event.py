from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.integration import Integration
    from app.models.organization import Organization


class Event(Base):
    """
    Normalized operational event ingested from external or synthetic connectors.

    Every event belongs strictly to one Organization (multi-tenant isolation)
    and is uniquely identified by (organization_id, source, external_id) to
    guarantee idempotent ingestion across retries and re-syncs.

    Monetary amounts are stored in ``amount_cents`` (integer minor units, exposed
    also as ``amount_minor``) alongside ISO-4217 ``currency`` and
    ``minor_unit_exponent`` so 0-, 2-, and 3-decimal currencies are never conflated.
    """

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("integrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    amount_cents: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    minor_unit_exponent: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    currency: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )
    actor: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="events",
    )
    integration: Mapped["Integration | None"] = relationship("Integration")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "source",
            "external_id",
            name="uq_events_org_source_external_id",
        ),
        Index("ix_events_organization_id", "organization_id"),
        Index("ix_events_org_occurred_at", "organization_id", "occurred_at"),
        Index("ix_events_org_source_type", "organization_id", "source", "event_type"),
        Index(
            "ix_events_org_currency_synthetic",
            "organization_id",
            "currency",
            "is_synthetic",
        ),
    )

    @property
    def amount_minor(self) -> int | None:
        """Canonical minor-unit alias for the legacy ``amount_cents`` column."""
        return self.amount_cents

    def __repr__(self) -> str:
        return (
            f"<Event id={self.id} org_id={self.organization_id} "
            f"source={self.source!r} external_id={self.external_id!r} "
            f"event_type={self.event_type!r}>"
        )
