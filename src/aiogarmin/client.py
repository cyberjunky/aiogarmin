"""Async client for Garmin Connect API."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from .const import (
    ACTIVITIES_BY_DATE_URL,
    ACTIVITIES_URL,
    ACTIVITY_DETAILS_URL,
    ACTIVITY_TYPES_URL,
    BADGES_URL,
    BLOOD_PRESSURE_URL,
    BODY_BATTERY_URL,
    BODY_COMPOSITION_URL,
    DAILY_STEPS_URL,
    DEFAULT_HEADERS,
    DEVICE_ALARMS_URL,
    DEVICES_URL,
    ENDURANCE_SCORE_URL,
    FITNESS_AGE_URL,
    GEAR_DEFAULTS_URL,
    GEAR_STATS_URL,
    GEAR_URL,
    GOALS_URL,
    HILL_SCORE_URL,
    HRV_URL,
    HYDRATION_URL,
    LACTATE_THRESHOLD_URL,
    MENSTRUAL_URL,
    SLEEP_URL,
    STRESS_URL,
    TRAINING_READINESS_URL,
    TRAINING_STATUS_URL,
    USER_PROFILE_URL,
    USER_SUMMARY_URL,
    WORKOUTS_URL,
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
        """Initialize client."""
        self._session = session
        self._auth = auth
        self._profile_cache: UserProfile | None = None

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Make authenticated API request."""
        if not self._auth.oauth2_token:
            raise GarminAuthError("Not authenticated")

        access_token = self._auth.oauth2_token.get("access_token", "")
        if not access_token:
            raise GarminAuthError("No access token in oauth2_token")

        headers = {
            **DEFAULT_HEADERS,
            "Authorization": f"Bearer {access_token}",
        }

        try:
            async with self._session.request(
                method, url, params=params, headers=headers
            ) as response:
                if response.status == 401:
                    _LOGGER.debug("Token expired, refreshing")
                    await self._auth.refresh_tokens()
                    new_token = self._auth.oauth2_token.get("access_token", "")
                    headers["Authorization"] = f"Bearer {new_token}"
                    async with self._session.request(
                        method, url, params=params, headers=headers
                    ) as retry_response:
                        if retry_response.status not in (200, 204):
                            raise GarminAPIError(
                                f"Request failed: {retry_response.status}",
                                retry_response.status,
                            )
                        if retry_response.status == 204:
                            return {}
                        return await retry_response.json()
                elif response.status == 204:
                    _LOGGER.debug("API %s returned 204 No Content", url)
                    return {}
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
        except (GarminAPIError, GarminAuthError):
            raise
        except Exception as err:
            _LOGGER.error("Request to %s failed: %s", url, err)
            raise GarminAPIError(f"Request failed: {err}") from err

    # ========== Core Group ==========

    async def get_user_profile(self) -> UserProfile:
        """Get user profile information."""
        if self._profile_cache:
            return self._profile_cache
        data = await self._request("GET", USER_PROFILE_URL)
        self._profile_cache = UserProfile.model_validate(data)
        return self._profile_cache

    async def get_user_summary(self, target_date: date | None = None) -> UserSummary:
        """Get daily summary for a date."""
        if target_date is None:
            target_date = date.today()

        profile = await self.get_user_profile()
        url = f"{USER_SUMMARY_URL}/{profile.display_name}"
        params = {"calendarDate": target_date.isoformat()}
        data = await self._request("GET", url, params=params)
        return UserSummary.model_validate(data)

    async def get_daily_steps(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Get daily steps for a date range."""
        url = f"{DAILY_STEPS_URL}/{start_date.isoformat()}/{end_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, list) else []

    async def get_body_composition(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get body composition data (weight, BMI, body fat)."""
        if target_date is None:
            target_date = date.today()

        start = (target_date - timedelta(days=30)).isoformat()
        end = target_date.isoformat()
        url = f"{BODY_COMPOSITION_URL}/{start}/{end}"
        data = await self._request("GET", url)
        return data.get("totalAverage", {}) if isinstance(data, dict) else {}

    # ========== Activity Group ==========

    async def get_activities(self, limit: int = 10) -> list[Activity]:
        """Get recent activities."""
        params = {"limit": limit, "start": 0}
        data = await self._request("GET", ACTIVITIES_URL, params=params)
        if isinstance(data, list):
            return [Activity.model_validate(item) for item in data]
        return []

    async def get_activities_by_date(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Get activities in a date range."""
        url = (
            f"{ACTIVITIES_BY_DATE_URL}/{start_date.isoformat()}/{end_date.isoformat()}"
        )
        data = await self._request("GET", url)
        return data if isinstance(data, list) else []

    async def get_activity_details(
        self, activity_id: int, max_chart_size: int = 100, max_poly_size: int = 4000
    ) -> dict[str, Any]:
        """Get detailed activity information including polyline."""
        url = f"{ACTIVITY_DETAILS_URL}/{activity_id}/details"
        params = {"maxChartSize": max_chart_size, "maxPolylineSize": max_poly_size}
        data = await self._request("GET", url, params=params)
        return data if isinstance(data, dict) else {}

    async def get_activity_types(self) -> list[dict[str, Any]]:
        """Get available activity types."""
        data = await self._request("GET", ACTIVITY_TYPES_URL)
        return data if isinstance(data, list) else []

    async def get_workouts(
        self, start: int = 0, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get scheduled workouts."""
        params = {"start": start, "limit": limit}
        data = await self._request("GET", WORKOUTS_URL, params=params)
        if isinstance(data, dict):
            return data.get("workouts", [])
        return data if isinstance(data, list) else []

    # ========== Wellness Group ==========

    async def get_sleep_data(self, target_date: date | None = None) -> SleepData | None:
        """Get sleep data for a date."""
        if target_date is None:
            target_date = date.today()

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
        """Get stress data for a date."""
        if target_date is None:
            target_date = date.today()

        url = f"{STRESS_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        if data:
            return StressData.model_validate(data)
        return None

    async def get_hrv_data(self, target_date: date | None = None) -> HRVData | None:
        """Get HRV data for a date."""
        if target_date is None:
            target_date = date.today()

        url = f"{HRV_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        if data:
            return HRVData.model_validate(data)
        return None

    async def get_body_battery(
        self, target_date: date | None = None
    ) -> list[BodyBattery]:
        """Get body battery data for a date."""
        if target_date is None:
            target_date = date.today()

        url = f"{BODY_BATTERY_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        if isinstance(data, dict):
            readings = data.get("bodyBatteryValuesArray", [])
            return [BodyBattery.model_validate(item) for item in readings]
        return []

    async def get_hydration_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get hydration data for a date."""
        if target_date is None:
            target_date = date.today()

        url = f"{HYDRATION_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    # ========== Fitness Group ==========

    async def get_training_readiness(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get training readiness data."""
        if target_date is None:
            target_date = date.today()

        url = f"{TRAINING_READINESS_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_training_status(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get training status data."""
        if target_date is None:
            target_date = date.today()

        url = f"{TRAINING_STATUS_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_endurance_score(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get endurance score."""
        if target_date is None:
            target_date = date.today()

        url = f"{ENDURANCE_SCORE_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_hill_score(self, target_date: date | None = None) -> dict[str, Any]:
        """Get hill score."""
        if target_date is None:
            target_date = date.today()

        url = f"{HILL_SCORE_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_fitness_age(self, target_date: date | None = None) -> dict[str, Any]:
        """Get fitness age data."""
        if target_date is None:
            target_date = date.today()

        url = f"{FITNESS_AGE_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_lactate_threshold(self) -> dict[str, Any]:
        """Get lactate threshold data."""
        data = await self._request("GET", LACTATE_THRESHOLD_URL)
        return data if isinstance(data, dict) else {}

    # ========== Device Group ==========

    async def get_devices(self) -> list[Device]:
        """Get list of connected Garmin devices."""
        data = await self._request("GET", DEVICES_URL)
        if isinstance(data, list):
            return [Device.model_validate(item) for item in data]
        return []

    async def get_device_alarms(self) -> list[dict[str, Any]]:
        """Get device alarms."""
        data = await self._request("GET", DEVICE_ALARMS_URL)
        return data if isinstance(data, list) else []

    # ========== Goals & Gamification Group ==========

    async def get_goals(self, status: str = "active") -> list[dict[str, Any]]:
        """Get goals by status (active, future, past)."""
        params = {"status": status}
        data = await self._request("GET", GOALS_URL, params=params)
        return data if isinstance(data, list) else []

    async def get_earned_badges(self) -> list[dict[str, Any]]:
        """Get earned badges."""
        data = await self._request("GET", BADGES_URL)
        return data if isinstance(data, list) else []

    # ========== Gear Group ==========

    async def get_gear(self, user_profile_id: int) -> list[dict[str, Any]]:
        """Get user gear."""
        url = f"{GEAR_URL}/{user_profile_id}"
        data = await self._request("GET", url)
        return data if isinstance(data, list) else []

    async def get_gear_stats(self, gear_uuid: str) -> dict[str, Any]:
        """Get gear statistics."""
        url = f"{GEAR_STATS_URL}/{gear_uuid}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_gear_defaults(self, user_profile_id: int) -> dict[str, Any]:
        """Get default gear settings."""
        url = f"{GEAR_DEFAULTS_URL}/{user_profile_id}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    # ========== Health Group ==========

    async def get_blood_pressure(
        self, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """Get blood pressure data for a date range."""
        url = f"{BLOOD_PRESSURE_URL}/{start_date.isoformat()}/{end_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_menstrual_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get menstrual cycle data."""
        if target_date is None:
            target_date = date.today()

        url = f"{MENSTRUAL_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}
