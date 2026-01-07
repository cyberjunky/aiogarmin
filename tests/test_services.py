"""Tests for service methods."""

import pytest

from aiogarmin import GarminAuth, GarminClient


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
