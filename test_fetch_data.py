#!/usr/bin/env python3
"""Test script to inspect aiogarmin data returned by fetch methods.

Usage:
    python test_fetch_data.py

You need to set environment variables or edit credentials below.
Tokens are saved to .garmin_tokens.json for subsequent runs.
"""

import asyncio
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from pprint import pprint

import aiohttp

from aiogarmin import GarminAuth, GarminClient


# === CREDENTIALS ===
# Set these via environment variables or edit directly
EMAIL = os.getenv("GARMIN_EMAIL", "your-email@example.com")
PASSWORD = os.getenv("GARMIN_PASSWORD", "your-password")

# Token storage file
TOKEN_FILE = Path(__file__).parent / ".garmin_tokens.json"


def load_tokens() -> tuple[dict | None, dict | None]:
    """Load saved tokens from file."""
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE) as f:
                data = json.load(f)
            print(f"Loaded tokens from {TOKEN_FILE}")
            return data.get("oauth1"), data.get("oauth2")
        except (json.JSONDecodeError, OSError) as e:
            print(f"Could not load tokens: {e}")
    return None, None


def save_tokens(oauth1: dict | None, oauth2: dict | None):
    """Save tokens to file for reuse."""
    with open(TOKEN_FILE, "w") as f:
        json.dump({"oauth1": oauth1, "oauth2": oauth2}, f, indent=2)
    print(f"Tokens saved to {TOKEN_FILE}")


def json_serial(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def print_section(title: str, data: dict | list | None):
    """Pretty print a data section."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    if data is None:
        print("  (No data)")
    elif isinstance(data, dict):
        # Print keys and their types/values
        for key, value in sorted(data.items()):
            val_type = type(value).__name__
            if isinstance(value, (datetime, date)):
                print(f"  {key}: {value.isoformat()} ({val_type})")
            elif isinstance(value, dict):
                print(f"  {key}: {{...}} ({len(value)} keys)")
            elif isinstance(value, list):
                print(f"  {key}: [...] ({len(value)} items)")
            elif isinstance(value, str) and len(value) > 50:
                print(f"  {key}: '{value[:50]}...' ({val_type})")
            else:
                print(f"  {key}: {value} ({val_type})")
    else:
        pprint(data)


async def main():
    """Fetch and display all data from aiogarmin."""
    # Load saved tokens
    oauth1_token, oauth2_token = load_tokens()

    async with aiohttp.ClientSession() as session:
        # Initialize auth with saved tokens
        auth = GarminAuth(
            session,
            oauth1_token=oauth1_token,
            oauth2_token=oauth2_token,
        )

        # Login if no tokens
        if not auth.oauth2_token:
            # Get credentials interactively if not set
            email = EMAIL
            password = PASSWORD
            
            if email == "your-email@example.com":
                email = input("Garmin Email: ").strip()
            if password == "your-password":
                import getpass
                password = getpass.getpass("Garmin Password: ")
            
            print(f"Logging in as {email}...")
            
            try:
                from aiogarmin.exceptions import GarminMFARequired
                result = await auth.login(email, password)
            except GarminMFARequired:
                # MFA required - prompt for code
                print("MFA required!")
                mfa_code = input("Enter MFA code: ").strip()
                result = await auth.complete_mfa(mfa_code)
            
            if not result.success:
                print(f"Login failed: {result}")
                return
            print(f"Logged in as: {result.display_name}")
            # Save tokens for next time
            save_tokens(auth.oauth1_token, auth.oauth2_token)

        # Create client
        client = GarminClient(session, auth)

        today = date.today()
        yesterday = today - timedelta(days=1)

        # === FETCH CORE DATA ===
        print("\n" + "=" * 60)
        print("  FETCHING CORE DATA (today)")
        print("=" * 60)
        core_data = await client.fetch_core_data(today)
        print_section("Core Data", core_data)

        # === FETCH ACTIVITY DATA ===
        print("\n" + "=" * 60)
        print("  FETCHING ACTIVITY DATA")
        print("=" * 60)
        activity_data = await client.fetch_activity_data(today)
        print_section("Activity Data", activity_data)

        # Check lastActivity specifically
        if "lastActivity" in activity_data:
            print("\n  --- Last Activity Details ---")
            last_act = activity_data["lastActivity"]
            if isinstance(last_act, dict):
                for k, v in last_act.items():
                    if isinstance(v, (datetime, date)):
                        print(f"    {k}: {v.isoformat()} ({type(v).__name__})")
                    elif k not in ("polyline", "hrTimeInZones"):
                        print(f"    {k}: {v}")

        # === FETCH TRAINING DATA ===
        print("\n" + "=" * 60)
        print("  FETCHING TRAINING DATA")
        print("=" * 60)
        training_data = await client.fetch_training_data(today)
        print_section("Training Data", training_data)

        # === FETCH BODY DATA ===
        print("\n" + "=" * 60)
        print("  FETCHING BODY DATA")
        print("=" * 60)
        body_data = await client.fetch_body_data(today)
        print_section("Body Data", body_data)

        # === FETCH GOALS DATA ===
        print("\n" + "=" * 60)
        print("  FETCHING GOALS DATA")
        print("=" * 60)
        goals_data = await client.fetch_goals_data()
        print_section("Goals Data", goals_data)

        # === FETCH GEAR DATA ===
        print("\n" + "=" * 60)
        print("  FETCHING GEAR DATA")
        print("=" * 60)
        gear_data = await client.fetch_gear_data()
        print_section("Gear Data", gear_data)

        # === SHOW NULL/NONE VALUES ===
        print("\n" + "=" * 60)
        print("  VALUES THAT ARE None (may need historical fetch)")
        print("=" * 60)
        
        all_data = {
            "core": core_data,
            "activity": activity_data,
            "training": training_data,
            "body": body_data,
        }

        for section, data in all_data.items():
            if isinstance(data, dict):
                none_keys = [k for k, v in data.items() if v is None]
                if none_keys:
                    print(f"\n  {section.upper()}:")
                    for k in sorted(none_keys):
                        print(f"    - {k}")

        # === SAVE FULL DATA TO JSON ===
        output_file = "garmin_data_dump.json"
        with open(output_file, "w") as f:
            json.dump(all_data, f, indent=2, default=json_serial)
        print(f"\n\nFull data saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
