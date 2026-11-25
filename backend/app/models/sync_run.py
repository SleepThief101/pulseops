from __future__ import annotations

from datetime import datetime
import enum
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.integration import Integration
    from app.models.organization import Organization


class SyncRunStatus(str, enum.Enum):
    """Allowed background/synchronous integration sync run states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SyncRun(Base):
    """
    Audit record of a connector sync execution for an organization's integration.
    """

    __tablename__ = "sync_runs"

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
    integration_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("integrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=SyncRunStatus.PENDING.value,
    )
    events_received: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    events_inserted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    events_skipped: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    organization: Mapped["Organization"] = relationship("Organization")
    integration: Mapped["Integration"] = relationship("Integration")

    __table_args__ = (
        Index("ix_sync_runs_organization_id", "organization_id"),
        Index("ix_sync_runs_integration_id", "integration_id"),
        Index("ix_sync_runs_org_started", "organization_id", "started_at"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_sync_runs_status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SyncRun id={self.id} org_id={self.organization_id} "
            f"integration_id={self.integration_id} status={self.status!r}>"
        )
