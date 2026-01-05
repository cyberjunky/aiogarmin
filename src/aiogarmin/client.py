"""Async client for Garmin Connect API."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from .const import (
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
    GARMIN_CN_CONNECT_API,
    GARMIN_CONNECT_API,
    GEAR_DEFAULTS_URL,
    GEAR_STATS_URL,
    GEAR_URL,
    GOALS_URL,
    HILL_SCORE_URL,
    HRV_URL,
    HYDRATION_URL,
    LACTATE_THRESHOLD_URL,
    MENSTRUAL_URL,
    MORNING_TRAINING_READINESS_URL,
    RESPIRATION_URL,
    SLEEP_URL,
    SPO2_URL,
    STRESS_URL,
    TRAINING_READINESS_URL,
    TRAINING_STATUS_URL,
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
                _LOGGER.debug("API response from %s: %s", url, str(result)[:500])
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

    async def get_data(
        self, target_date: date | None = None, timezone: str | None = None
    ) -> dict[str, Any]:
        """Fetch all Garmin Connect data for a date.

        Returns FLAT dictionary with all sensor keys matching sensor_descriptions.py.
        Implements midnight fallback: if today's data isn't ready (dailyStepGoal=None),
        falls back to yesterday's data.

        Args:
            target_date: Date to fetch data for (default: today)
            timezone: Timezone string for alarm calculations (e.g., "Europe/Amsterdam")

        Returns:
            Flat dictionary with all sensor data keys
        """
        if target_date is None:
            target_date = date.today()

        yesterday_date = target_date - timedelta(days=1)
        week_ago = target_date - timedelta(days=7)

        # ========== Core Summary with Midnight Fallback ==========
        summary_raw = await self._safe_call(self._get_user_summary_raw, target_date)

        # Smart fallback: detect when Garmin servers haven't populated today's data yet
        # Key signal: dailyStepGoal is None means the day data structure doesn't exist
        today_data_not_ready = not summary_raw or summary_raw.get("dailyStepGoal") is None

        if today_data_not_ready:
            _LOGGER.debug(
                "Today's data not ready (dailyStepGoal=%s), fetching yesterday's data",
                summary_raw.get("dailyStepGoal") if summary_raw else None,
            )
            yesterday_summary = await self._safe_call(
                self._get_user_summary_raw, yesterday_date
            )
            if yesterday_summary and yesterday_summary.get("dailyStepGoal") is not None:
                summary_raw = yesterday_summary
                _LOGGER.debug("Using yesterday's summary data as fallback")

        # Default to empty dict if still None
        summary_raw = summary_raw or {}

        _LOGGER.debug(
            "Summary data: totalSteps=%s, dailyStepGoal=%s, lastSync=%s",
            summary_raw.get("totalSteps"),
            summary_raw.get("dailyStepGoal"),
            summary_raw.get("lastSyncTimestampGMT"),
        )

        # ========== Weekly Averages ==========
        daily_steps = await self._safe_call(
            self.get_daily_steps, week_ago, yesterday_date
        )
        yesterday_steps = None
        yesterday_distance = None
        weekly_step_avg = None
        weekly_distance_avg = None

        if daily_steps:
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

        # ========== Body Composition ==========
        body_composition = await self._safe_call(self.get_body_composition, target_date)
        body_composition = body_composition or {}

        # ========== Activities ==========
        activities_by_date = await self._safe_call(
            self.get_activities_by_date, week_ago, target_date + timedelta(days=1)
        )
        last_activity: dict[str, Any] = {}
        if activities_by_date:
            last_activity = dict(activities_by_date[0])
            # Fetch polyline for last activity if it has GPS data
            if last_activity.get("hasPolyline"):
                try:
                    activity_id = last_activity.get("activityId")
                    activity_details = await self.get_activity_details(
                        activity_id, 100, 4000
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
                    _LOGGER.debug("Failed to fetch polyline for activity: %s", err)

        # ========== Workouts ==========
        workouts = await self._safe_call(self.get_workouts, 0, 10)
        workouts = workouts or []

        # ========== Sleep Data ==========
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
                sleep_score = daily_sleep.get("sleepScores", {}).get("overall", {}).get("value")
                sleep_time_seconds = daily_sleep.get("sleepTimeSeconds")
                deep_sleep_seconds = daily_sleep.get("deepSleepSeconds")
                light_sleep_seconds = daily_sleep.get("lightSleepSeconds")
                rem_sleep_seconds = daily_sleep.get("remSleepSeconds")
                awake_sleep_seconds = daily_sleep.get("awakeSleepSeconds")
            except (KeyError, TypeError):
                pass

        # ========== Stress Data ==========
        stress_data = await self._safe_call(self._get_stress_data_raw, target_date)
        stress_data = stress_data or {}

        # ========== HRV Data ==========
        hrv_data = await self._safe_call(self._get_hrv_data_raw, target_date)
        hrv_status: dict[str, Any] = {"status": "unknown"}
        if hrv_data and "hrvSummary" in hrv_data:
            hrv_status = hrv_data["hrvSummary"]

        # ========== Body Battery ==========
        body_battery_data = await self._safe_call(self._get_body_battery_raw, target_date)

        # ========== Hydration ==========
        hydration = await self._safe_call(self.get_hydration_data, target_date)
        hydration = hydration or {}

        # ========== Training Readiness ==========
        training_readiness = await self._safe_call(
            self.get_training_readiness, target_date
        )

        # ========== Morning Training Readiness ==========
        morning_training_readiness = await self._safe_call(
            self.get_morning_training_readiness, target_date
        )

        # ========== Training Status ==========
        training_status = await self._safe_call(self.get_training_status, target_date)

        # ========== Lactate Threshold ==========
        lactate_threshold = await self._safe_call(self.get_lactate_threshold)

        # ========== Endurance Score ==========
        endurance_data = await self._safe_call(self.get_endurance_score, target_date)
        endurance_score: dict[str, Any] = {"overallScore": None}
        if endurance_data and "overallScore" in endurance_data:
            endurance_score = endurance_data

        # ========== Hill Score ==========
        hill_data = await self._safe_call(self.get_hill_score, target_date)
        hill_score: dict[str, Any] = {"overallScore": None}
        if hill_data and "overallScore" in hill_data:
            hill_score = hill_data

        # ========== Fitness Age ==========
        fitness_age = await self._safe_call(self.get_fitness_age, target_date)
        fitness_age = fitness_age or {}

        # ========== Goals ==========
        active_goals = await self._safe_call(self.get_goals, "active")
        future_goals = await self._safe_call(self.get_goals, "future")
        past_goals = await self._safe_call(self.get_goals, "past")

        # ========== Badges & Gamification ==========
        badges = await self._safe_call(self.get_earned_badges)
        badges = badges or []
        user_points = sum(
            badge.get("badgePoints", 0) * badge.get("badgeEarnedNumber", 1)
            for badge in badges
        )
        # Calculate user level from points
        level_points = {
            0: 0, 1: 100, 2: 500, 3: 1000, 4: 2500, 5: 5000,
            6: 10000, 7: 25000, 8: 50000, 9: 100000, 10: 250000,
        }
        user_level = 0
        for level, points in level_points.items():
            if user_points >= points:
                user_level = level

        # ========== Alarms ==========
        alarms = await self._safe_call(self.get_device_alarms)
        next_alarms = self._calculate_next_active_alarms(alarms, timezone)

        # ========== Respiration ==========
        respiration = await self._safe_call(self.get_respiration_data, target_date)
        respiration = respiration or {}

        # ========== SPO2 ==========
        spo2 = await self._safe_call(self.get_spo2_data, target_date)
        spo2 = spo2 or {}

        # ========== Blood Pressure ==========
        blood_pressure_data: dict[str, Any] = {}
        bp_response = await self._safe_call(
            self.get_blood_pressure,
            target_date - timedelta(days=30),
            target_date,
        )
        if bp_response and isinstance(bp_response, dict):
            # Collect all measurements from all summaries
            all_measurements: list[dict[str, Any]] = []
            summaries = bp_response.get("measurementSummaries", [])
            for summary in summaries:
                measurements = summary.get("measurements", [])
                all_measurements.extend(measurements)

            if all_measurements:
                # Find the measurement with the latest timestamp
                latest_bp = max(
                    all_measurements,
                    key=lambda m: m.get("measurementTimestampLocal", ""),
                )
                blood_pressure_data = {
                    "bpSystolic": latest_bp.get("systolic"),
                    "bpDiastolic": latest_bp.get("diastolic"),
                    "bpPulse": latest_bp.get("pulse"),
                    "bpMeasurementTime": latest_bp.get("measurementTimestampLocal"),
                }

        # ========== Menstrual Data ==========
        menstrual_data = await self._safe_call(self.get_menstrual_data, target_date)
        menstrual_data = menstrual_data or {}

        # ========== Build Flat Result ==========
        result: dict[str, Any] = {
            # From summary (spread all keys)
            **summary_raw,
            # Weekly averages
            "yesterdaySteps": yesterday_steps,
            "yesterdayDistance": yesterday_distance,
            "weeklyStepAvg": weekly_step_avg,
            "weeklyDistanceAvg": weekly_distance_avg,
            # Body composition
            **body_composition,
            # Activities
            "lastActivities": activities_by_date or [],
            "lastActivity": last_activity,
            # Workouts
            "workouts": workouts,
            "lastWorkout": workouts[0] if workouts else {},
            # Sleep
            "sleepScore": sleep_score,
            "sleepTimeSeconds": sleep_time_seconds,
            "deepSleepSeconds": deep_sleep_seconds,
            "lightSleepSeconds": light_sleep_seconds,
            "remSleepSeconds": rem_sleep_seconds,
            "awakeSleepSeconds": awake_sleep_seconds,
            # Stress (spread all keys)
            **stress_data,
            # HRV
            "hrvStatus": hrv_status,
            # Body Battery (spread if dict)
            **(body_battery_data if isinstance(body_battery_data, dict) else {}),
            # Hydration
            **hydration,
            # Training
            "trainingReadiness": training_readiness or {},
            "morningTrainingReadiness": morning_training_readiness or {},
            "trainingStatus": training_status or {},
            "lactateThreshold": lactate_threshold or {},
            # Scores
            "enduranceScore": endurance_score,
            "hillScore": hill_score,
            # Fitness age (spread)
            **fitness_age,
            # Goals
            "activeGoals": active_goals or [],
            "futureGoals": future_goals or [],
            "goalsHistory": (past_goals or [])[:10],
            # Gamification
            "badges": badges,
            "userPoints": user_points,
            "userLevel": user_level,
            # Alarms
            "nextAlarm": next_alarms,
            # Respiration
            **respiration,
            # SPO2
            **spo2,
            # Blood Pressure
            **blood_pressure_data,
            # Menstrual
            "menstrualData": menstrual_data,
        }

        return result

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
            "MONDAY": 1, "TUESDAY": 2, "WEDNESDAY": 3, "THURSDAY": 4,
            "FRIDAY": 5, "SATURDAY": 6, "SUNDAY": 7,
        }

        try:
            tz = ZoneInfo(timezone)
            now = datetime.now(tz)
        except Exception as err:
            _LOGGER.warning("Invalid timezone '%s': %s", timezone, err)
            return None

        _LOGGER.debug(
            "Processing %d alarms at %s (%s)",
            len(alarms), now.isoformat(), timezone
        )

        for alarm_setting in alarms:
            # Only process active alarms
            alarm_mode = alarm_setting.get("alarmMode")
            if alarm_mode != "ON":
                _LOGGER.debug(
                    "Skipping alarm %s (mode=%s)",
                    alarm_setting.get("alarmId"), alarm_mode
                )
                continue

            # alarmTime is minutes from midnight
            alarm_minutes = alarm_setting.get("alarmTime", 0)
            alarm_days = alarm_setting.get("alarmDays", [])

            _LOGGER.debug(
                "Processing alarm %s: time=%d min, days=%s",
                alarm_setting.get("alarmId"), alarm_minutes, alarm_days
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
                        day, alarm.isoformat(), days_ahead
                    )

                else:
                    _LOGGER.debug("Unknown alarm day type: %s", day)

        if not active_alarms:
            _LOGGER.debug("No active alarms found")
            return None

        sorted_alarms = sorted(active_alarms)
        _LOGGER.debug("Active alarms: %s", sorted_alarms)
        return sorted_alarms

    # ========== Core Group ==========

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

    # ========== Activity Group ==========

    async def get_activities(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent activities."""
        params = {"limit": limit, "start": 0}
        data = await self._request("GET", ACTIVITIES_URL, params=params)
        return data if isinstance(data, list) else []

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

    async def get_sleep_data(self, target_date: date | None = None) -> dict[str, Any]:
        """Get sleep data for a date."""
        if target_date is None:
            target_date = date.today()

        profile = await self.get_user_profile()
        url = f"{SLEEP_URL}/{profile.display_name}"
        params = {"date": target_date.isoformat(), "nonSleepBufferMinutes": 60}
        data = await self._request("GET", url, params=params)
        return data if isinstance(data, dict) else {}

    async def get_stress_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get stress data for a date."""
        if target_date is None:
            target_date = date.today()

        url = f"{STRESS_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_hrv_data(self, target_date: date | None = None) -> dict[str, Any]:
        """Get HRV data for a date."""
        if target_date is None:
            target_date = date.today()

        url = f"{HRV_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_body_battery(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get body battery data for a date."""
        if target_date is None:
            target_date = date.today()

        params = {
            "startDate": target_date.isoformat(),
            "endDate": target_date.isoformat(),
        }
        data = await self._request("GET", BODY_BATTERY_URL, params=params)
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

    # ========== Device Group ==========

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get list of connected Garmin devices."""
        data = await self._request("GET", DEVICES_URL)
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

    # ========== Raw API Methods (return dict for flat data) ==========

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

    async def _get_stress_data_raw(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get stress data as raw dict for flat data output."""
        if target_date is None:
            target_date = date.today()

        url = f"{STRESS_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
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

    async def _get_body_battery_raw(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get body battery data as raw dict for flat data output."""
        if target_date is None:
            target_date = date.today()

        params = {
            "startDate": target_date.isoformat(),
            "endDate": target_date.isoformat(),
        }
        data = await self._request("GET", BODY_BATTERY_URL, params=params)
        return data if isinstance(data, dict) else {}

    # ========== New API Methods ==========

    async def get_device_alarms(self) -> list[dict[str, Any]]:
        """Get device alarms."""
        data = await self._request("GET", DEVICE_ALARMS_URL)
        return data if isinstance(data, list) else []

    async def get_morning_training_readiness(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get morning training readiness (AFTER_WAKEUP_RESET context)."""
        if target_date is None:
            target_date = date.today()

        url = f"{MORNING_TRAINING_READINESS_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_respiration_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get daily respiration data."""
        if target_date is None:
            target_date = date.today()

        url = f"{RESPIRATION_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

    async def get_spo2_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Get daily SpO2 data."""
        if target_date is None:
            target_date = date.today()

        url = f"{SPO2_URL}/{target_date.isoformat()}"
        data = await self._request("GET", url)
        return data if isinstance(data, dict) else {}

