# aiogarmin

Async Python client for Garmin Connect API, designed for Home Assistant integration.

## Features

- **Fully async** and native React API compatible via `/gc-api/`
- **Cloudflare & WAF Evasion** using perfectly spoofed TLS fingerprints securely backed by `curl_cffi`
- **MFA authentication** with proxy-evasion support and Turnstile bypass
- **JWT Token-based auth** - credentials logically map to `GARMIN-SSO-GUID` sessions natively and save permanently
- **Websession injection** for Home Assistant compatibility
- **Retry with backoff** for rate limits (429) and server errors (5xx)
- **Midnight fallback** - automatically uses yesterday's data when today isn't ready yet
- **Coordinator-based fetch** - optimized data fetching for Home Assistant multi-coordinator pattern
- **Data transformations** - automatic unit conversions (seconds→minutes, grams→kg)

## Installation

```bash
pip install aiogarmin
```

## Usage

```python
import asyncio
import aiohttp
from datetime import date
from aiogarmin import GarminClient, GarminAuth

async def main():
    async with aiohttp.ClientSession() as session:
        # Initialize the modern JWT session architecture
        auth = GarminAuth()
        
        # Load seamless session from disk to completely evade rate limits natively
        if not auth.load_session(".garmin_tokens.json"):
            # Execute Native Authenticator if no cached JWT_WEB context exists
            await auth.login("email@example.com", "password")
            
            # Handle MFA securely natively
            if not auth.is_authenticated:
                mfa_code = input("Enter MFA code: ")
                await auth.complete_mfa(mfa_code)
                
            # Permanently cache the native TLS & Cookie dictionaries to disk
            auth.save_session(".garmin_tokens.json")
        
        # Initialize client connecting accurately to React gc-api routing
        client = GarminClient(session, auth)
        
        today = date.today()
        # Coordinator-based fetch methods natively pulling from React interface
        core_data = await client.fetch_core_data(today)      # Steps, HR, sleep, stress
        body_data = await client.fetch_body_data(today)      # Weight, body composition, fitness age
        activity_data = await client.fetch_activity_data(today)  # Activities, workouts
        training_data = await client.fetch_training_data(today)  # HRV, training status
        goals_data = await client.fetch_goals_data()    # Goals, badges
        gear_data = await client.fetch_gear_data()      # Gear, device alarms
```

## For Home Assistant

This library is designed to work with Home Assistant's websession and multi-coordinator pattern:

```python
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import json

session = async_get_clientsession(hass)

# Load cached tokens from generic config entry natively
auth = GarminAuth()
auth.jwt_web = entry.data.get("jwt_web")
auth.csrf_token = entry.data.get("csrf_token")
auth.cs.cookies.update(entry.data.get("cookies", {}))

client = GarminClient(session, auth)

# Each coordinator fetches its own data seamlessly routing to gc-api
core_data = await client.fetch_core_data(target_date=date.today())
body_data = await client.fetch_body_data(target_date=date.today())
```

## Coordinator Fetch Methods

Optimized methods that group related API calls for Home Assistant coordinators:

| Method | API Calls | Data Returned |
| ------ | --------- | ------------- |
| `fetch_core_data()` | 3 | Steps, distance, calories, HR, stress, sleep, body battery, SPO2 |
| `fetch_body_data()` | 3 | Weight, BMI, body fat, hydration, fitness age |
| `fetch_activity_data()` | 4+ | Activities, workouts, HR zones, polylines |
| `fetch_training_data()` | 7 | Training readiness, status, HRV, lactate, endurance/hill scores |
| `fetch_goals_data()` | 4 | Goals (active/future/history), badges, user level |
| `fetch_gear_data()` | 4+ | Gear items, stats, device alarms |
| `fetch_blood_pressure_data()` | 1 | Blood pressure measurements |
| `fetch_menstrual_data()` | 2 | Menstrual cycle data |

## Individual API Methods

Low-level methods used by coordinator fetch methods (all return raw `dict` or `list[dict]`):

| Method | Description |
| ------ | ----------- |
| `get_user_profile()` | User profile info |
| `get_user_summary()` | Daily summary (steps, HR, stress, body battery) |
| `get_daily_steps()` | Steps for date range |
| `get_body_composition()` | Weight, BMI, body fat |
| `get_fitness_age()` | Fitness age metrics |
| `get_hydration_data()` | Daily hydration |
| `get_activities_by_date()` | Activities in date range |
| `get_activity_details()` | Detailed activity with polyline |
| `get_activity_hr_in_timezones()` | HR time in zones |
| `get_workouts()` | Scheduled workouts |
| `get_training_readiness()` | Training readiness score |
| `get_training_status()` | Training status |
| `get_morning_training_readiness()` | Morning readiness |
| `get_endurance_score()` | Endurance score |
| `get_hill_score()` | Hill score |
| `get_lactate_threshold()` | Lactate threshold |
| `get_hrv_data()` | Heart rate variability |
| `get_goals()` | User goals by status |
| `get_earned_badges()` | Earned badges |
| `get_gear()` | User gear items |
| `get_gear_stats()` | Gear statistics |
| `get_gear_defaults()` | Default gear settings |
| `get_devices()` | Connected devices |
| `get_device_alarms()` | Device alarms |
| `get_device_settings()` | Device settings |
| `get_blood_pressure()` | Blood pressure data |
| `get_menstrual_data()` | Menstrual cycle data |
| `get_menstrual_calendar()` | Menstrual calendar |

## Data Transformations

The library automatically adds computed fields for convenience:

- **Time conversions**: `sleepTimeSeconds` → `sleepTimeMinutes`
- **Activity time**: `highlyActiveSeconds` → `highlyActiveMinutes`
- **Weight**: `weight` (grams) → `weightKg`
- **Stress**: `stressQualifier` → `stressQualifierText` (capitalized)
- **Nested flattening**: HRV status, training readiness, scores

## Acknowledgements

This library is inspired by and builds upon great work from:

**[garth](https://github.com/matin/garth)** - The original Garmin SSO auth & Connect Python client architecture.

Special thanks to [Matin](https://github.com/matin) for paving the authentication flow and making it available to the community before the `/gc-api/` migration.

## License

MIT
