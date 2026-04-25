"""Intervals.icu API client.

Docs: https://intervals.icu/api
Auth: HTTP Basic, username "API_KEY", password = your API key.
"""
import base64
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import Config

BASE = "https://intervals.icu/api/v1"


def _headers() -> dict:
    token = base64.b64encode(f"API_KEY:{Config.INTERVALS_API_KEY}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _date_range(days: int) -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


async def get_recent_activities(days: int = 7) -> list[dict]:
    """Recent activities, trimmed to fields the coach actually needs."""
    oldest, newest = _date_range(days)
    url = f"{BASE}/athlete/{Config.INTERVALS_ATHLETE_ID}/activities"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            url, headers=_headers(), params={"oldest": oldest, "newest": newest}
        )
        r.raise_for_status()
        activities = r.json()

    return [
        {
            "date": a.get("start_date_local", "")[:10],
            "name": a.get("name"),
            "type": a.get("type"),
            "duration_min": round((a.get("moving_time") or 0) / 60),
            "distance_km": round((a.get("distance") or 0) / 1000, 1),
            "elevation_m": a.get("total_elevation_gain"),
            "avg_power": a.get("icu_average_watts"),
            "norm_power": a.get("icu_weighted_avg_watts"),
            "avg_hr": a.get("average_heartrate"),
            "max_hr": a.get("max_heartrate"),
            "tss": a.get("icu_training_load"),
            "intensity_pct": a.get("icu_intensity"),
            "feel": a.get("feel"),
            "perceived_exertion": a.get("perceived_exertion"),
        }
        for a in activities
    ]


async def get_wellness(days: int = 7) -> list[dict]:
    """Daily wellness rows: includes CTL, ATL, sleep, weight, etc."""
    oldest, newest = _date_range(days)
    url = f"{BASE}/athlete/{Config.INTERVALS_ATHLETE_ID}/wellness"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            url, headers=_headers(), params={"oldest": oldest, "newest": newest}
        )
        r.raise_for_status()
        return r.json()


async def get_current_form() -> dict:
    """Today's CTL/ATL/TSB snapshot."""
    rows = await get_wellness(days=2)
    if not rows:
        return {}
    today = rows[-1]
    ctl = today.get("ctl") or 0
    atl = today.get("atl") or 0
    return {
        "ctl_fitness": round(ctl, 1),
        "atl_fatigue": round(atl, 1),
        "tsb_form": round(ctl - atl, 1),
        "ramp_rate": today.get("rampRate"),
    }


async def get_full_snapshot(days: int = 7) -> dict[str, Any]:
    """Bundle everything Claude needs in one structured object."""
    activities = await get_recent_activities(days)
    wellness = await get_wellness(days)
    form = await get_current_form()
    return {
        "form": form,
        "activities_last_7d": activities,
        "wellness_last_7d": [
            {
                "date": w.get("id"),
                "sleep_hours": w.get("sleepSecs", 0) / 3600 if w.get("sleepSecs") else None,
                "sleep_quality": w.get("sleepQuality"),
                "fatigue": w.get("fatigue"),
                "soreness": w.get("soreness"),
                "stress": w.get("stress"),
                "mood": w.get("mood"),
                "motivation": w.get("motivation"),
                "weight_kg": w.get("weight"),
                "resting_hr": w.get("restingHR"),
                "hrv": w.get("hrv"),
            }
            for w in wellness
        ],
    }
