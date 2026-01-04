"""Pydantic models for Garmin Connect API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GarminModel(BaseModel):
    """Base model that ignores unknown fields."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AuthResult(BaseModel):
    """Result of authentication attempt."""

    success: bool
    oauth1_token: dict | None = None
    oauth2_token: dict | None = None
    display_name: str | None = None
    user_id: str | None = None


class UserProfile(GarminModel):
    """User profile information."""

    id: int
    display_name: str = Field(alias="displayName")
    profile_image_url: str | None = Field(default=None, alias="profileImageUrlMedium")


class UserSummary(GarminModel):
    """Daily user summary."""

    total_steps: int | None = Field(default=None, alias="totalSteps")
    total_distance_meters: float | None = Field(
        default=None, alias="totalDistanceMeters"
    )
    active_calories: int | None = Field(default=None, alias="activeKilocalories")
    highly_active_seconds: int | None = Field(default=None, alias="highlyActiveSeconds")
    sedentary_seconds: int | None = Field(default=None, alias="sedentarySeconds")
    floors_ascended: int | None = Field(default=None, alias="floorsAscended")
    floors_descended: int | None = Field(default=None, alias="floorsDescended")
    min_heart_rate: int | None = Field(default=None, alias="minHeartRate")
    max_heart_rate: int | None = Field(default=None, alias="maxHeartRate")
    resting_heart_rate: int | None = Field(default=None, alias="restingHeartRate")
    avg_stress_level: int | None = Field(default=None, alias="averageStressLevel")
    max_stress_level: int | None = Field(default=None, alias="maxStressLevel")
    body_battery_charged: int | None = Field(
        default=None, alias="bodyBatteryChargedValue"
    )
    body_battery_drained: int | None = Field(
        default=None, alias="bodyBatteryDrainedValue"
    )


class Activity(GarminModel):
    """Activity summary."""

    activity_id: int = Field(alias="activityId")
    activity_name: str = Field(alias="activityName")
    activity_type: dict | None = Field(default=None, alias="activityType")
    start_time_local: datetime | None = Field(default=None, alias="startTimeLocal")
    distance: float | None = Field(default=None)
    duration: float | None = Field(default=None)
    average_hr: int | None = Field(default=None, alias="averageHR")
    max_hr: int | None = Field(default=None, alias="maxHR")
    calories: int | None = Field(default=None)


class BodyBattery(GarminModel):
    """Body battery reading."""

    timestamp: datetime | None = Field(default=None, alias="startTimestampGMT")
    charged: int | None = Field(default=None, alias="charged")
    drained: int | None = Field(default=None, alias="drained")
    level: int | None = Field(default=None, alias="bodyBatteryLevel")


class SleepData(GarminModel):
    """Sleep data summary."""

    sleep_start: datetime | None = Field(default=None, alias="sleepStartTimestampGMT")
    sleep_end: datetime | None = Field(default=None, alias="sleepEndTimestampGMT")
    total_sleep_seconds: int | None = Field(default=None, alias="sleepTimeSeconds")
    deep_sleep_seconds: int | None = Field(default=None, alias="deepSleepSeconds")
    light_sleep_seconds: int | None = Field(default=None, alias="lightSleepSeconds")
    rem_sleep_seconds: int | None = Field(default=None, alias="remSleepSeconds")
    awake_seconds: int | None = Field(default=None, alias="awakeSleepSeconds")


class StressData(GarminModel):
    """Stress data summary."""

    overall_stress_level: int | None = Field(default=None, alias="overallStressLevel")
    rest_stress_duration: int | None = Field(default=None, alias="restStressDuration")
    activity_stress_duration: int | None = Field(
        default=None, alias="activityStressDuration"
    )
    low_stress_duration: int | None = Field(default=None, alias="lowStressDuration")
    medium_stress_duration: int | None = Field(
        default=None, alias="mediumStressDuration"
    )
    high_stress_duration: int | None = Field(default=None, alias="highStressDuration")


class HRVData(GarminModel):
    """HRV (Heart Rate Variability) data."""

    hrv_value: int | None = Field(default=None, alias="hrvValue")
    baseline_low: int | None = Field(default=None, alias="baselineLowUpper")
    baseline_balanced: int | None = Field(default=None, alias="baselineBalancedLower")
    status: str | None = Field(default=None)


class Device(GarminModel):
    """Garmin device information."""

    device_id: int | None = Field(default=None, alias="deviceId")
    display_name: str | None = Field(default=None, alias="displayName")
    device_type_name: str | None = Field(default=None, alias="deviceTypeName")
    # Battery fields - may or may not exist in API
    battery_level: int | None = Field(default=None, alias="batteryLevel")
    battery_status: str | None = Field(default=None, alias="batteryStatus")
