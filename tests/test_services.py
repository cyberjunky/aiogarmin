"""Tests for service methods (upload, body comp, BP, gear)."""

import pytest

from aiogarmin import GarminAuth, GarminClient
from aiogarmin.const import (
    GEAR_LINK_URL,
    GEAR_URL,
    UPLOAD_URL,
)


class TestServiceMethods:
    """Tests for service-related client methods."""

    async def test_upload_activity_file_not_found(self, session):
        """Test upload_activity with non-existent file."""
        auth = GarminAuth(session, oauth2_token="token")
        client = GarminClient(session, auth)

        with pytest.raises(FileNotFoundError):
            await client.upload_activity("/nonexistent/file.fit")

    async def test_upload_activity_invalid_format(self, session, tmp_path):
        """Test upload_activity with unsupported file format."""
        # Create a temporary file with wrong extension
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        auth = GarminAuth(session, oauth2_token="token")
        client = GarminClient(session, auth)

        with pytest.raises(ValueError, match="Invalid file format"):
            await client.upload_activity(str(test_file))

    async def test_upload_activity_success(self, session, mock_aioresponse, tmp_path):
        """Test successful activity upload."""
        # Create a valid FIT file
        test_file = tmp_path / "test.fit"
        test_file.write_bytes(b"\x0e\x10\x00\x00" + b"\x00" * 100)  # Minimal FIT header

        mock_aioresponse.post(
            UPLOAD_URL,
            payload={
                "detailedImportResult": {
                    "uploadId": 12345,
                    "successes": [{"internalId": 1}],
                    "failures": [],
                }
            },
            status=202,
        )

        auth = GarminAuth(session, oauth2_token="token")
        client = GarminClient(session, auth)
        result = await client.upload_activity(str(test_file))

        assert result["detailedImportResult"]["uploadId"] == 12345

    async def test_get_gear(self, session, mock_aioresponse):
        """Test get gear list."""
        mock_aioresponse.get(
            GEAR_URL,
            payload=[
                {
                    "uuid": "abc123",
                    "displayName": "Running Shoes",
                    "gearTypePk": 1,
                    "gearStatusName": "active",
                    "customMakeModel": "Nike Pegasus",
                }
            ],
        )

        auth = GarminAuth(session, oauth2_token="token")
        client = GarminClient(session, auth)
        gear = await client.get_gear()

        assert len(gear) == 1
        assert gear[0]["displayName"] == "Running Shoes"

    async def test_add_gear_to_activity(self, session, mock_aioresponse):
        """Test adding gear to activity."""
        mock_aioresponse.put(
            GEAR_LINK_URL,
            payload={"success": True},
        )

        auth = GarminAuth(session, oauth2_token="token")
        client = GarminClient(session, auth)
        result = await client.add_gear_to_activity("abc123", 12345678)

        assert result.get("success") is True
