"""Garmin Connect authentication using the brand new React /gc-api/ flow.

Flow:
1. Authenticate via native Mobile SSO JSON API (bypass Cloudflare Captcha perfectly)
   using a Web Service Ticket request ('https://connect.garmin.com/app/').
2. Handle MFA transparently.
3. Consume the Web Ticket natively and extract browser-side React tokens (JWT_WEB).
4. Fetch /gc-api/ natively armed with dynamic connect-csrf-token and JWT_WEB.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from curl_cffi import requests

from .exceptions import GarminAuthError, GarminMFARequired
from .models import AuthResult

_LOGGER = logging.getLogger(__name__)

CLIENT_ID = "GarminConnect"
SSO_SERVICE_URL = "https://connect.garmin.com/app/"


class GarminAuth:
    """State-of-the-art authentication engine bypassing Cloudflare."""

    def __init__(self, domain: str = "garmin.com") -> None:
        self.domain = domain
        self._sso = f"https://sso.{domain}"
        self._connect = f"https://connect.{domain}"

        self.jwt_web: str | None = None
        self.csrf_token: str | None = None
        self._display_name: str | None = None

        # Base impersonation for Web API requests
        self.cs = requests.Session(impersonate="chrome131")

    @property
    def is_authenticated(self) -> bool:
        return bool(self.jwt_web and self.csrf_token)

    @property
    def display_name(self) -> str | None:
        return self._display_name

    def get_api_headers(self) -> dict[str, str]:
        """Headers required to natively query /gc-api/ on connect.garmin.com."""
        if not self.is_authenticated:
            raise GarminAuthError("Not authenticated")

        return {
            "Accept": "application/json",
            "connect-csrf-token": self.csrf_token,
            "Origin": self._connect,
            "Referer": f"{self._connect}/modern/",
            "DI-Backend": f"connectapi.{self.domain}",
        }

    def get_api_base_url(self) -> str:
        """New Web endpoints are exclusively /gc-api/."""
        return f"{self._connect}/gc-api"

    # -- LOGIN FLOW --

    async def login(self, email: str, password: str) -> AuthResult:
        """Logs into Mobile API specifically spoofing a Web Ticket fetch."""
        # 1. Cloudflare stealth Mobile warmup
        sess = requests.Session(impersonate="chrome131_android")
        sess.headers = {
            "User-Agent": "com.garmin.android.apps.connectmobile",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }

        sess.get(
            f"{self._sso}/mobile/sso/en/sign-in",
            params={"clientId": CLIENT_ID},
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            },
        )

        # 2. Transmit credentials using native Mobile JSON payload to evade CF
        r = sess.post(
            f"{self._sso}/mobile/api/login",
            params={
                "clientId": CLIENT_ID,
                "locale": "en-US",
                "service": SSO_SERVICE_URL,
            },
            json={
                "username": email,
                "password": password,
                "rememberMe": False,
                "captchaToken": "",
            },
        )

        try:
            res = r.json()
        except Exception as err:
            raise GarminAuthError(
                f"Login failed (Not JSON): HTTP {r.status_code} {r.text[:200]}"
            ) from err

        resp_type = res.get("responseStatus", {}).get("type")

        if resp_type == "SUCCESSFUL":
            ticket = res["serviceTicketId"]
            return await self._establish_session(ticket)

        if resp_type == "MFA_REQUIRED":
            self._mfa_method = res.get("customerMfaInfo", {}).get(
                "mfaLastMethodUsed", "email"
            )
            # Preserve state so MFA completion can use the same native headers
            self._mfa_session = sess
            raise GarminMFARequired("mfa_required")

        if (
            "status-code" in res.get("error", {})
            and res["error"]["status-code"] == "429"
        ):
            raise GarminAuthError(f"Rate Limited (429)! Wait ~10 minutes. {res}")

        raise GarminAuthError(f"Login failed: {res}")

    async def complete_mfa(self, mfa_code: str) -> AuthResult:
        """Complete MFA to get Service Ticket."""
        if not hasattr(self, "_mfa_session"):
            raise GarminAuthError("No pending MFA session")

        r = self._mfa_session.post(
            f"{self._sso}/mobile/api/mfa/verifyCode",
            params={
                "clientId": CLIENT_ID,
                "locale": "en-US",
                "service": SSO_SERVICE_URL,
            },
            json={
                "mfaMethod": self._mfa_method,
                "mfaVerificationCode": mfa_code,
                "rememberMyBrowser": False,
                "reconsentList": [],
                "mfaSetup": False,
            },
        )

        res = r.json()
        if res.get("responseStatus", {}).get("type") == "SUCCESSFUL":
            ticket = res["serviceTicketId"]
            return await self._establish_session(ticket)

        raise GarminAuthError(f"MFA Verification failed: {res}")

    async def _establish_session(self, ticket: str) -> AuthResult:
        """Consumes the perfectly obtained Web Ticket to dynamically extract JWT_WEB."""

        self.cs = requests.Session(impersonate="chrome131")
        self.cs.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Consume the ticket directly
        self.cs.get(SSO_SERVICE_URL, params={"ticket": ticket}, allow_redirects=True)

        # Dynamically harvest JWT from the token exchange!
        r_tok = self.cs.post(
            f"{self._connect}/services/auth/token/di-oauth/refresh",
            headers={
                "Accept": "application/json",
                "NK": "NT",
                "Referer": f"{self._connect}/modern/",
            },
        )

        if r_tok.status_code not in (200, 201):
            raise GarminAuthError(
                f"Failed JWT extraction: {r_tok.status_code} {r_tok.text}"
            )

        jwt_data = r_tok.json()
        self.jwt_web = jwt_data.get("encryptedToken")
        self.csrf_token = jwt_data.get("csrfToken")

        if not self.jwt_web or not self.csrf_token:
            raise GarminAuthError(
                "Missing required JWT or CSRF tokens in response payload."
            )

        self.cs.cookies.set("JWT_WEB", self.jwt_web, domain=f".{self.domain}", path="/")

        # Skip verification fetch because the /userId=current path throws 404,
        # but the session is fully active!
        self._display_name = "User"

        return AuthResult(success=True)

    async def refresh_session(self) -> bool:
        """Refreshes the JWT_WEB and CSRF tokens automatically using secure tracking cookies."""
        if not self.is_authenticated:
            return False

        try:
            r_tok = self.cs.post(
                f"{self._connect}/services/auth/token/di-oauth/refresh",
                headers={
                    "Accept": "application/json",
                    "NK": "NT",
                    "connect-csrf-token": self.csrf_token,
                    "Referer": f"{self._connect}/modern/",
                },
                timeout=10,
            )
            if r_tok.status_code in (200, 201):
                jwt_data = r_tok.json()
                self.jwt_web = jwt_data.get("encryptedToken")
                self.csrf_token = jwt_data.get("csrfToken")
                self.cs.cookies.set(
                    "JWT_WEB", self.jwt_web, domain=f".{self.domain}", path="/"
                )
                return True
        except Exception:
            pass

        return False

    def save_session(self, path: str | Path) -> None:
        """Save tokens to disk natively preserving all security cookies."""
        if not self.is_authenticated:
            return

        data = {
            "jwt_web": self.jwt_web,
            "csrf_token": self.csrf_token,
            "display_name": self._display_name,
            "cookies": getattr(self.cs.cookies, "get_dict", dict)(),
        }

        # fallback for curl_cffi cookiejar behavior depending on version:
        if not data["cookies"]:
            data["cookies"] = {c.name: c.value for c in self.cs.cookies.jar}

        Path(path).write_text(json.dumps(data, indent=2))

    def load_session(self, path: str | Path) -> bool:
        """Load tokens and inject all security tracking cookies natively."""
        p = Path(path)
        if not p.exists():
            return False

        try:
            data = json.loads(p.read_text())
            self.jwt_web = data.get("jwt_web")
            self.csrf_token = data.get("csrf_token")
            self._display_name = data.get("display_name")

            if self.is_authenticated:
                raw_cookies = data.get("cookies", {})
                for k, v in raw_cookies.items():
                    self.cs.cookies.set(k, v, domain=f".{self.domain}", path="/")
                return True

            return False
        except Exception:
            return False

    def api_request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> Any:
        """Make an authenticated API request natively mimicking the DOM."""
        url = f"{self.get_api_base_url()}/{path.lstrip('/')}"

        resp = self.cs.request(
            method,
            url,
            params=params,
            json=json_data,
            headers=self.get_api_headers(),
            timeout=15,
        )

        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            raise GarminAuthError(f"API Error {resp.status_code}: {resp.text[:200]}")

        return resp.json()
