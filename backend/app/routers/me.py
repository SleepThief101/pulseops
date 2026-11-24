"""
GET /me — authenticated user profile endpoint.

Mounted at the root level (no /auth prefix) to match the specification.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.models.user import User
from app.schemas.auth import UserProfile

me_router = APIRouter(tags=["Profile"])


@me_router.get(
    "/me",
    response_model=UserProfile,
    summary="Return the authenticated user's profile",
)
def me(current_user: User = Depends(get_current_user)) -> UserProfile:
    """
    Return the profile of the currently authenticated user.

    Requires a valid Bearer JWT in the Authorization header.
    Password hash is never included in the response.
    """
    return UserProfile.model_validate(current_user)
