"""Async client for Garmin Connect API."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, timedelta
from typing import TYPE_CHECKING, Any

from .const import (
    ACTIVITIES_URL,
    ACTIVITY_CREATE_URL,
    ACTIVITY_DETAILS_URL,
    BADGES_URL,
    BLOOD_PRESSURE_SET_URL,
    BLOOD_PRESSURE_URL,
    BODY_COMPOSITION_URL,
    DAILY_STEPS_URL,
    DEFAULT_HEADERS,
    DEVICES_URL,
    ENDURANCE_SCORE_URL,
    FITNESS_AGE_URL,
    GARMIN_CN_CONNECT_API,
    GARMIN_CONNECT_API,
    GEAR_DEFAULTS_URL,
    GEAR_LINK_URL,
    GEAR_STATS_URL,
    GEAR_URL,
    GOALS_URL,
    HILL_SCORE_URL,
    HRV_URL,
    HYDRATION_URL,
    LACTATE_THRESHOLD_URL,
    MENSTRUAL_CALENDAR_URL,
    MENSTRUAL_URL,
    SLEEP_URL,
    TRAINING_READINESS_URL,
    TRAINING_STATUS_URL,
    UPLOAD_URL,
    USER_PROFILE_URL,
    USER_SUMMARY_URL,
    WORKOUTS_URL,
)
from .exceptions import GarminAPIError, GarminAuthError
from .models import UserProfile

if TYPE_CHECKING:
    import aiohttp

    from .auth import GarminAuth

_LOGGER = logging.getLogger(__name__)

# Essential keys to keep when trimming activity data
# This reduces ~3KB per activity to ~500 bytes
ACTIVITY_ESSENTIAL_KEYS = {
    # Identity
    "activityId",
    "activityName",
    # Time
    "startTimeLocal",
    "startTimeGMT",
    "duration",
    "movingDuration",
    "elapsedDuration",
    # Distance/Speed
    "distance",
    "averageSpeed",
    "maxSpeed",
    # Location
    "locationName",
    "startLatitude",
    "startLongitude",
    "endLatitude",
    "endLongitude",
    # Heart Rate
    "averageHR",
    "maxHR",
    # Stats
    "calories",
    "steps",
    "elevationGain",
    "elevationLoss",
    # Cadence
    "averageRunningCadenceInStepsPerMinute",
    "maxRunningCadenceInStepsPerMinute",
    # Type (simplified)
    "activityType",
    # Polyline/GPS (for map display)
    "hasPolyline",
    "polyline",
}


def _trim_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """Trim activity to essential fields only to reduce data size."""
    trimmed = {k: v for k, v in activity.items() if k in ACTIVITY_ESSENTIAL_KEYS}
    # Simplify activityType to just typeKey
    if "activityType" in trimmed and isinstance(trimmed["activityType"], dict):
        trimmed["activityType"] = trimmed["activityType"].get("typeKey", "unknown")
    return trimmed


def _seconds_to_minutes(seconds: int | float | None) -> float | None:
    """Convert seconds to minutes, rounded to 2 decimal places."""
    if seconds is None:
        return None
    return round(seconds / 60, 2)


def _grams_to_kg(grams: int | float | None) -> float | None:
    """Convert grams to kilograms, rounded to 2 decimal places."""
    if grams is None:
        return None
    return round(grams / 1000, 2)


def _add_computed_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Add pre-computed fields for common unit conversions and nested extractions.

    This simplifies the Home Assistant integration by providing ready-to-use values.
    """
    result = dict(data)

    # === Sleep: seconds → minutes ===
    for key in [
        "sleepTimeSeconds",
        "deepSleepSeconds",
        "lightSleepSeconds",
        "remSleepSeconds",
        "awakeSleepSeconds",
        "sleepingSeconds",
        "measurableAsleepDuration",
        "measurableAwakeDuration",
    ]:
        if key in result:
            minutes_key = key.replace("Seconds", "Minutes").replace(
                "Duration", "DurationMinutes"
            )
            result[minutes_key] = _seconds_to_minutes(result.get(key, 0))

    # === Stress: seconds → minutes ===
    for key in [
        "totalStressDuration",
        "restStressDuration",
        "activityStressDuration",
        "lowStressDuration",
        "mediumStressDuration",
        "highStressDuration",
        "uncategorizedStressDuration",
        "stressDuration",
    ]:
        if key in result:
            minutes_key = key.replace("Duration", "Minutes")
            result[minutes_key] = _seconds_to_minutes(result.get(key, 0))

    # === Activity: seconds → minutes ===
    for key in ["activeSeconds", "highlyActiveSeconds", "sedentarySeconds"]:
        if key in result:
            minutes_key = key.replace("Seconds", "Minutes")
            result[minutes_key] = _seconds_to_minutes(result.get(key, 0))

    # === Weight: grams → kg ===
    for key in ["weight", "boneMass", "muscleMass"]:
        if key in result:
            kg_key = f"{key}Kg"
            result[kg_key] = _grams_to_kg(result.get(key, 0))

    # === HRV: flatten nested structure ===
    hrv = result.get("hrvStatus", {})
    if hrv:
        result["hrvStatusText"] = (hrv.get("status") or "").capitalize()
        result["hrvWeeklyAvg"] = hrv.get("weeklyAvg")
        result["hrvLastNightAvg"] = hrv.get("lastNightAvg")
        result["hrvLastNight5MinHigh"] = hrv.get("lastNight5MinHigh")
        baseline = hrv.get("baseline", {})
        result["hrvBaselineLowUpper"] = baseline.get("lowUpper")
        result["hrvBaselineBalancedLow"] = baseline.get("balancedLow")
        result["hrvBaselineBalancedUpper"] = baseline.get("balancedUpper")

    # === Training: flatten nested structures ===
    training_readiness = result.get("trainingReadiness", {})
    if training_readiness:
        result["trainingReadinessScore"] = training_readiness.get("score")
        result["trainingReadinessLevel"] = training_readiness.get("level")

    morning_readiness = result.get("morningTrainingReadiness", {})
    if morning_readiness:
        result["morningTrainingReadinessScore"] = morning_readiness.get("score")

    training_status = result.get("trainingStatus", {})
    if training_status:
        result["trainingStatusPhrase"] = training_status.get("trainingStatusPhrase")

    # === Scores: flatten nested structures ===
    endurance = result.get("enduranceScore", {})
    if endurance:
        result["enduranceScoreValue"] = endurance.get("overallScore")

    hill = result.get("hillScore", {})
    if hill:
        result["hillScoreValue"] = hill.get("overallScore")

    # === Stress qualifier: capitalize ===
    if "stressQualifier" in result:
        result["stressQualifierText"] = (
            result.get("stressQualifier") or ""
        ).capitalize()

    return result


