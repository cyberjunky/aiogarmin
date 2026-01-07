"""Pure async authentication for Garmin Connect using aiohttp."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from .exceptions import GarminAuthError, GarminMFARequired
from .models import AuthResult

if TYPE_CHECKING:
    import aiohttp

_LOGGER = logging.getLogger(__name__)

# Regex patterns
CSRF_RE = re.compile(r'name="_csrf"\s+value="(.+?)"')
TITLE_RE = re.compile(r"<title>(.+?)</title>")
TICKET_RE = re.compile(r'embed\?ticket=([^"]+)"')

# OAuth consumer keys URL
OAUTH_CONSUMER_URL = "https://thegarth.s3.amazonaws.com/oauth_consumer.json"

# User agent (mimics Garmin mobile app)
USER_AGENT = "com.garmin.android.apps.connectmobile"


class GarminAuth:
    """Handle Garmin SSO authentication using aiohttp."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        oauth1_token: dict | None = None,
        oauth2_token: dict | None = None,
        domain: str = "garmin.com",
    ) -> None:
        """Initialize auth handler.

        Args:
            session: aiohttp ClientSession (HA websession)
            oauth1_token: Stored OAuth1 token dict
            oauth2_token: Stored OAuth2 token dict
            domain: Garmin domain (garmin.com or garmin.cn)
        """
        self._session = session
        self._domain = domain
        self._oauth1_token = oauth1_token
        self._oauth2_token = oauth2_token
        self._last_response_text: str = ""
        self._consumer_key: str | None = None
        self._consumer_secret: str | None = None

    @property
    def oauth1_token(self) -> dict | None:
        """Return OAuth1 token."""
        return self._oauth1_token

    @property
    def oauth2_token(self) -> dict | None:
        """Return OAuth2 token."""
        return self._oauth2_token

    @property
    def is_authenticated(self) -> bool:
        """Check if we have valid tokens."""
        return self._oauth2_token is not None

    def _get_headers(self, referrer: str | None = None) -> dict[str, str]:
        """Get request headers."""
        headers = {"User-Agent": USER_AGENT}
        if referrer:
            headers["Referer"] = referrer
        return headers

    async def get_auth_headers(self) -> dict[str, str]:
        """Get authenticated request headers with Bearer token.

        Returns:
            Headers dict with Authorization Bearer token
        """
        if not self._oauth2_token:
            raise GarminAuthError("No OAuth2 token - authentication required")

        access_token = self._oauth2_token.get("access_token", "")
        if not access_token:
            raise GarminAuthError("No access token in OAuth2 token")

        return {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": USER_AGENT,
        }

    async def refresh(self) -> AuthResult:
        """Refresh OAuth2 token. Alias for refresh_tokens()."""
        return await self.refresh_tokens()

    async def _fetch_consumer_keys(self) -> None:
        """Fetch OAuth consumer keys from S3."""
        if self._consumer_key and self._consumer_secret:
            return

        async with self._session.get(OAUTH_CONSUMER_URL) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._consumer_key = data["consumer_key"]
            self._consumer_secret = data["consumer_secret"]

    async def login(self, username: str, password: str) -> AuthResult:
        """Login with username and password.

        Args:
            username: Garmin account email
            password: Garmin account password

        Returns:
            AuthResult with tokens on success

        Raises:
            GarminMFARequired: If MFA verification is needed
            GarminAuthError: If authentication fails
        """
        _LOGGER.debug("Starting login for %s", username)

        sso = f"https://sso.{self._domain}/sso"
        sso_embed = f"{sso}/embed"

        embed_params = {
            "id": "gauth-widget",
            "embedWidget": "true",
            "gauthHost": sso,
        }

        signin_params = {
            **embed_params,
            "gauthHost": sso_embed,
            "service": sso_embed,
            "source": sso_embed,
            "redirectAfterAccountLoginUrl": sso_embed,
            "redirectAfterAccountCreationUrl": sso_embed,
        }

        try:
            # Step 1: Set cookies
            embed_url = f"{sso}/embed"
            async with self._session.get(
                embed_url,
                params=embed_params,
                headers=self._get_headers(),
            ) as resp:
                await resp.text()

            # Step 2: Get CSRF token
            signin_url = f"{sso}/signin"
            async with self._session.get(
                signin_url,
                params=signin_params,
                headers=self._get_headers(embed_url),
            ) as resp:
                self._last_response_text = await resp.text()
                csrf_token = self._extract_csrf(self._last_response_text)

            if not csrf_token:
                raise GarminAuthError("Could not extract CSRF token")

            # Step 3: Submit credentials
            login_data = {
                "username": username,
                "password": password,
                "embed": "true",
                "_csrf": csrf_token,
            }

            async with self._session.post(
                signin_url,
                params=signin_params,
                data=login_data,
                headers=self._get_headers(signin_url),
            ) as resp:
                self._last_response_text = await resp.text()
                title = self._extract_title(self._last_response_text)

            # Check for MFA
            if title and "MFA" in title:
                _LOGGER.debug("MFA required")
                # Store state for MFA completion - including CSRF for retry
                self._signin_params = signin_params
                self._mfa_csrf_token = self._extract_csrf(self._last_response_text)
                raise GarminMFARequired("mfa_required")

            # Check for success
            if title != "Success":
                raise GarminAuthError(f"Login failed: {title}")

            # Complete login
            return await self._complete_login()

        except GarminMFARequired:
            raise
        except GarminAuthError:
            raise
        except Exception as err:
            _LOGGER.exception("Login failed")
            raise GarminAuthError(f"Login failed: {err}") from err

    async def complete_mfa(self, mfa_code: str) -> AuthResult:
        """Complete MFA verification.

        Args:
            mfa_code: The MFA code from authenticator app

        Returns:
            AuthResult with tokens on success
        """
        if not hasattr(self, "_signin_params"):
            raise GarminAuthError("No MFA session - call login first")

        _LOGGER.debug("Completing MFA verification")

        try:
            # Try to extract new CSRF from last response, fallback to stored token
            csrf_token = self._extract_csrf(self._last_response_text)
            if not csrf_token:
                csrf_token = getattr(self, "_mfa_csrf_token", None)
            if not csrf_token:
                # No token available - session truly expired
                self._clear_mfa_session()
                raise GarminAuthError("MFA session expired - please restart login")

            # Build referrer URL (the MFA page we're on)
            sso_url = f"https://sso.{self._domain}/sso/signin"
            mfa_url = f"https://sso.{self._domain}/sso/verifyMFA/loginEnterMfaCode"
            mfa_data = {
                "mfa-code": mfa_code,
                "embed": "true",
                "_csrf": csrf_token,
                "fromPage": "setupEnterMfaCode",
            }

            headers = {
                "User-Agent": USER_AGENT,
                "Referer": sso_url,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": f"https://sso.{self._domain}",
            }

            async with self._session.post(
                mfa_url,
                params=self._signin_params,
                data=mfa_data,
                headers=headers,
            ) as resp:
                self._last_response_text = await resp.text()

            # Check for success - either title says Success OR we have a ticket
            title = self._extract_title(self._last_response_text)
            ticket = self._extract_ticket(self._last_response_text)

            _LOGGER.debug("MFA title: %s, ticket found: %s", title, bool(ticket))

            if ticket:
                # We have a ticket, MFA succeeded
                return await self._complete_login()

            if title == "Success":
                return await self._complete_login()

            # Try to extract error message from response
            error_msg = "Invalid MFA code"
            error_match = re.search(
                r'class="[^"]*error[^"]*"[^>]*>([^<]+)<',
                self._last_response_text,
                re.IGNORECASE,
            )
            if error_match:
                error_msg = error_match.group(1).strip()
                _LOGGER.debug("MFA error from page: %s", error_msg)

            raise GarminAuthError(error_msg)

        except GarminAuthError:
            raise
        except Exception as err:
            _LOGGER.exception("MFA verification failed")
            raise GarminAuthError(f"MFA failed: {err}") from err

    async def _complete_login(self) -> AuthResult:
        """Complete login after successful auth - get OAuth tokens."""
        # Extract ticket from response
        ticket = self._extract_ticket(self._last_response_text)
        if not ticket:
            raise GarminAuthError("Could not extract ticket from response")

        # Fetch consumer keys
        await self._fetch_consumer_keys()

        # Get OAuth1 token
        self._oauth1_token = await self._get_oauth1_token(ticket)

        # Exchange for OAuth2 token
        self._oauth2_token = await self._exchange_oauth1_for_oauth2()

        return AuthResult(
            success=True,
            oauth1_token=self._oauth1_token,
            oauth2_token=self._oauth2_token,
        )

    async def _get_oauth1_token(self, ticket: str) -> dict:
        """Get OAuth1 token using ticket."""
        from oauthlib.oauth1 import Client as OAuth1Client

        base_url = f"https://connectapi.{self._domain}/oauth-service/oauth"
        login_url = f"https://sso.{self._domain}/sso/embed"
        url = f"{base_url}/preauthorized?ticket={ticket}&login-url={login_url}&accepts-mfa-tokens=true"

        # Create OAuth1 signature
        oauth_client = OAuth1Client(
            self._consumer_key,
            client_secret=self._consumer_secret,
        )

        uri, headers, _ = oauth_client.sign(url, http_method="GET")

        async with self._session.get(
            uri,
            headers={**headers, "User-Agent": USER_AGENT},
        ) as resp:
            resp.raise_for_status()
            text = await resp.text()
            parsed = parse_qs(text)
            token = {k: v[0] for k, v in parsed.items()}
            token["domain"] = self._domain
            return token

    async def _exchange_oauth1_for_oauth2(self) -> dict:
        """Exchange OAuth1 token for OAuth2 token."""
        from oauthlib.oauth1 import Client as OAuth1Client

        if not self._oauth1_token:
            raise GarminAuthError("No OAuth1 token")

        base_url = f"https://connectapi.{self._domain}/oauth-service/oauth"
        url = f"{base_url}/exchange/user/2.0"

        # Create OAuth1 signature with token
        oauth_client = OAuth1Client(
            self._consumer_key,
            client_secret=self._consumer_secret,
            resource_owner_key=self._oauth1_token.get("oauth_token"),
            resource_owner_secret=self._oauth1_token.get("oauth_token_secret"),
        )

        # Prepare data (include MFA token if present)
        data = ""
        if self._oauth1_token.get("mfa_token"):
            data = f"mfa_token={self._oauth1_token['mfa_token']}"

        uri, headers, body = oauth_client.sign(
            url,
            http_method="POST",
            body=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        async with self._session.post(
            uri,
            headers={**headers, "User-Agent": USER_AGENT},
            data=body,
        ) as resp:
            resp.raise_for_status()
            token = await resp.json()

            # Add expiration timestamps
            token["expires_at"] = int(time.time() + token.get("expires_in", 3600))
            token["refresh_token_expires_at"] = int(
                time.time() + token.get("refresh_token_expires_in", 86400)
            )
            return token

    async def refresh_tokens(self) -> AuthResult:
        """Refresh OAuth2 token using OAuth1 token."""
        if not self._oauth1_token:
            raise GarminAuthError("No OAuth1 token - full login required")

        _LOGGER.debug("Refreshing OAuth2 token")

        try:
            await self._fetch_consumer_keys()
            self._oauth2_token = await self._exchange_oauth1_for_oauth2()

            return AuthResult(
                success=True,
                oauth1_token=self._oauth1_token,
                oauth2_token=self._oauth2_token,
            )

        except Exception as err:
            _LOGGER.exception("Token refresh failed")
            raise GarminAuthError(f"Token refresh failed: {err}") from err

    def _extract_csrf(self, html: str) -> str | None:
        """Extract CSRF token from HTML."""
        match = CSRF_RE.search(html)
        return match.group(1) if match else None

    def _extract_title(self, html: str) -> str | None:
        """Extract title from HTML."""
        match = TITLE_RE.search(html)
        return match.group(1) if match else None

    def _extract_ticket(self, html: str) -> str | None:
        """Extract ticket from response HTML."""
        match = TICKET_RE.search(html)
        return match.group(1) if match else None

    def _clear_mfa_session(self) -> None:
        """Clear MFA session state - forces restart of login flow."""
        if hasattr(self, "_signin_params"):
            del self._signin_params
        self._last_response_text = ""
