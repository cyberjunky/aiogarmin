"""Constants for aiogarmin."""

# Garmin SSO URLs
GARMIN_SSO_URL = "https://sso.garmin.com/sso"
GARMIN_SSO_SIGNIN = f"{GARMIN_SSO_URL}/signin"
GARMIN_SSO_MFA = f"{GARMIN_SSO_URL}/verifyMFA/loginEnterMfaCode"

# Garmin Connect API URLs (using connectapi.garmin.com like garth does)
GARMIN_CONNECT_API = "https://connectapi.garmin.com"

# User/Profile endpoints
USER_PROFILE_URL = f"{GARMIN_CONNECT_API}/userprofile-service/socialProfile"
USER_SUMMARY_URL = f"{GARMIN_CONNECT_API}/usersummary-service/usersummary/daily"

# Activity endpoints
ACTIVITIES_URL = (
    f"{GARMIN_CONNECT_API}/activitylist-service/activities/search/activities"
)
ACTIVITIES_BY_DATE_URL = f"{GARMIN_CONNECT_API}/activitylist-service/activities/byDate"
ACTIVITY_DETAILS_URL = f"{GARMIN_CONNECT_API}/activity-service/activity"
WORKOUTS_URL = f"{GARMIN_CONNECT_API}/workout-service/workouts"

# Wellness endpoints
HRV_URL = f"{GARMIN_CONNECT_API}/hrv-service/hrv"
SLEEP_URL = f"{GARMIN_CONNECT_API}/wellness-service/wellness/dailySleepData"
HYDRATION_URL = f"{GARMIN_CONNECT_API}/usersummary-service/usersummary/hydration/daily"
DAILY_STEPS_URL = f"{GARMIN_CONNECT_API}/usersummary-service/stats/steps/daily"

# Body composition endpoints
BODY_COMPOSITION_URL = f"{GARMIN_CONNECT_API}/weight-service/weight/range"

# Fitness/Training endpoints
TRAINING_READINESS_URL = (
    f"{GARMIN_CONNECT_API}/metrics-service/metrics/trainingreadiness"
)
MORNING_TRAINING_READINESS_URL = (
    f"{GARMIN_CONNECT_API}/metrics-service/metrics/trainingreadiness/report"
)
TRAINING_STATUS_URL = (
    f"{GARMIN_CONNECT_API}/metrics-service/metrics/trainingstatus/aggregated"
)
ENDURANCE_SCORE_URL = f"{GARMIN_CONNECT_API}/metrics-service/metrics/endurancescore"
HILL_SCORE_URL = f"{GARMIN_CONNECT_API}/metrics-service/metrics/hillscore"
FITNESS_AGE_URL = f"{GARMIN_CONNECT_API}/fitnessage-service/fitnessage"
LACTATE_THRESHOLD_URL = (
    f"{GARMIN_CONNECT_API}/biometric-service/biometric/latestLactateThreshold"
)

# Device endpoints
DEVICES_URL = f"{GARMIN_CONNECT_API}/device-service/deviceregistration/devices"
DEVICE_ALARMS_URL = f"{GARMIN_CONNECT_API}/device-service/devices/alarms"

# Respiration and SPO2 endpoints
RESPIRATION_URL = f"{GARMIN_CONNECT_API}/wellness-service/wellness/daily/respiration"
SPO2_URL = f"{GARMIN_CONNECT_API}/wellness-service/wellness/dailySpo2"


# Goals & Gamification endpoints
GOALS_URL = f"{GARMIN_CONNECT_API}/goal-service/goal/goals"
BADGES_URL = f"{GARMIN_CONNECT_API}/badge-service/badge/earned"

# Gear endpoints
GEAR_URL = f"{GARMIN_CONNECT_API}/gear-service/gear/filterGear"
GEAR_BASE_URL = f"{GARMIN_CONNECT_API}/gear-service/gear"
GEAR_STATS_URL = f"{GARMIN_CONNECT_API}/gear-service/gear/stats"
GEAR_DEFAULTS_URL = f"{GARMIN_CONNECT_API}/gear-service/gear/user"

# Health endpoints
BLOOD_PRESSURE_URL = f"{GARMIN_CONNECT_API}/bloodpressure-service/bloodpressure/range"
BLOOD_PRESSURE_SET_URL = f"{GARMIN_CONNECT_API}/bloodpressure-service/bloodpressure"
MENSTRUAL_URL = f"{GARMIN_CONNECT_API}/periodichealth-service/menstrualcycle/dayview"
MENSTRUAL_CALENDAR_URL = (
    f"{GARMIN_CONNECT_API}/periodichealth-service/menstrualcycle/calendar"
)

# Upload/Write endpoints
UPLOAD_URL = f"{GARMIN_CONNECT_API}/upload-service/upload"
ACTIVITY_CREATE_URL = f"{GARMIN_CONNECT_API}/activity-service/activity"
GEAR_LINK_URL = f"{GARMIN_CONNECT_API}/gear-service/gear/link"

# Default headers
DEFAULT_HEADERS = {
    "User-Agent": "GCM-iOS-5.7.2.1",
    "Accept": "application/json",
}

# China domain
GARMIN_CN_CONNECT_API = "https://connectapi.garmin.cn"
