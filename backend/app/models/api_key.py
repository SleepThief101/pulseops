from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class ApiKey(Base):
    """
    Per-user hashed API key for authenticated MCP access.

    Only ``key_hash`` (SHA-256 hex digest of a cryptographically random token)
    and ``key_prefix`` are persisted. Plaintext tokens are returned once at
    creation and never stored or retrievable afterward.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    key_prefix: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    key_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_api_keys_user_id", "user_id"),
        Index("ix_api_keys_key_prefix", "key_prefix"),
    )

    def __repr__(self) -> str:
        return (
            f"<ApiKey id={self.id} user_id={self.user_id} "
            f"prefix={self.key_prefix!r} revoked={self.revoked_at is not None}>"
        )
