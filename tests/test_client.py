"""Tests for GarminClient."""

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
                "displayName": "testuser",
                "userId": 12345,
                "profileImageUrlMedium": "https://example.com/image.jpg",
            },
        )

        auth = GarminAuth(session, oauth2_token="token")
        client = GarminClient(session, auth)
        profile = await client.get_user_profile()

        assert profile.display_name == "testuser"
        assert profile.user_id == 12345

    async def test_get_activities(self, session, mock_aioresponse):
        """Test get activities."""
        mock_aioresponse.get(
            ACTIVITIES_URL,
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

        auth = GarminAuth(session, oauth2_token="token")
        client = GarminClient(session, auth)
        activities = await client.get_activities(limit=10)

        assert len(activities) == 1
        assert activities[0].activity_name == "Morning Run"
        assert activities[0].distance == 5000.0

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

        auth = GarminAuth(session, oauth2_token="token")
        client = GarminClient(session, auth)
        devices = await client.get_devices()

        assert len(devices) == 1
        assert devices[0].display_name == "Forerunner 955"
        assert devices[0].battery_level == 85
