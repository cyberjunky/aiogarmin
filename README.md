# aiogarmin

Async Python client for Garmin Connect API, designed for Home Assistant integration.

## Features

- **Fully async** using aiohttp
- **MFA authentication** with retry support
- **Token-based auth** - credentials used once, then tokens stored
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
import aiohttp
from aiogarmin import GarminClient, GarminAuth

async with aiohttp.ClientSession() as session:
    # Login with credentials (one-time)
    auth = GarminAuth(session)
    result = await auth.login("email@example.com", "password")
    
    if result.mfa_required:
        # Handle MFA - supports retry with correct code
        mfa_code = input("Enter MFA code: ")
        result = await auth.complete_mfa(mfa_code)
    
    # Save tokens for future use
    oauth1_token = auth.oauth1_token  # dict
    oauth2_token = auth.oauth2_token  # dict
    
    # Use client for API calls
    client = GarminClient(session, auth)
    
    # Coordinator-based fetch methods (recommended for HA)
    core_data = await client.fetch_core_data()      # Steps, HR, sleep, stress
    body_data = await client.fetch_body_data()      # Weight, body composition, fitness age
    activity_data = await client.fetch_activity_data()  # Activities, workouts
    training_data = await client.fetch_training_data()  # HRV, training status
    goals_data = await client.fetch_goals_data()    # Goals, badges
    gear_data = await client.fetch_gear_data()      # Gear, device alarms
```

## For Home Assistant

This library is designed to work with Home Assistant's websession and multi-coordinator pattern:

```python
from homeassistant.helpers.aiohttp_client import async_get_clientsession

session = async_get_clientsession(hass)

# Load stored token dicts from config entry
oauth1_token = entry.data.get("oauth1_token")
oauth2_token = entry.data.get("oauth2_token")

auth = GarminAuth(session, oauth1_token=oauth1_token, oauth2_token=oauth2_token)
client = GarminClient(session, auth)

# Each coordinator fetches its own data
core_data = await client.fetch_core_data(target_date=date.today())
body_data = await client.fetch_body_data(target_date=date.today())
```

## Coordinator Fetch Methods

Optimized methods that group related API calls for Home Assistant coordinators:

| Method | API Calls | Data Returned |
|--------|-----------|---------------|
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
|--------|-------------|
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

**[garth](https://github.com/matin/garth)** - Garmin SSO auth + Connect Python client

Special thanks to [Matin](https://github.com/matin) for the Garmin Connect authentication flow and making it available to the community.

## License

MIT
