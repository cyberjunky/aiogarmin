# aiogarmin

Async Python client for Garmin Connect API, designed for Home Assistant integration.

## Features

- **Fully async** using aiohttp
- **MFA authentication** support
- **Token-based auth** - credentials used once, then tokens stored
- **Websession injection** for Home Assistant compatibility
- **Retry with backoff** for rate limits (429) and server errors (5xx)
- **Midnight fallback** - automatically uses yesterday's data when today isn't ready yet

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
    oauth1_token = auth.oauth1_token  # dict
    oauth2_token = auth.oauth2_token  # dict
    
    # Use client for API calls
    client = GarminClient(session, auth)
    
    # get_data() returns flat dict with all data for sensors
    data = await client.get_data()
    print(data["totalSteps"])
    print(data["restingHeartRate"])
```

## For Home Assistant

This library is designed to work with Home Assistant's websession:

```python
from homeassistant.helpers.aiohttp_client import async_get_clientsession

session = async_get_clientsession(hass)

# Load stored token dicts from config entry
oauth1_token = entry.data.get("oauth1_token")
oauth2_token = entry.data.get("oauth2_token")

auth = GarminAuth(session, oauth1_token=oauth1_token, oauth2_token=oauth2_token)
client = GarminClient(session, auth)

# Get all data in flat format for sensors
data = await client.get_data(timezone="Europe/Amsterdam")
```

## API Methods

All methods return raw `dict` or `list[dict]`:

| Method | Description |
|--------|-------------|
| `get_data()` | All data in flat dict (recommended for HA) |
| `get_user_summary()` | Daily summary (steps, calories, HR) |
| `get_activities()` | Recent activities |
| `get_sleep_data()` | Sleep metrics |
| `get_stress_data()` | Stress levels |
| `get_hrv_data()` | Heart rate variability |
| `get_body_battery()` | Body battery levels |
| `get_training_readiness()` | Training readiness |
| `get_devices()` | Connected devices |

## Acknowledgements

This library is inspired by and builds upon great work from:

Matin's **[garth](https://github.com/matin/garth)** - Garmin SSO auth + Connect Python client

Special thanks to him for the Garmin Connect authentication flow and making it available to the community.

## License

MIT
