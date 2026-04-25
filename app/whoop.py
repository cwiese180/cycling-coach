"""WHOOP API v2 client.

WHOOP uses OAuth2. After initial auth (one-time, via setup script), we store the
refresh token in env and use it to mint short-lived access tokens, cached in SQLite.

Docs: https://developer.whoop.com/api
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import Config
from app import storage

TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer/v2"

_TOKEN_KEY = "whoop_access_token"


async def _get_access_token() -> Optional[str]:
    """Return a valid access token, refreshing if needed."""
    if not Config.WHOOP_REFRESH_TOKEN:
        return None

    cached = storage.kv_get(_TOKEN_KEY)
    if cached and cached.get("expires_at", 0) > time.time() + 60:
        return cached["access_token"]

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": Config.WHOOP_REFRESH_TOKEN,
                "client_id": Config.WHOOP_CLIENT_ID,
                "client_secret": Config.WHOOP_CLIENT_SECRET,
                "scope": "offline read:recovery read:cycles read:sleep read:workout read:profile",
            },
        )
        r.raise_for_status()
        data = r.json()

    token_info = {
        "access_token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 3600) - 60,
    }
    storage.kv_set(_TOKEN_KEY, token_info)
    return token_info["access_token"]


async def _get(path: str, params: dict | None = None) -> dict:
    token = await _get_access_token()
    if not token:
        return {}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
        )
        r.raise_for_status()
        return r.json()


async def get_recovery_today() -> dict:
    """Most recent recovery score (HRV, RHR, recovery %)."""
    if not Config.WHOOP_REFRESH_TOKEN:
        return {}
    start = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    data = await _get("/recovery", params={"start": start, "limit": 5})
    records = data.get("records", [])
    if not records:
        return {}
    latest = records[0]
    score = latest.get("score", {})
    return {
        "recovery_pct": score.get("recovery_score"),
        "hrv_ms": score.get("hrv_rmssd_milli"),
        "resting_hr": score.get("resting_heart_rate"),
        "skin_temp_c": score.get("skin_temp_celsius"),
        "spo2": score.get("spo2_percentage"),
    }


async def get_sleep_last_night() -> dict:
    """Last night's sleep summary."""
    if not Config.WHOOP_REFRESH_TOKEN:
        return {}
    start = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    data = await _get("/activity/sleep", params={"start": start, "limit": 5})
    records = data.get("records", [])
    if not records:
        return {}
    latest = records[0]
    score = latest.get("score", {})
    stage = score.get("stage_summary", {})
    return {
        "performance_pct": score.get("sleep_performance_percentage"),
        "efficiency_pct": score.get("sleep_efficiency_percentage"),
        "consistency_pct": score.get("sleep_consistency_percentage"),
        "total_sleep_min": stage.get("total_in_bed_time_milli", 0) / 60000,
        "rem_min": stage.get("total_rem_sleep_time_milli", 0) / 60000,
        "deep_min": stage.get("total_slow_wave_sleep_time_milli", 0) / 60000,
        "awake_min": stage.get("total_awake_time_milli", 0) / 60000,
        "respiratory_rate": score.get("respiratory_rate"),
    }


async def get_recent_strain(days: int = 3) -> list[dict]:
    """Recent daily strain (cycles)."""
    if not Config.WHOOP_REFRESH_TOKEN:
        return []
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    data = await _get("/cycle", params={"start": start, "limit": days + 1})
    records = data.get("records", [])
    return [
        {
            "date": r.get("start", "")[:10],
            "strain": r.get("score", {}).get("strain"),
            "avg_hr": r.get("score", {}).get("average_heart_rate"),
            "max_hr": r.get("score", {}).get("max_heart_rate"),
            "kj": r.get("score", {}).get("kilojoule"),
        }
        for r in records
    ]


async def get_full_snapshot() -> dict:
    """Bundle everything Claude needs from WHOOP."""
    if not Config.WHOOP_REFRESH_TOKEN:
        return {"connected": False}
    try:
        recovery = await get_recovery_today()
        sleep = await get_sleep_last_night()
        strain = await get_recent_strain(3)
        return {
            "connected": True,
            "recovery": recovery,
            "sleep_last_night": sleep,
            "recent_strain": strain,
        }
    except Exception as e:
        return {"connected": True, "error": str(e)}