class GarminClient:
    """Async Garmin Connect API client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: GarminAuth,
        is_cn: bool = False,
    ) -> None:
        """Initialize client.

        Args:
            session: aiohttp ClientSession
            auth: GarminAuth instance with tokens
            is_cn: Use Chinese Garmin Connect domain
        """
        self._session = session
        self._auth = auth
        self._is_cn = is_cn
        self._base_url = GARMIN_CN_CONNECT_API if is_cn else GARMIN_CONNECT_API
        self._profile_cache: UserProfile | None = None

    def _get_url(self, url: str) -> str:
        """Get URL with correct base domain."""
        if self._is_cn:
            return url.replace(GARMIN_CONNECT_API, GARMIN_CN_CONNECT_API)
        return url

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any] | list[Any]:
        """Make authenticated API request with retry/backoff for rate limits and server errors.

        Retries up to 3 times for:
        - 429 (Too Many Requests) - rate limited
        - 5xx (Server errors) - temporary Garmin issues
        """
        import asyncio

        MAX_RETRIES = 3
        RETRY_DELAYS = [1, 2, 4]  # Exponential backoff in seconds

        if not self._auth.oauth2_token:
            raise GarminAuthError("Not authenticated")

        access_token = self._auth.oauth2_token.get("access_token", "")
        if not access_token:
            raise GarminAuthError("No access token in oauth2_token")

        # Apply CN domain if needed
        url = self._get_url(url)

        headers = {
            **DEFAULT_HEADERS,
            "Authorization": f"Bearer {access_token}",
        }

        try:
            async with self._session.request(
                method, url, params=params, headers=headers
            ) as response:
                # Handle 401 - token expired, refresh and retry once
                if response.status == 401:
                    _LOGGER.debug("Token expired, refreshing")
                    await self._auth.refresh_tokens()
                    new_token = self._auth.oauth2_token.get("access_token", "")
                    headers["Authorization"] = f"Bearer {new_token}"
                    async with self._session.request(
                        method, url, params=params, headers=headers
                    ) as retry_response:
                        if retry_response.status not in (200, 204, 404):
                            raise GarminAPIError(
                                f"Request failed after token refresh: {retry_response.status}",
                                retry_response.status,
                            )
                        if retry_response.status in (204, 404):
                            _LOGGER.debug(
                                "API %s returned %d", url, retry_response.status
                            )
                            return {}
                        return await retry_response.json()

                # Handle 204 No Content
                elif response.status == 204:
                    _LOGGER.debug("API %s returned 204 No Content", url)
                    return {}

                # Handle 404 - data not available
                elif response.status == 404:
                    _LOGGER.debug("API %s returned 404 - data not available", url)
                    return {}

                # Handle 429 Rate Limit - retry with backoff
                elif response.status == 429:
                    if _retry_count < MAX_RETRIES:
                        delay = RETRY_DELAYS[_retry_count]
                        _LOGGER.warning(
                            "Rate limited (429) on %s, retrying in %ds (attempt %d/%d)",
                            url.split("/")[-1],
                            delay,
                            _retry_count + 1,
                            MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                        return await self._request(
                            method, url, params, _retry_count=_retry_count + 1
                        )
                    raise GarminAPIError(
                        f"Rate limited after {MAX_RETRIES} retries",
                        response.status,
                    )

                # Handle 5xx Server Errors (502 Bad Gateway, 503, 504, etc.) - retry with backoff
                elif 500 <= response.status < 600:
                    if _retry_count < MAX_RETRIES:
                        delay = RETRY_DELAYS[_retry_count]
                        _LOGGER.warning(
                            "Server error (%d) on %s, retrying in %ds (attempt %d/%d)",
                            response.status,
                            url.split("/")[-1],
                            delay,
                            _retry_count + 1,
                            MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                        return await self._request(
                            method, url, params, _retry_count=_retry_count + 1
                        )
                    raise GarminAPIError(
                        f"Server error {response.status} after {MAX_RETRIES} retries",
                        response.status,
                    )

                # Handle other non-200 errors
                elif response.status != 200:
                    text = await response.text()
                    _LOGGER.debug(
                        "API %s returned %d: %s", url, response.status, text[:200]
                    )
                    raise GarminAPIError(
                        f"Request to {url} failed: {response.status}",
                        response.status,
                    )

                # Success - return JSON response
                result = await response.json()
                _LOGGER.debug("API response from %s: %s", url, str(result)[:5000])
                return result

        except (GarminAPIError, GarminAuthError):
            raise
        except Exception as err:
            _LOGGER.debug("Request to %s failed: %s", url, err)
            raise GarminAPIError(f"Request failed: {err}") from err

    async def _safe_call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Safely call an API function, returning None on error."""
        try:
            return await func(*args, **kwargs)
        except GarminAPIError as err:
            _LOGGER.warning("API call %s failed: %s", func.__name__, err)
            return None

    # ========== Main Data Fetching ==========
    # DEPRECATED: The get_data() method has been removed.
    # Use specialized fetch methods instead:
    # - fetch_core_data() for summary, steps, sleep, stress, HRV
    # - fetch_activity_data() for activities, polylines, workouts
    # - fetch_training_data() for training readiness, status, lactate threshold
    # - fetch_body_data() for weight, body composition, hydration, fitness age
    # - fetch_goals_data() for goals, badges
    # - fetch_gear_data() for gear stats, alarms
    # - fetch_blood_pressure_data() for blood pressure
    # - fetch_menstrual_data() for menstrual cycle data

    def _calculate_next_active_alarms(
        self, alarms: list[dict[str, Any]] | None, timezone: str | None
    ) -> list[str] | None:
        """Calculate the next scheduled active alarms.

        Args:
            alarms: List of alarm dictionaries from Garmin API
            timezone: Timezone string (e.g., "Europe/Amsterdam")

        Returns:
            Sorted list of ISO format alarm datetimes, or None if no alarms/timezone

        Note:
            alarmTime is in minutes from midnight (e.g., 420 = 7:00 AM)
            alarmDays can be: ONCE, MONDAY, TUESDAY, etc.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        if not alarms or not timezone:
            _LOGGER.debug("No alarms or timezone provided")
            return None

        active_alarms: list[str] = []
        day_to_number = {
            "MONDAY": 1,
            "TUESDAY": 2,
            "WEDNESDAY": 3,
            "THURSDAY": 4,
            "FRIDAY": 5,
            "SATURDAY": 6,
            "SUNDAY": 7,
        }

        try:
            tz = ZoneInfo(timezone)
            now = datetime.now(tz)
        except Exception as err:
            _LOGGER.warning("Invalid timezone '%s': %s", timezone, err)
            return None

        _LOGGER.debug(
            "Processing %d alarms at %s (%s)", len(alarms), now.isoformat(), timezone
        )

        for alarm_setting in alarms:
            # Only process active alarms
            alarm_mode = alarm_setting.get("alarmMode")
            if alarm_mode != "ON":
                _LOGGER.debug(
                    "Skipping alarm %s (mode=%s)",
                    alarm_setting.get("alarmId"),
                    alarm_mode,
                )
                continue

            # alarmTime is minutes from midnight
            alarm_minutes = alarm_setting.get("alarmTime", 0)
            alarm_days = alarm_setting.get("alarmDays", [])

            _LOGGER.debug(
                "Processing alarm %s: time=%d min, days=%s",
                alarm_setting.get("alarmId"),
                alarm_minutes,
                alarm_days,
            )

            for day in alarm_days:
                if day == "ONCE":
                    # One-time alarm: occurs at alarm_minutes from today's midnight
                    # If already passed today, it's for tomorrow
                    midnight_today = datetime.combine(
                        now.date(), datetime.min.time(), tzinfo=tz
                    )
                    alarm = midnight_today + timedelta(minutes=alarm_minutes)
                    if alarm <= now:
                        # Already passed today, add for tomorrow
                        alarm += timedelta(days=1)
                    active_alarms.append(alarm.isoformat())
                    _LOGGER.debug("ONCE alarm scheduled for %s", alarm.isoformat())

                elif day in day_to_number:
                    # Recurring weekly alarm for specific day
                    target_weekday = day_to_number[day]  # 1=Monday, 7=Sunday
                    current_weekday = now.isoweekday()

                    # Calculate days until target day
                    days_ahead = target_weekday - current_weekday
                    if days_ahead < 0:
                        # Target day already passed this week
                        days_ahead += 7
                    elif days_ahead == 0:
                        # Same day - check if alarm already passed
                        midnight_today = datetime.combine(
                            now.date(), datetime.min.time(), tzinfo=tz
                        )
                        alarm_today = midnight_today + timedelta(minutes=alarm_minutes)
                        if alarm_today <= now:
                            # Already passed today, next week
                            days_ahead = 7

                    # Calculate alarm datetime
                    target_date = now.date() + timedelta(days=days_ahead)
                    midnight_target = datetime.combine(
                        target_date, datetime.min.time(), tzinfo=tz
                    )
                    alarm = midnight_target + timedelta(minutes=alarm_minutes)
                    active_alarms.append(alarm.isoformat())
                    _LOGGER.debug(
                        "%s alarm scheduled for %s (in %d days)",
                        day,
                        alarm.isoformat(),
                        days_ahead,
                    )

                else:
                    _LOGGER.debug("Unknown alarm day type: %s", day)

        if not active_alarms:
            _LOGGER.debug("No active alarms found")
            return None

        sorted_alarms = sorted(active_alarms)
        _LOGGER.debug("Active alarms: %s", sorted_alarms)
        return sorted_alarms

    async def get_user_profile(self) -> UserProfile:
        """Get user profile information."""
        if self._profile_cache:
            return self._profile_cache
        data = await self._request("GET", USER_PROFILE_URL)
        self._profile_cache = UserProfile.model_validate(data)
        return self._profile_cache

    async def get_user_summary(self, target_date: date | None = None) -> dict[str, Any]:
        """Get daily summary for a date."""
        if target_date is None:
            target_date = date.today()

        profile = await self.get_user_profile()
        url = f"{USER_SUMMARY_URL}/{profile.display_name}"
        params = {"calendarDate": target_date.isoformat()}
        data = await self._request("GET", url, params=params)
        return data if isinstance(data, dict) else {}

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

    async def get_activities_by_date(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Get activities in a date range."""
        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "start": 0,
            "limit": 100,
        }
        data = await self._request("GET", ACTIVITIES_URL, params=params)
        return data if isinstance(data, list) else []

    async def get_activity_details(
        self, activity_id: int, max_chart_size: int = 100, max_poly_size: int = 4000
    ) -> dict[str, Any]:
        """Get detailed activity information including polyline."""
        url = f"{ACTIVITY_DETAILS_URL}/{activity_id}/details"
        params = {"maxChartSize": max_chart_size, "maxPolylineSize": max_poly_size}
        data = await self._request("GET", url, params=params)
        return data if isinstance(data, dict) else {}

    async def get_activity_hr_in_timezones(
        self, activity_id: int
    ) -> list[dict[str, Any]]:
        """Get heart rate time in zones for an activity.

        Returns a list of HR zones with time spent in each zone.
        Example: [{"zoneName": "Zone 1", "secsInZone": 300}, ...]
        """
        url = f"{ACTIVITY_DETAILS_URL}/{activity_id}/hrTimeInZones"
        data = await self._request("GET", url)
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

    async def get_hrv_data(self, target_date: date | None = None) -> dict[str, Any]:
        """Get HRV data for a date."""
        if target_date is None:
            target_date = date.today()

        url = f"{HRV_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_hydration_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get hydration data for a date."""
        if target_date is None:
            target_date = date.today()

        url = f"{HYDRATION_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

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

        params = {"calendarDate": target_date.isoformat()}
        data = await self._request("GET", ENDURANCE_SCORE_URL, params=params)
        return data if isinstance(data, dict) else {}

    async def get_hill_score(self, target_date: date | None = None) -> dict[str, Any]:
        """Get hill score."""
        if target_date is None:
            target_date = date.today()

        params = {"calendarDate": target_date.isoformat()}
        data = await self._request("GET", HILL_SCORE_URL, params=params)
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

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get list of connected Garmin devices."""
        data = await self._request("GET", DEVICES_URL)
        return data if isinstance(data, list) else []

    async def get_goals(self, status: str = "active") -> list[dict[str, Any]]:
        """Get goals by status (active, future, past)."""
        params = {"status": status}
        data = await self._request("GET", GOALS_URL, params=params)
        return data if isinstance(data, list) else []

    async def get_earned_badges(self) -> list[dict[str, Any]]:
        """Get earned badges."""
        data = await self._request("GET", BADGES_URL)
        return data if isinstance(data, list) else []

    async def get_gear(self, user_profile_id: int) -> list[dict[str, Any]]:
        """Get user gear."""
        params = {"userProfilePk": str(user_profile_id)}
        data = await self._request("GET", GEAR_URL, params=params)
        return data if isinstance(data, list) else []

    async def get_gear_stats(self, gear_uuid: str) -> dict[str, Any]:
        """Get gear statistics."""
        url = f"{GEAR_STATS_URL}/{gear_uuid}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_gear_defaults(self, user_profile_id: int) -> list[dict[str, Any]]:
        """Get default gear settings."""
        url = f"{GEAR_DEFAULTS_URL}/{user_profile_id}/activityTypes"
        data = await self._request("GET", url)
        return data if isinstance(data, list) else []

    async def get_blood_pressure(
        self, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """Get blood pressure data for a date range."""
        url = f"{BLOOD_PRESSURE_URL}/{start_date.isoformat()}/{end_date.isoformat()}"
        # includeAll must be string "true" (not boolean) for aiohttp params
        params = {"includeAll": "true"}
        data = await self._request("GET", url, params=params)
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

    async def get_menstrual_calendar(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> dict[str, Any]:
        """Get menstrual cycle calendar data with predictions.

        Returns cycle summaries including predicted cycles.
        """
        if start_date is None:
            start_date = date.today() - timedelta(days=30)
        if end_date is None:
            end_date = date.today() + timedelta(days=60)

        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }
        data = await self._request("GET", MENSTRUAL_CALENDAR_URL, params=params)
        return data if isinstance(data, dict) else {}

    async def _get_user_summary_raw(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get daily summary as raw dict for flat data output."""
        if target_date is None:
            target_date = date.today()

        profile = await self.get_user_profile()
        url = f"{USER_SUMMARY_URL}/{profile.display_name}"
        params = {"calendarDate": target_date.isoformat()}
        data = await self._request("GET", url, params=params)
        return data if isinstance(data, dict) else {}

    async def _get_sleep_data_raw(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get sleep data as raw dict for flat data output."""
        if target_date is None:
            target_date = date.today()

        profile = await self.get_user_profile()
        url = f"{SLEEP_URL}/{profile.display_name}"
        params = {"date": target_date.isoformat(), "nonSleepBufferMinutes": 60}
        data = await self._request("GET", url, params=params)
        return data if isinstance(data, dict) else {}

    async def _get_hrv_data_raw(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get HRV data as raw dict for flat data output."""
        if target_date is None:
            target_date = date.today()

        url = f"{HRV_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_device_alarms(self) -> list[dict[str, Any]]:
        """Get device alarms from all devices.

        Alarms are stored in device settings, not at a separate endpoint.
        This mirrors python-garminconnect's approach.
        Note: Not all devices sync alarms to Garmin Connect cloud.
        """
        alarms: list[dict[str, Any]] = []
        devices = await self._safe_call(self.get_devices)
        if devices:
            for device in devices:
                device_id = device.get("deviceId")
                if device_id:
                    settings = await self._safe_call(
                        self.get_device_settings, device_id
                    )
                    if settings:
                        device_alarms = settings.get("alarms")
                        if device_alarms:
                            alarms.extend(device_alarms)
        return alarms

    async def get_device_settings(self, device_id: int) -> dict[str, Any]:
        """Get device settings for a specific device."""
        url = f"{GARMIN_CONNECT_API}/device-service/deviceservice/device-info/settings/{device_id}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_morning_training_readiness(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get morning training readiness (AFTER_WAKEUP_RESET context).

        This filters the regular training readiness data for entries
        with inputContext == 'AFTER_WAKEUP_RESET'.
        """
        if target_date is None:
            target_date = date.today()

        # Get regular training readiness data
        data = await self.get_training_readiness(target_date)

        if not data:
            return {}

        # If response is a list, search for morning reading
        if isinstance(data, list):
            # First try to find entry with AFTER_WAKEUP_RESET context
            morning_entry = next(
                (
                    entry
                    for entry in data
                    if entry.get("inputContext") == "AFTER_WAKEUP_RESET"
                ),
                None,
            )

            # If no explicit morning context, return first entry as fallback
            # (typically the morning reading is first in the list)
            if morning_entry is None and data:
                _LOGGER.debug(
                    "No AFTER_WAKEUP_RESET context found, using first entry as fallback"
                )
                return data[0] if data else {}

            return morning_entry if morning_entry else {}

        # If response is a single dict, return it directly
        return data if isinstance(data, dict) else {}

    # ========== Write/Service Methods ==========

    async def _post_request(
        self,
        url: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated POST request."""

        headers = await self._auth.get_auth_headers()
        headers.update(DEFAULT_HEADERS)
        headers["Content-Type"] = "application/json"

        full_url = self._get_url(url)
        _LOGGER.debug("POST %s with payload: %s", full_url, json_data)

        async with self._session.post(
            full_url, headers=headers, json=json_data
        ) as response:
            if response.status == 401:
                _LOGGER.debug("401 - attempting token refresh")
                await self._auth.refresh()
                headers = await self._auth.get_auth_headers()
                headers.update(DEFAULT_HEADERS)
                headers["Content-Type"] = "application/json"
                async with self._session.post(
                    full_url, headers=headers, json=json_data
                ) as retry_response:
                    if retry_response.status != 200:
                        error_text = await retry_response.text()
                        _LOGGER.error(
                            "POST retry failed %s: %s",
                            retry_response.status,
                            error_text,
                        )
                        raise GarminAPIError(f"POST failed: {retry_response.status}")
                    return await retry_response.json()

            if response.status not in (200, 201, 204):
                error_text = await response.text()
                _LOGGER.error("POST failed %s: %s", response.status, error_text)
                raise GarminAPIError(f"POST failed: {response.status} - {error_text}")

            if response.status == 204:
                return {}

            return await response.json()

    async def _put_request(
        self,
        url: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated PUT request."""
        headers = await self._auth.get_auth_headers()
        headers.update(DEFAULT_HEADERS)
        if json_data is not None:
            headers["Content-Type"] = "application/json"

        full_url = self._get_url(url)
        _LOGGER.debug("PUT %s", full_url)

        async with self._session.put(
            full_url, headers=headers, json=json_data
        ) as response:
            if response.status == 401:
                await self._auth.refresh()
                headers = await self._auth.get_auth_headers()
                headers.update(DEFAULT_HEADERS)
                if json_data is not None:
                    headers["Content-Type"] = "application/json"
                async with self._session.put(
                    full_url, headers=headers, json=json_data
                ) as retry_response:
                    if retry_response.status not in (200, 201, 204):
                        raise GarminAPIError(f"PUT failed: {retry_response.status}")
                    if retry_response.status == 204:
                        return {}
                    return await retry_response.json()

            if response.status not in (200, 201, 204):
                raise GarminAPIError(f"PUT failed: {response.status}")

            if response.status == 204:
                return {}

            return await response.json()

    async def _delete_request(self, url: str) -> dict[str, Any]:
        """Make a DELETE request to the Garmin API."""
        headers = await self._auth.get_auth_headers()
        headers.update(DEFAULT_HEADERS)

        full_url = self._get_url(url)
        _LOGGER.debug("DELETE %s", full_url)

        async with self._session.delete(full_url, headers=headers) as response:
            if response.status == 401:
                await self._auth.refresh()
                headers = await self._auth.get_auth_headers()
                headers.update(DEFAULT_HEADERS)
                async with self._session.delete(
                    full_url, headers=headers
                ) as retry_response:
                    if retry_response.status not in (200, 204):
                        raise GarminAPIError(f"DELETE failed: {retry_response.status}")
                    if retry_response.status == 204:
                        return {}
                    return await retry_response.json()

            if response.status not in (200, 204):
                raise GarminAPIError(f"DELETE failed: {response.status}")

            if response.status == 204:
                return {}

            return await response.json()

    async def _upload_fit_file(
        self, fit_data: bytes, filename: str = "data.fit"
    ) -> dict[str, Any]:
        """Upload FIT file data to Garmin Connect.

        Args:
            fit_data: FIT file bytes
            filename: Name for the upload
        """
        import aiohttp

        headers = await self._auth.get_auth_headers()
        headers.update(DEFAULT_HEADERS)
        # Remove Content-Type - will be set by aiohttp for multipart

        full_url = self._get_url(UPLOAD_URL)
        _LOGGER.debug("Uploading FIT file: %s (%d bytes)", filename, len(fit_data))

        # Create multipart form data
        form_data = aiohttp.FormData()
        form_data.add_field(
            "file",
            fit_data,
            filename=filename,
            content_type="application/octet-stream",
        )

        async with self._session.post(
            full_url, headers=headers, data=form_data
        ) as response:
            if response.status == 401:
                # Retry after refresh
                await self._auth.refresh()
                headers = await self._auth.get_auth_headers()
                headers.update(DEFAULT_HEADERS)
                async with self._session.post(
                    full_url, headers=headers, data=form_data
                ) as retry_response:
                    if retry_response.status not in (200, 201):
                        text = await retry_response.text()
                        raise GarminAPIError(
                            f"FIT upload failed: {retry_response.status} - {text}"
                        )
                    return await retry_response.json()

            if response.status not in (200, 201):
                text = await response.text()
                raise GarminAPIError(f"FIT upload failed: {response.status} - {text}")

            return await response.json()

    async def set_blood_pressure(
        self,
        systolic: int,
        diastolic: int,
        pulse: int,
        timestamp: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Add blood pressure measurement.

        Args:
            systolic: Systolic blood pressure (70-260)
            diastolic: Diastolic blood pressure (40-150)
            pulse: Pulse rate (20-250)
            timestamp: ISO timestamp (defaults to now)
            notes: Optional notes
        """
        from datetime import datetime

        _LOGGER.debug(
            "set_blood_pressure called with systolic=%s, diastolic=%s, pulse=%s, timestamp=%s",
            systolic,
            diastolic,
            pulse,
            timestamp,
        )

        dt = datetime.fromisoformat(timestamp) if timestamp else datetime.now()
        dt_gmt = dt.astimezone(UTC)

        def fmt_ts(d: datetime) -> str:
            """Format timestamp with milliseconds precision like python-garminconnect."""
            return d.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

        payload = {
            "measurementTimestampLocal": fmt_ts(dt),
            "measurementTimestampGMT": fmt_ts(dt_gmt),
            "systolic": systolic,
            "diastolic": diastolic,
            "pulse": pulse,
            "sourceType": "MANUAL",
            "notes": notes,
        }

        _LOGGER.debug("Blood pressure payload: %s", payload)
        return await self._post_request(BLOOD_PRESSURE_SET_URL, payload)

    async def add_body_composition(
        self,
        weight: float,
        timestamp: str | None = None,
        percent_fat: float | None = None,
        percent_hydration: float | None = None,
        visceral_fat_mass: float | None = None,
        bone_mass: float | None = None,
        muscle_mass: float | None = None,
        basal_met: float | None = None,
        active_met: float | None = None,
        physique_rating: float | None = None,
        metabolic_age: float | None = None,
        visceral_fat_rating: float | None = None,
        bmi: float | None = None,
    ) -> dict[str, Any]:
        """Add body composition measurement via FIT file upload.

        Args:
            weight: Weight in kg (required)
            timestamp: ISO timestamp (defaults to now)
            percent_fat: Body fat percentage
            percent_hydration: Hydration percentage
            visceral_fat_mass: Visceral fat mass in kg
            bone_mass: Bone mass in kg
            muscle_mass: Muscle mass in kg
            basal_met: Basal metabolic rate in kcal
            active_met: Active metabolic rate in kcal
            physique_rating: Physique rating (1-9)
            metabolic_age: Metabolic age in years
            visceral_fat_rating: Visceral fat rating (1-59)
            bmi: Body mass index
        """
        from datetime import datetime

        from .fit import FitEncoderWeight  # type: ignore[attr-defined]

        _LOGGER.debug(
            "add_body_composition called with weight=%s, timestamp=%s",
            weight,
            timestamp,
        )

        dt = datetime.fromisoformat(timestamp) if timestamp else datetime.now()

        # Build FIT file
        fit_encoder = FitEncoderWeight()
        fit_encoder.write_file_info()
        fit_encoder.write_file_creator()
        fit_encoder.write_device_info(dt)
        fit_encoder.write_weight_scale(
            timestamp=dt,
            weight=weight,
            percent_fat=percent_fat,
            percent_hydration=percent_hydration,
            visceral_fat_mass=visceral_fat_mass,
            bone_mass=bone_mass,
            muscle_mass=muscle_mass,
            basal_met=basal_met,
            active_met=active_met,
            physique_rating=physique_rating,
            metabolic_age=metabolic_age,
            visceral_fat_rating=visceral_fat_rating,
            bmi=bmi,
        )
        fit_encoder.finish()

        # Upload FIT file
        return await self._upload_fit_file(
            fit_encoder.getvalue(), "body_composition.fit"
        )

    async def set_active_gear(
        self,
        activity_type: str,
        setting: str,
        gear_uuid: str | None = None,
    ) -> dict[str, Any]:
        """Set gear as active/default for an activity type.

        Note: This service requires an entity target to identify which gear to set.
        The gear_uuid is typically extracted from the target entity's attributes.

        Args:
            activity_type: Activity type (running, cycling, hiking, walking, swimming, other)
            setting: One of 'set this as default, unset others', 'set as default', 'unset default'
            gear_uuid: UUID of the gear (from entity target attributes)
        """
        if not gear_uuid:
            raise ValueError("gear_uuid is required - target a gear sensor entity")

        _LOGGER.debug(
            "set_active_gear called: activity_type=%s, setting=%s, gear_uuid=%s",
            activity_type,
            setting,
            gear_uuid,
        )

        # Determine the action based on setting
        if (
            setting == "set this as default, unset others"
            or setting == "set as default"
        ):
            default_gear = True
        elif setting == "unset default":
            default_gear = False
        else:
            raise ValueError(f"Unknown setting: {setting}")

        # Use consistent URL format with python-garminconnect:
        # PUT gear-service/gear/{gearUUID}/activityType/{activityTypeId}/default/true
        # DELETE gear-service/gear/{gearUUID}/activityType/{activityTypeId}
        # Note: activityType must be numeric (1=running, 2=cycling, etc.)

        activity_type_map = {
            "running": 1,
            "cycling": 2,
            "walking": 3,
            "hiking": 4,
            "swimming": 5,
            "other": 9,
        }
        activity_type_id = activity_type_map.get(activity_type.lower(), activity_type)

        url_path = f"/gear-service/gear/{gear_uuid}/activityType/{activity_type_id}"

        if default_gear:
            url = f"{GARMIN_CONNECT_API}{url_path}/default/true"
            return await self._put_request(url)
        else:
            url = f"{GARMIN_CONNECT_API}{url_path}"
            return await self._delete_request(url=url)

    async def create_activity(
        self,
        activity_name: str,
        activity_type: str,
        start_datetime: str,
        duration_min: int,
        distance_km: float = 0.0,
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        """Create a manual activity.

        Args:
            activity_name: Name/title of the activity
            activity_type: Type key (running, cycling, walking, etc.)
            start_datetime: ISO timestamp for start (2023-12-02T10:00:00.000)
            duration_min: Duration in minutes
            distance_km: Distance in kilometers (optional)
            time_zone: Timezone (e.g. Europe/Amsterdam, defaults to UTC)
        """
        # Ensure timestamp has milliseconds
        if "." not in start_datetime:
            start_datetime = f"{start_datetime}.000"

        payload = {
            "activityTypeDTO": {"typeKey": activity_type},
            "accessControlRuleDTO": {"typeId": 2, "typeKey": "private"},
            "timeZoneUnitDTO": {"unitKey": time_zone or "UTC"},
            "activityName": activity_name,
            "metadataDTO": {"autoCalcCalories": True},
            "summaryDTO": {
                "startTimeLocal": start_datetime,
                "distance": distance_km * 1000,  # Convert to meters
                "duration": duration_min * 60,  # Convert to seconds
            },
        }

        return await self._post_request(ACTIVITY_CREATE_URL, payload)

    async def upload_activity(self, file_path: str) -> dict[str, Any]:
        """Upload an activity file (FIT, GPX, TCX).

        Args:
            file_path: Path to the activity file
        """
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_extension = path.suffix.upper().lstrip(".")
        allowed_formats = {"FIT", "GPX", "TCX"}
        if file_extension not in allowed_formats:
            raise ValueError(
                f"Invalid file format '{file_extension}'. "
                f"Allowed: {', '.join(allowed_formats)}"
            )

        headers = await self._auth.get_auth_headers()
        # For multipart upload, only set User-Agent - let aiohttp handle Content-Type
        headers["User-Agent"] = "GCM-iOS-5.7.2.1"

        # Read file content (do this synchronously but it's a small file)
        file_bytes = await asyncio.get_event_loop().run_in_executor(
            None, path.read_bytes
        )

        from aiohttp import FormData

        data = FormData()
        # Match requests library multipart format
        content_type_map = {
            ".fit": "application/octet-stream",
            ".gpx": "application/gpx+xml",
            ".tcx": "application/vnd.garmin.tcx+xml",
        }
        content_type = content_type_map.get(
            path.suffix.lower(), "application/octet-stream"
        )
        data.add_field(
            "file", file_bytes, filename=path.name, content_type=content_type
        )

        full_url = self._get_url(UPLOAD_URL)
        _LOGGER.debug("Uploading activity file: %s", path.name)

        async with self._session.post(full_url, headers=headers, data=data) as response:
            # Handle 403 by refreshing token and retrying
            if response.status == 403:
                _LOGGER.debug("Upload got 403, refreshing token and retrying")
                await self._auth.refresh()
                headers = await self._auth.get_auth_headers()
                headers["User-Agent"] = "GCM-iOS-5.7.2.1"
                data = FormData()
                data.add_field(
                    "file", file_bytes, filename=path.name, content_type=content_type
                )
                async with self._session.post(
                    full_url, headers=headers, data=data
                ) as retry_response:
                    if retry_response.status not in (200, 201, 400):
                        body = await retry_response.text()
                        raise GarminAPIError(
                            f"Upload failed: {retry_response.status}, body: {body[:500]}"
                        )
                    try:
                        result = await retry_response.json()
                    except Exception:
                        result = {"raw": await retry_response.text()}
                    return result

            # Parse response (may be JSON or error page)
            try:
                body = await response.json()
            except Exception:
                error_text = await response.text()
                raise GarminAPIError(
                    f"Upload failed: {response.status}, body: {error_text[:500]}"
                ) from None

            # 400 with uploadId means file was accepted but has validation issues
            if response.status == 400 and body.get("detailedImportResult", {}).get(
                "uploadId"
            ):
                _LOGGER.warning("Upload accepted with warnings: %s", body)
                return body

            # Handle 409 (duplicate) and other errors with friendly messages
            if response.status not in (200, 201, 202):
                result = body.get("detailedImportResult", {})
                failures = result.get("failures", [])
                if failures:
                    # Extract readable messages from failures
                    messages = []
                    for failure in failures:
                        for msg in failure.get("messages", []):
                            messages.append(msg.get("content", "Unknown error"))
                    error_msg = "; ".join(messages) if messages else "Unknown error"
                    raise GarminAPIError(f"Upload failed: {error_msg}")
                raise GarminAPIError(f"Upload failed: {response.status}, body: {body}")
            return body

    async def add_gear_to_activity(
        self, gear_uuid: str, activity_id: int
    ) -> dict[str, Any]:
        """Associate gear with an activity.

        Args:
            gear_uuid: UUID of the gear (from get_gear)
            activity_id: ID of the activity
        """
        url = f"{GEAR_LINK_URL}/{gear_uuid}/activity/{activity_id}"
        return await self._put_request(url)

    # ========== Multi-Coordinator Fetch Methods ==========

    async def fetch_core_data(self, target_date: date | None = None) -> dict[str, Any]:
        """Fetch core data: summary, daily steps, sleep.

        API calls: get_user_summary, get_daily_steps, get_sleep_data (3 calls)
        """
        if target_date is None:
            target_date = date.today()

        yesterday_date = target_date - timedelta(days=1)
        week_ago = target_date - timedelta(days=7)

        # Core summary with midnight fallback
        summary_raw = await self._safe_call(self._get_user_summary_raw, target_date)
        today_data_not_ready = (
            not summary_raw or summary_raw.get("dailyStepGoal") is None
        )

        if today_data_not_ready:
            yesterday_summary = await self._safe_call(
                self._get_user_summary_raw, yesterday_date
            )
            if yesterday_summary and yesterday_summary.get("dailyStepGoal") is not None:
                summary_raw = yesterday_summary

        summary_raw = summary_raw or {}

        # Weekly averages
        daily_steps = await self._safe_call(
            self.get_daily_steps, week_ago, yesterday_date
        )
        yesterday_steps = None
        yesterday_distance = None
        weekly_step_avg = None
        weekly_distance_avg = None

        if daily_steps:
            yesterday_data = daily_steps[-1]
            yesterday_steps = yesterday_data.get("totalSteps")
            yesterday_distance = yesterday_data.get("totalDistance")

            total_steps = sum(d.get("totalSteps", 0) for d in daily_steps)
            total_distance = sum(d.get("totalDistance", 0) for d in daily_steps)
            days_count = len(daily_steps)
            if days_count > 0:
                weekly_step_avg = round(total_steps / days_count)
                weekly_distance_avg = round(total_distance / days_count)

        # Sleep data
        sleep_data = await self._safe_call(self._get_sleep_data_raw, target_date)
        sleep_score = None
        sleep_time_seconds = None
        deep_sleep_seconds = None
        light_sleep_seconds = None
        rem_sleep_seconds = None
        awake_sleep_seconds = None

        if sleep_data:
            try:
                daily_sleep = sleep_data.get("dailySleepDTO", {})
                sleep_score = (
                    daily_sleep.get("sleepScores", {}).get("overall", {}).get("value")
                )
                sleep_time_seconds = daily_sleep.get("sleepTimeSeconds")
                deep_sleep_seconds = daily_sleep.get("deepSleepSeconds")
                light_sleep_seconds = daily_sleep.get("lightSleepSeconds")
                rem_sleep_seconds = daily_sleep.get("remSleepSeconds")
                awake_sleep_seconds = daily_sleep.get("awakeSleepSeconds")
            except (KeyError, TypeError):
                pass

        data = {
            **summary_raw,
            "yesterdaySteps": yesterday_steps,
            "yesterdayDistance": yesterday_distance,
            "weeklyStepAvg": weekly_step_avg,
            "weeklyDistanceAvg": weekly_distance_avg,
            "sleepScore": sleep_score,
            "sleepTimeSeconds": sleep_time_seconds,
            "deepSleepSeconds": deep_sleep_seconds,
            "lightSleepSeconds": light_sleep_seconds,
            "remSleepSeconds": rem_sleep_seconds,
            "awakeSleepSeconds": awake_sleep_seconds,
        }
        return _add_computed_fields(data)

    async def fetch_activity_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Fetch activity data: activities, polyline, HR zones, workouts.

        API calls: get_activities_by_date, get_activity_details,
                   get_activity_hr_in_timezones, get_workouts (4 calls)
        """
        if target_date is None:
            target_date = date.today()

        week_ago = target_date - timedelta(days=7)

        # Activities
        activities_by_date = await self._safe_call(
            self.get_activities_by_date, week_ago, target_date + timedelta(days=1)
        )
        last_activity: dict[str, Any] = {}
        if activities_by_date:
            last_activity = dict(activities_by_date[0])
            activity_id = last_activity.get("activityId")

            # Fetch polyline
            if last_activity.get("hasPolyline") and activity_id is not None:
                try:
                    activity_details = await self.get_activity_details(
                        int(activity_id), 100, 4000
                    )
                    if activity_details:
                        polyline_data = activity_details.get("geoPolylineDTO", {})
                        raw_polyline = polyline_data.get("polyline", [])
                        last_activity["polyline"] = [
                            {"lat": p.get("lat"), "lon": p.get("lon")}
                            for p in raw_polyline
                            if p.get("lat") is not None and p.get("lon") is not None
                        ]
                except GarminAPIError as err:
                    _LOGGER.debug("Failed to fetch polyline: %s", err)

            # Fetch HR zones
            if activity_id:
                hr_zones = await self._safe_call(
                    self.get_activity_hr_in_timezones, activity_id
                )
                if hr_zones:
                    last_activity["hrTimeInZones"] = hr_zones

        # Workouts
        workouts = await self._safe_call(self.get_workouts, 0, 10)
        workouts = workouts or []

        # Trim activities to essential fields
        trimmed_activities = [_trim_activity(a) for a in (activities_by_date or [])]
        trimmed_last_activity = _trim_activity(last_activity) if last_activity else {}

        return {
            "lastActivities": trimmed_activities,
            "lastActivity": trimmed_last_activity,
            "workouts": workouts,
            "lastWorkout": workouts[0] if workouts else {},
        }

    async def fetch_training_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Fetch training data: readiness, status, lactate, scores, HRV.

        API calls: get_training_readiness, get_morning_training_readiness,
                   get_training_status, get_lactate_threshold, get_endurance_score,
                   get_hill_score, get_hrv_data (7 calls)
        """
        if target_date is None:
            target_date = date.today()

        training_readiness = await self._safe_call(
            self.get_training_readiness, target_date
        )
        morning_training_readiness = await self._safe_call(
            self.get_morning_training_readiness, target_date
        )
        training_status = await self._safe_call(self.get_training_status, target_date)
        lactate_threshold = await self._safe_call(self.get_lactate_threshold)

        endurance_data = await self._safe_call(self.get_endurance_score, target_date)
        endurance_score: dict[str, Any] = {"overallScore": None}
        if endurance_data and "overallScore" in endurance_data:
            endurance_score = endurance_data

        hill_data = await self._safe_call(self.get_hill_score, target_date)
        hill_score: dict[str, Any] = {"overallScore": None}
        if hill_data and "overallScore" in hill_data:
            hill_score = hill_data

        # HRV
        hrv_data = await self._safe_call(self._get_hrv_data_raw, target_date)
        hrv_status: dict[str, Any] = {"status": "unknown"}
        if hrv_data and "hrvSummary" in hrv_data:
            hrv_status = hrv_data["hrvSummary"]

        data = {
            "trainingReadiness": training_readiness or {},
            "morningTrainingReadiness": morning_training_readiness or {},
            "trainingStatus": training_status or {},
            "lactateThreshold": lactate_threshold or {},
            "enduranceScore": endurance_score,
            "hillScore": hill_score,
            "hrvStatus": hrv_status,
        }
        return _add_computed_fields(data)

    async def fetch_body_data(self, target_date: date | None = None) -> dict[str, Any]:
        """Fetch body data: body composition, hydration, fitness age.

        API calls: get_body_composition, get_hydration_data, get_fitness_age (3 calls)
        """
        if target_date is None:
            target_date = date.today()

        body_composition = await self._safe_call(self.get_body_composition, target_date)
        body_composition = body_composition or {}

        hydration = await self._safe_call(self.get_hydration_data, target_date)
        hydration = hydration or {}

        fitness_age = await self._safe_call(self.get_fitness_age, target_date)
        fitness_age = fitness_age or {}

        data = {
            **body_composition,
            **hydration,
            **fitness_age,
        }
        return _add_computed_fields(data)

    async def fetch_goals_data(self) -> dict[str, Any]:
        """Fetch goals data: goals, badges.

        API calls: get_goals×3, get_earned_badges (4 calls)
        """
        active_goals = await self._safe_call(self.get_goals, "active")
        future_goals = await self._safe_call(self.get_goals, "future")
        past_goals = await self._safe_call(self.get_goals, "past")

        raw_badges = await self._safe_call(self.get_earned_badges)
        raw_badges = raw_badges or []

        # Calculate points before trimming
        user_points = sum(
            badge.get("badgePoints", 0) * badge.get("badgeEarnedNumber", 1)
            for badge in raw_badges
        )
        level_points = {
            1: 0,
            2: 20,
            3: 60,
            4: 140,
            5: 300,
            6: 600,
            7: 1200,
            8: 2400,
            9: 4800,
            10: 9600,
        }
        user_level = 1
        for level, points in level_points.items():
            if user_points >= points:
                user_level = level

        # Trim badges to only essential fields (reduces data from ~30 to 4 fields per badge)
        badges = [
            {
                "badgeName": b.get("badgeName"),
                "badgePoints": b.get("badgePoints"),
                "badgeEarnedDate": b.get("badgeEarnedDate"),
                "badgeEarnedNumber": b.get("badgeEarnedNumber"),
            }
            for b in raw_badges
        ]

        return {
            "activeGoals": active_goals or [],
            "futureGoals": future_goals or [],
            "goalsHistory": (past_goals or [])[:10],
            "badges": badges,
            "userPoints": user_points,
            "userLevel": user_level,
        }

    async def fetch_gear_data(self, timezone: str | None = None) -> dict[str, Any]:
        """Fetch gear data: gear, defaults, stats, alarms.

        API calls: get_gear, get_gear_defaults, get_gear_stats×N,
                   get_device_alarms (4+ calls)
        """
        # Get user profile ID for gear API
        profile = await self._safe_call(self.get_user_profile)
        user_profile_id = profile.profile_id if profile else None

        gear: list[dict[str, Any]] = []
        gear_stats: list[dict[str, Any]] = []
        gear_defaults: dict[str, Any] = {}

        if user_profile_id:
            gear = await self._safe_call(self.get_gear, user_profile_id) or []
            gear_defaults = (
                await self._safe_call(self.get_gear_defaults, user_profile_id) or {}
            )

            activity_type_names = {
                1: "running",
                2: "cycling",
                3: "walking",
                4: "hiking",
                5: "swimming",
                6: "gym",
                7: "yoga",
                9: "other",
            }
            gear_default_activities: dict[str, list[str]] = {}
            if isinstance(gear_defaults, list):
                for default in gear_defaults:
                    uuid = default.get("uuid")
                    activity_pk = default.get("activityTypePk")
                    if uuid and activity_pk and default.get("defaultGear"):
                        if uuid not in gear_default_activities:
                            gear_default_activities[uuid] = []
                        activity_name = activity_type_names.get(
                            activity_pk, f"type_{activity_pk}"
                        )
                        gear_default_activities[uuid].append(activity_name)

            if gear:
                for gear_item in gear:
                    gear_uuid = gear_item.get("uuid")
                    if gear_uuid:
                        stats = await self._safe_call(self.get_gear_stats, gear_uuid)
                        if stats:
                            stats["gearUuid"] = gear_uuid
                            stats["gearName"] = gear_item.get("displayName", "Unknown")
                            stats["gearTypeName"] = gear_item.get(
                                "gearTypeName", "Unknown"
                            )
                            stats["gearStatusName"] = gear_item.get(
                                "gearStatusName", "active"
                            )
                            stats["gearMakeName"] = gear_item.get("gearMakeName")
                            stats["gearModelName"] = gear_item.get("gearModelName")
                            stats["customMakeModel"] = gear_item.get("customMakeModel")
                            stats["dateBegin"] = gear_item.get("dateBegin")
                            stats["dateEnd"] = gear_item.get("dateEnd")
                            stats["maximumMeters"] = gear_item.get("maximumMeters")
                            stats["defaultForActivity"] = gear_default_activities.get(
                                gear_uuid, []
                            )
                            gear_stats.append(stats)

        # Alarms
        alarms = await self._safe_call(self.get_device_alarms)
        next_alarms = self._calculate_next_active_alarms(alarms, timezone)

        return {
            "gear": gear,
            "gearStats": gear_stats,
            "gearDefaults": gear_defaults,
            "nextAlarm": next_alarms,
        }

    async def fetch_blood_pressure_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Fetch blood pressure data.

        API calls: get_blood_pressure (1 call)
        """
        if target_date is None:
            target_date = date.today()

        blood_pressure_data: dict[str, Any] = {}
        bp_response = await self._safe_call(
            self.get_blood_pressure,
            target_date - timedelta(days=30),
            target_date,
        )
        if bp_response and isinstance(bp_response, dict):
            summaries = bp_response.get("measurementSummaries", [])

            all_measurements: list[dict[str, Any]] = []
            for summary in summaries:
                measurements = summary.get("measurements", [])
                all_measurements.extend(measurements)

            if all_measurements:
                latest_bp = max(
                    all_measurements,
                    key=lambda m: m.get("measurementTimestampLocal", ""),
                )
                blood_pressure_data = {
                    "bpSystolic": latest_bp.get("systolic"),
                    "bpDiastolic": latest_bp.get("diastolic"),
                    "bpPulse": latest_bp.get("pulse"),
                    "bpMeasurementTime": latest_bp.get("measurementTimestampLocal"),
                    "bpCategory": latest_bp.get("category"),
                    "bpCategoryName": latest_bp.get("categoryName"),
                }
            elif summaries:
                latest_summary = max(
                    summaries,
                    key=lambda s: s.get("startDate", ""),
                )
                blood_pressure_data = {
                    "bpSystolic": latest_summary.get("highSystolic"),
                    "bpDiastolic": latest_summary.get("highDiastolic"),
                    "bpPulse": None,
                    "bpMeasurementTime": latest_summary.get("startDate"),
                    "bpCategory": latest_summary.get("category"),
                    "bpCategoryName": latest_summary.get("categoryName"),
                }

        return blood_pressure_data

    async def fetch_menstrual_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Fetch menstrual data: day summary and calendar predictions.

        API calls: get_menstrual_data, get_menstrual_calendar (2 calls)
        """
        if target_date is None:
            target_date = date.today()

        menstrual_data = await self._safe_call(self.get_menstrual_data, target_date)
        menstrual_data = menstrual_data or {}

        menstrual_calendar = await self._safe_call(self.get_menstrual_calendar)
        menstrual_calendar = menstrual_calendar or {}

        return {
            "menstrualData": menstrual_data,
            "menstrualCalendar": menstrual_calendar,
        }
