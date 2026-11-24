from datetime import datetime
import enum
import uuid
from typing import TYPE_CHECKING
from sqlalchemy import String, Text, DateTime, Uuid, ForeignKey, CheckConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.organization import Organization


class IntegrationStatus(str, enum.Enum):
    """Allowed integration lifecycle statuses."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class Integration(Base):
    """
    Integration stores external service connection configurations and
    encrypted credentials belonging to an organization.
    """
    __tablename__ = "integrations"

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
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=IntegrationStatus.PENDING.value,
    )
    credentials_encrypted: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="integrations",
    )

    __table_args__ = (
        Index("ix_integrations_organization_id", "organization_id"),
        Index("ix_integrations_org_provider", "organization_id", "provider"),
        CheckConstraint(
            "status IN ('active', 'inactive', 'pending', 'error', 'disconnected')",
            name="ck_integrations_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<Integration id={self.id} org_id={self.organization_id} provider={self.provider!r} status={self.status!r}>"
