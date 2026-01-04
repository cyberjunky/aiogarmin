"""Constants for aiogarmin."""

# Garmin SSO URLs
GARMIN_SSO_URL = "https://sso.garmin.com/sso"
GARMIN_SSO_SIGNIN = f"{GARMIN_SSO_URL}/signin"
GARMIN_SSO_MFA = f"{GARMIN_SSO_URL}/verifyMFA/loginEnterMfaCode"

# Garmin Connect API URLs (using connectapi.garmin.com like garth does)
GARMIN_CONNECT_API = "https://connectapi.garmin.com"

# API endpoints (based on python-garminconnect library)
USER_PROFILE_URL = f"{GARMIN_CONNECT_API}/userprofile-service/socialProfile"
USER_SUMMARY_URL = f"{GARMIN_CONNECT_API}/usersummary-service/usersummary/daily"
ACTIVITIES_URL = (
    f"{GARMIN_CONNECT_API}/activitylist-service/activities/search/activities"
)
ACTIVITY_DETAILS_URL = f"{GARMIN_CONNECT_API}/activity-service/activity"

# Wellness endpoints
BODY_BATTERY_URL = f"{GARMIN_CONNECT_API}/wellness-service/wellness/bodyBattery"
HRV_URL = f"{GARMIN_CONNECT_API}/hrv-service/hrv"
SLEEP_URL = f"{GARMIN_CONNECT_API}/wellness-service/wellness/dailySleepData"
STRESS_URL = f"{GARMIN_CONNECT_API}/wellness-service/wellness/dailyStress"

# Device endpoints
DEVICES_URL = f"{GARMIN_CONNECT_API}/device-service/deviceregistration/devices"

# Default headers
DEFAULT_HEADERS = {
    "User-Agent": "GCM-iOS-5.7.2.1",
    "Accept": "application/json",
}

# China domain
GARMIN_CN_CONNECT_API = "https://connectapi.garmin.cn"
