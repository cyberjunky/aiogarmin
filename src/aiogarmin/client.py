"""Async client for Garmin Connect API."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from .const import (
    ACTIVITIES_URL,
    ACTIVITY_DETAILS_URL,
    BODY_BATTERY_URL,
    DEFAULT_HEADERS,
    DEVICES_URL,
    HRV_URL,
    SLEEP_URL,
    STRESS_URL,
    USER_PROFILE_URL,
    USER_SUMMARY_URL,
)
from .exceptions import GarminAPIError, GarminAuthError
from .models import (
    Activity,
    BodyBattery,
    Device,
    HRVData,
    SleepData,
    StressData,
    UserProfile,
    UserSummary,
)

if TYPE_CHECKING:
    import aiohttp

    from .auth import GarminAuth

_LOGGER = logging.getLogger(__name__)


class GarminClient:
    """Async Garmin Connect API client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: GarminAuth,
    ) -> None:
        """Initialize client.

        Args:
            session: aiohttp ClientSession (can be HA websession)
            auth: GarminAuth instance with tokens
        """
        self._session = session
        self._auth = auth

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated API request.

        Args:
            method: HTTP method
            url: API URL
            params: Query parameters

        Returns:
            JSON response as dict

        Raises:
            GarminAuthError: If not authenticated
            GarminAPIError: If request fails
        """
        if not self._auth.oauth2_token:
            raise GarminAuthError("Not authenticated")

        # Extract access token from the oauth2_token dict
        access_token = self._auth.oauth2_token.get("access_token", "")
        if not access_token:
            raise GarminAuthError("No access token in oauth2_token")

        headers = {
            **DEFAULT_HEADERS,
            "Authorization": f"Bearer {access_token}",
        }

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                headers=headers,
            ) as response:
                if response.status == 401:
                    # Token expired, try refresh
                    _LOGGER.debug("Token expired, refreshing")
                    await self._auth.refresh_tokens()
                    # Retry with new token
                    new_token = self._auth.oauth2_token.get("access_token", "")
                    headers["Authorization"] = f"Bearer {new_token}"
                    async with self._session.request(
                        method,
                        url,
                        params=params,
                        headers=headers,
                    ) as retry_response:
                        if retry_response.status != 200:
                            raise GarminAPIError(
                                f"Request failed: {retry_response.status}",
                                retry_response.status,
                            )
                        return await retry_response.json()
                elif response.status != 200:
                    text = await response.text()
                    _LOGGER.warning(
                        "API %s returned %d: %s", url, response.status, text[:200]
                    )
                    raise GarminAPIError(
                        f"Request to {url} failed: {response.status}",
                        response.status,
                    )
                result = await response.json()
                _LOGGER.debug("API response from %s: %s", url, str(result)[:500])
                return result
        except GarminAPIError:
            raise
        except GarminAuthError:
            raise
        except Exception as err:
            _LOGGER.error("Request to %s failed: %s", url, err)
            raise GarminAPIError(f"Request failed: {err}") from err

    async def get_user_profile(self) -> UserProfile:
        """Get user profile information."""
        data = await self._request("GET", USER_PROFILE_URL)
        return UserProfile.model_validate(data)

    async def get_user_summary(self, target_date: date | None = None) -> UserSummary:
        """Get daily summary for a date.

        Args:
            target_date: Date to get summary for (default: today)
        """
        if target_date is None:
            target_date = date.today()

        # Get display name first
        profile = await self.get_user_profile()
        url = f"{USER_SUMMARY_URL}/{profile.display_name}"
        params = {"calendarDate": target_date.isoformat()}

        data = await self._request("GET", url, params=params)
        return UserSummary.model_validate(data)

    async def get_activities(self, limit: int = 10) -> list[Activity]:
        """Get recent activities.

        Args:
            limit: Maximum number of activities to return
        """
        params = {"limit": limit, "start": 0}
        data = await self._request("GET", ACTIVITIES_URL, params=params)
        return [Activity.model_validate(item) for item in data]

    async def get_activity_details(self, activity_id: int) -> dict[str, Any]:
        """Get detailed information for an activity.

        Args:
            activity_id: Activity ID to fetch
        """
        url = f"{ACTIVITY_DETAILS_URL}/{activity_id}/details"
        return await self._request("GET", url)

    async def get_body_battery(
        self, target_date: date | None = None
    ) -> list[BodyBattery]:
        """Get body battery data for a date.

        Args:
            target_date: Date to get data for (default: today)
        """
        if target_date is None:
            target_date = date.today()

        url = f"{BODY_BATTERY_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        readings = data.get("bodyBatteryValuesArray", [])
        return [BodyBattery.model_validate(item) for item in readings]

    async def get_sleep_data(self, target_date: date | None = None) -> SleepData | None:
        """Get sleep data for a date.

        Args:
            target_date: Date to get data for (default: today)
        """
        if target_date is None:
            target_date = date.today()

        # Sleep endpoint uses displayName in URL, date as query param
        profile = await self.get_user_profile()
        url = f"{SLEEP_URL}/{profile.display_name}"
        params = {"date": target_date.isoformat(), "nonSleepBufferMinutes": 60}
        data = await self._request("GET", url, params=params)
        if data:
            return SleepData.model_validate(data)
        return None

    async def get_stress_data(
        self, target_date: date | None = None
    ) -> StressData | None:
        """Get stress data for a date.

        Args:
            target_date: Date to get data for (default: today)
        """
        if target_date is None:
            target_date = date.today()

        url = f"{STRESS_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        if data:
            return StressData.model_validate(data)
        return None

    async def get_hrv_data(self, target_date: date | None = None) -> HRVData | None:
        """Get HRV data for a date.

        Args:
            target_date: Date to get data for (default: today)
        """
        if target_date is None:
            target_date = date.today()

        url = f"{HRV_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        if data:
            return HRVData.model_validate(data)
        return None

    async def get_devices(self) -> list[Device]:
        """Get list of connected Garmin devices."""
        data = await self._request("GET", DEVICES_URL)
        return [Device.model_validate(item) for item in data]
