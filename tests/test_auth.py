"""Tests for GarminAuth."""

import pytest

from aiogarmin import GarminAuth, GarminAuthError
from aiogarmin.const import GARMIN_SSO_SIGNIN, OAUTH1_URL, OAUTH2_URL


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

    async def test_login_success(self, session, mock_aioresponse):
        """Test successful login without MFA."""
        # Mock SSO page
        mock_aioresponse.get(
            GARMIN_SSO_SIGNIN,
            body='<input name="_csrf" value="csrf123">',
        )
        # Mock login POST - redirect with ticket
        mock_aioresponse.post(
            GARMIN_SSO_SIGNIN,
            status=302,
            headers={"Location": "https://connect.garmin.com?ticket=abc123"},
        )
        # Mock OAuth1 exchange
        mock_aioresponse.get(
            OAUTH1_URL,
            payload={"oauth_token": "oauth1_token_value"},
        )
        # Mock OAuth2 exchange
        mock_aioresponse.post(
            OAUTH2_URL,
            payload={"access_token": "oauth2_token_value"},
        )

        auth = GarminAuth(session)
        result = await auth.login("user@example.com", "password")

        assert result.success
        assert result.oauth1_token == "oauth1_token_value"
        assert result.oauth2_token == "oauth2_token_value"

    async def test_login_invalid_credentials(self, session, mock_aioresponse):
        """Test login with invalid credentials."""
        mock_aioresponse.get(
            GARMIN_SSO_SIGNIN,
            body='<input name="_csrf" value="csrf123">',
        )
        mock_aioresponse.post(
            GARMIN_SSO_SIGNIN,
            status=200,
            body="<html>Invalid credentials</html>",
        )

        auth = GarminAuth(session)
        with pytest.raises(GarminAuthError):
            await auth.login("user@example.com", "wrong_password")

    async def test_refresh_without_token(self, session):
        """Test refresh fails without OAuth1 token."""
        auth = GarminAuth(session)
        with pytest.raises(GarminAuthError, match="No OAuth1 token"):
            await auth.refresh_tokens()

    async def test_refresh_success(self, session, mock_aioresponse):
        """Test successful token refresh."""
        mock_aioresponse.post(
            OAUTH2_URL,
            payload={"access_token": "new_oauth2_token"},
        )

        auth = GarminAuth(session, oauth1_token="oauth1_token")
        result = await auth.refresh_tokens()

        assert result.success
        assert result.oauth2_token == "new_oauth2_token"
