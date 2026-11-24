from datetime import datetime
import enum
import uuid
from typing import TYPE_CHECKING
from sqlalchemy import String, DateTime, Uuid, ForeignKey, UniqueConstraint, CheckConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class MembershipRole(str, enum.Enum):
    """Allowed organization membership roles."""
    OWNER = "owner"
    MEMBER = "member"
    VIEWER = "viewer"


class Membership(Base):
    """
    Membership represents a user's association with an organization
    and their role within that organization (owner, member, viewer).
    """
    __tablename__ = "memberships"

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
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=MembershipRole.MEMBER.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="memberships",
    )
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="memberships",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_memberships_user_org"),
        CheckConstraint(
            "role IN ('owner', 'member', 'viewer')",
            name="ck_memberships_role",
        ),
        Index("ix_memberships_user_id", "user_id"),
        Index("ix_memberships_organization_id", "organization_id"),
    )

    def __repr__(self) -> str:
        return f"<Membership id={self.id} user_id={self.user_id} org_id={self.organization_id} role={self.role!r}>"
