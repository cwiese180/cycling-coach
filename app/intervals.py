"""Intervals.icu API client.

Smart-split data loading:
- Last 14 days of full activity detail (per-ride metrics)
- Last 90 days summarised by week (TSS, ride count, hours, elevation)
- Full 90-day CTL/ATL/TSB curve (downsampled to weekly)
- Last 14 days of daily wellness rows

Docs: https://intervals.icu/api
Auth: HTTP Basic, username "API_KEY", password = your API key.
"""
import base64
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.config import Config

BASE = "https://intervals.icu/api/v1"

DETAIL_DAYS = 14   # per-ride detail
SUMMARY_DAYS = 90  # weekly summary horizon


def _headers() -> dict:
    token = base64.b64encode(f"API_KEY:{Config.INTERVALS_API_KEY}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _date_range(days: int) -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def _iso_week_key(date_str: str) -> str:
    """Convert YYYY-MM-DD to a 'YYYY-Wnn' ISO week key."""
    if not date_str:
        return ""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    except ValueError:
        return ""


async def _fetch_activities(days: int) -> list[dict]:
    """Raw activities call — used by both detail and summary."""
    oldest, newest = _date_range(days)
    url = f"{BASE}/athlete/{Config.INTERVALS_ATHLETE_ID}/activities"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            url, headers=_headers(), params={"oldest": oldest, "newest": newest}
        )
        r.raise_for_status()
        return r.json()


async def get_recent_activities_detail(days: int = DETAIL_DAYS) -> list[dict]:
    """Per-ride detail for recent activities — what the coach reasons over."""
    activities = await _fetch_activities(days)
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


async def get_weekly_summary(days: int = SUMMARY_DAYS) -> list[dict]:
    """Aggregate the last N days into per-week training summaries.

    One row per ISO week, oldest first. Compact — Claude reads at a glance:
    'Week of x: 5 rides, 8.2h, 320 TSS'.
    """
    activities = await _fetch_activities(days)
    by_week: dict[str, dict] = defaultdict(
        lambda: {
            "ride_count": 0,
            "total_hours": 0.0,
            "total_tss": 0.0,
            "total_distance_km": 0.0,
            "total_elevation_m": 0,
            "hardest_ride_tss": 0,
            "hardest_ride_name": None,
        }
    )

    for a in activities:
        date_str = a.get("start_date_local", "")[:10]
        week = _iso_week_key(date_str)
        if not week:
            continue
        bucket = by_week[week]
        bucket["ride_count"] += 1
        bucket["total_hours"] += (a.get("moving_time") or 0) / 3600
        tss = a.get("icu_training_load") or 0
        bucket["total_tss"] += tss
        bucket["total_distance_km"] += (a.get("distance") or 0) / 1000
        bucket["total_elevation_m"] += a.get("total_elevation_gain") or 0
        if tss > bucket["hardest_ride_tss"]:
            bucket["hardest_ride_tss"] = tss
            bucket["hardest_ride_name"] = a.get("name")

    summary = []
    for week in sorted(by_week.keys()):
        b = by_week[week]
        summary.append(
            {
                "week": week,
                "rides": b["ride_count"],
                "hours": round(b["total_hours"], 1),
                "tss": round(b["total_tss"]),
                "distance_km": round(b["total_distance_km"]),
                "elevation_m": round(b["total_elevation_m"]),
                "hardest_ride": b["hardest_ride_name"],
                "hardest_tss": round(b["hardest_ride_tss"]),
            }
        )
    return summary


async def _fetch_wellness(days: int) -> list[dict]:
    oldest, newest = _date_range(days)
    url = f"{BASE}/athlete/{Config.INTERVALS_ATHLETE_ID}/wellness"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            url, headers=_headers(), params={"oldest": oldest, "newest": newest}
        )
        r.raise_for_status()
        return r.json()


async def get_wellness_recent(days: int = DETAIL_DAYS) -> list[dict]:
    """Recent daily wellness — sleep, fatigue, mood, RHR, HRV."""
    rows = await _fetch_wellness(days)
    return [
        {
            "date": w.get("id"),
            "sleep_hours": round(w.get("sleepSecs", 0) / 3600, 1) if w.get("sleepSecs") else None,
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
        for w in rows
    ]


async def get_fitness_curve_weekly(days: int = SUMMARY_DAYS) -> list[dict]:
    """CTL/ATL/TSB sampled weekly across the full horizon.

    One row per ISO week (latest entry of that week wins) — gives Claude the
    fitness arc without dumping 90 daily rows.
    """
    rows = await _fetch_wellness(days)
    by_week: dict[str, dict] = {}
    for w in rows:
        date_str = w.get("id", "")
        week = _iso_week_key(date_str)
        if not week:
            continue
        ctl = w.get("ctl")
        atl = w.get("atl")
        if ctl is None or atl is None:
            continue
        # latest row of the week wins
        existing = by_week.get(week)
        if not existing or date_str > existing.get("date", ""):
            by_week[week] = {
                "week": week,
                "date": date_str,
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(ctl - atl, 1),
            }
    return [by_week[w] for w in sorted(by_week.keys())]


async def get_current_form() -> dict:
    """Today's CTL/ATL/TSB snapshot."""
    rows = await _fetch_wellness(days=2)
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


async def get_full_snapshot() -> dict[str, Any]:
    """Bundle smart-split data: recent detail + 90-day summary + form."""
    detail = await get_recent_activities_detail(DETAIL_DAYS)
    weekly = await get_weekly_summary(SUMMARY_DAYS)
    wellness = await get_wellness_recent(DETAIL_DAYS)
    fitness_curve = await get_fitness_curve_weekly(SUMMARY_DAYS)
    form = await get_current_form()
    return {
        "form_today": form,
        "fitness_curve_weekly_90d": fitness_curve,
        "training_summary_weekly_90d": weekly,
        "activities_detail_last_14d": detail,
        "wellness_last_14d": wellness,
    }
