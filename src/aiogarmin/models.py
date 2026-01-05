"""Pydantic models for Garmin Connect API responses."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GarminModel(BaseModel):
    """Base model that ignores unknown fields."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AuthResult(BaseModel):
    """Result of authentication attempt."""

    success: bool
    oauth1_token: dict | None = None
    oauth2_token: dict | None = None
    display_name: str | None = None
    user_id: str | None = None


class UserProfile(GarminModel):
    """User profile information.

    Used for caching user profile data, primarily to get display_name
    which is used in API URLs.
    """

    id: int
    display_name: str = Field(alias="displayName")
    profile_image_url: str | None = Field(default=None, alias="profileImageUrlMedium")
