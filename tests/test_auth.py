"""Tests for GarminAuth."""

import pytest

from aiogarmin import GarminAuth, GarminAuthError


class TestGarminAuth:
    """Tests for GarminAuth class."""

    async def test_init(self, session):
        """Test auth initialization."""
        auth = GarminAuth(session)
        assert auth.oauth1_token is None
        assert auth.oauth2_token is None
        assert not auth.is_authenticated

    async def test_init_with_tokens(self, session):
        """Test auth initialization with existing tokens."""
        auth = GarminAuth(
            session,
            oauth1_token="token1",
            oauth2_token="token2",
        )
        assert auth.oauth1_token == "token1"
        assert auth.oauth2_token == "token2"
        assert auth.is_authenticated

    async def test_refresh_without_token(self, session):
        """Test refresh fails without OAuth1 token."""
        auth = GarminAuth(session)
        with pytest.raises(GarminAuthError, match="No OAuth1 token"):
            await auth.refresh()
