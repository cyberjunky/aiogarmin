# aiogarmin

Async Python client for Garmin Connect API, designed for Home Assistant integration.

## Features

- Fully async using aiohttp
- Supports MFA authentication
- Token-based auth (no stored credentials)
- Websession injection for Home Assistant compatibility
- Pydantic models for API responses

## Installation

```bash
pip install aiogarmin
```

## Usage

```python
import aiohttp
from aiogarmin import GarminClient, GarminAuth

async with aiohttp.ClientSession() as session:
    # Login with credentials (one-time)
    auth = GarminAuth(session)
    result = await auth.login("email@example.com", "password")
    
    if result.mfa_required:
        # Handle MFA
        mfa_code = input("Enter MFA code: ")
        result = await auth.complete_mfa(mfa_code)
    
    # Save tokens for future use
    tokens = result.tokens
    
    # Use client for API calls
    client = GarminClient(session, auth)
    summary = await client.get_user_summary()
```

## For Home Assistant

This library is designed to work with Home Assistant's websession:

```python
from homeassistant.helpers.aiohttp_client import async_get_clientsession

session = async_get_clientsession(hass)
auth = GarminAuth(session, oauth1_token=stored_token1, oauth2_token=stored_token2)
client = GarminClient(session, auth)
```

## Acknowledgements

This library is inspired by and builds upon great work from:

- **[garth](https://github.com/matin/garth)** by [@matin](https://github.com/matin) - Garmin SSO auth + Connect Python client

Special thanks to Matin for reverse-engineering the Garmin Connect authentication flow and making it available to the community.

## License

MIT
