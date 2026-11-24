from datetime import datetime
import uuid
from typing import TYPE_CHECKING
from sqlalchemy import String, DateTime, Uuid, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.membership import Membership


class User(Base):
    """
    User represents an authenticated principal across organizations.
    Email uniqueness is enforced case-insensitively.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    memberships: Mapped[list["Membership"]] = relationship(
        "Membership",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_users_email_lower", func.lower(email), unique=True),
    )

    @validates("email")
    def validate_email(self, key: str, address: str) -> str:
        """Normalize email addresses to lowercase to prevent casing duplicates."""
        if address:
            return address.strip().lower()
        return address

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
