"""Tests for GarminClient."""

import re
from datetime import date, timedelta

import pytest

from aiogarmin import GarminAuth, GarminClient
from aiogarmin.const import (
    ACTIVITIES_URL,
    DEVICES_URL,
    USER_PROFILE_URL,
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
