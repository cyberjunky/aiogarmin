"""Tests for GarminClient."""

import re
from datetime import date, timedelta

import pytest

from aiogarmin import GarminAuth, GarminClient
from aiogarmin.const import (
    ACTIVITIES_URL,
    DAILY_STEPS_URL,
    DEVICES_URL,
    SLEEP_URL,
    USER_PROFILE_URL,
    USER_SUMMARY_URL,
)
from aiogarmin.exceptions import GarminAuthError


class TestGarminClient:
    """Tests for GarminClient class."""

    async def test_request_without_auth(self, session):
        """Test request fails without authentication."""
        auth = GarminAuth(session)
        client = GarminClient(session, auth)

        with pytest.raises(GarminAuthError, match="Not authenticated"):
            await client.get_user_profile()

    async def test_get_user_profile(self, session, mock_aioresponse):
        """Test get user profile."""
        mock_aioresponse.get(
            USER_PROFILE_URL,
            payload={
                "id": 12345,
                "profileId": 67890,
                "displayName": "testuser",
                "profileImageUrlMedium": "https://example.com/image.jpg",
            },
        )

        auth = GarminAuth(session, oauth2_token={"access_token": "token"})
        client = GarminClient(session, auth)
        profile = await client.get_user_profile()

        assert profile.display_name == "testuser"
        assert profile.id == 12345
        assert profile.profile_id == 67890

    async def test_get_activities(self, session, mock_aioresponse):
        """Test get activities."""
        # Use regex pattern to match URL with query params
        pattern = re.compile(rf"^{re.escape(ACTIVITIES_URL)}.*$")
        mock_aioresponse.get(
            pattern,
            payload=[
                {
                    "activityId": 1,
                    "activityName": "Morning Run",
                    "activityType": "running",
                    "startTimeLocal": "2024-01-01T08:00:00",
                    "distance": 5000.0,
                    "duration": 1800.0,
                },
            ],
        )

        auth = GarminAuth(session, oauth2_token={"access_token": "token"})
        client = GarminClient(session, auth)
        end_date = date.today()
        start_date = end_date - timedelta(days=7)
        activities = await client.get_activities_by_date(start_date, end_date)

        assert len(activities) == 1
        assert activities[0]["activityName"] == "Morning Run"
        assert activities[0]["distance"] == 5000.0

    async def test_get_devices(self, session, mock_aioresponse):
        """Test get devices."""
        mock_aioresponse.get(
            DEVICES_URL,
            payload=[
                {
                    "deviceId": 123,
                    "displayName": "Forerunner 955",
                    "deviceTypeName": "forerunner955",
                    "batteryLevel": 85,
                    "batteryStatus": "GOOD",
                },
            ],
        )

        auth = GarminAuth(session, oauth2_token={"access_token": "token"})
        client = GarminClient(session, auth)
        devices = await client.get_devices()

        assert len(devices) == 1
        assert devices[0]["displayName"] == "Forerunner 955"
        assert devices[0]["batteryLevel"] == 85

    async def test_fetch_core_data_sleep_fields(self, session, mock_aioresponse):
        """Test fetch_core_data returns all sleep fields including nap and unmeasurable."""
        # Mock user profile for sleep URL
        mock_aioresponse.get(
            USER_PROFILE_URL,
            payload={
                "id": 12345,
                "profileId": 67890,
                "displayName": "testuser",
            },
        )

        # Mock user summary
        summary_pattern = re.compile(rf"^{re.escape(USER_SUMMARY_URL)}.*$")
        mock_aioresponse.get(
            summary_pattern,
            payload={
                "dailyStepGoal": 10000,
                "totalSteps": 5000,
                "totalDistanceMeters": 4000,
            },
        )

        # Mock daily steps
        steps_pattern = re.compile(rf"^{re.escape(DAILY_STEPS_URL)}.*$")
        mock_aioresponse.get(
            steps_pattern,
            payload=[
                {
                    "totalSteps": 8000,
                    "totalDistance": 6000,
                    "calendarDate": "2026-01-23",
                },
            ],
        )

        # Mock sleep data with all sleep state fields
        sleep_pattern = re.compile(rf"^{re.escape(SLEEP_URL)}.*$")
        mock_aioresponse.get(
            sleep_pattern,
            payload={
                "dailySleepDTO": {
                    "sleepTimeSeconds": 28800,  # 8 hours
                    "deepSleepSeconds": 7200,  # 2 hours
                    "lightSleepSeconds": 14400,  # 4 hours
                    "remSleepSeconds": 5400,  # 1.5 hours
                    "awakeSleepSeconds": 1800,  # 30 min
                    "napTimeSeconds": 3600,  # 1 hour
                    "unmeasurableSleepSeconds": 600,  # 10 min
                    "sleepScores": {
                        "overall": {"value": 85},
                    },
                },
            },
        )

        auth = GarminAuth(session, oauth2_token={"access_token": "token"})
        client = GarminClient(session, auth)
        data = await client.fetch_core_data()

        # Verify all sleep fields are present
        assert data["sleepScore"] == 85
        assert data["sleepTimeSeconds"] == 28800
        assert data["deepSleepSeconds"] == 7200
        assert data["lightSleepSeconds"] == 14400
        assert data["remSleepSeconds"] == 5400
        assert data["awakeSleepSeconds"] == 1800
        assert data["napTimeSeconds"] == 3600
        assert data["unmeasurableSleepSeconds"] == 600

        # Verify computed minutes fields are present
        assert data["sleepTimeMinutes"] == 480  # 28800 / 60
        assert data["deepSleepMinutes"] == 120  # 7200 / 60
        assert data["lightSleepMinutes"] == 240  # 14400 / 60
        assert data["remSleepMinutes"] == 90  # 5400 / 60
        assert data["awakeSleepMinutes"] == 30  # 1800 / 60
        assert data["napTimeMinutes"] == 60  # 3600 / 60
        assert data["unmeasurableSleepMinutes"] == 10  # 600 / 60
