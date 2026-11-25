from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.organization import Organization


class WebhookDelivery(Base):
    """
    Records processed webhook delivery IDs per organization and provider to
    reject duplicate or replayed deliveries after HMAC verification.
    """

    __tablename__ = "webhook_deliveries"

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
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    delivery_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    payload_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship("Organization")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "delivery_id",
            name="uq_webhook_deliveries_org_provider_delivery",
        ),
        Index("ix_webhook_deliveries_organization_id", "organization_id"),
    )
