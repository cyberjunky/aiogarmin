"""Test fixtures for aiogarmin."""

import pytest
import aiohttp
from aioresponses import aioresponses


@pytest.fixture
def mock_aioresponse():
    """Mock aiohttp responses."""
    with aioresponses() as m:
        yield m


@pytest.fixture
async def session():
    """Create aiohttp ClientSession."""
    async with aiohttp.ClientSession() as session:
        yield session
