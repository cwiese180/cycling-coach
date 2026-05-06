"""WHOOP API v2 client.

WHOOP uses OAuth2 with refresh-token rotation: every refresh call may issue
a new refresh token and invalidate the old one. We persist the latest refresh
token in:
  1. SQLite (kv table) — primary, fast lookup
  2. A flat file at /app/data/whoop_refresh_token.txt — belt-and-braces, also
     visible to the operator if they need to copy it out

We also LOG the rotated token at INFO level on every change so it shows up in
DigitalOcean Runtime Logs as a recovery path of last resort.

Initial bootstrap: env var WHOOP_REFRESH_TOKEN. After first refresh, we use
the stored value.

Docs: https://developer.whoop.com/api
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import Config
from app import storage

log = logging.getLogger("whoop")

TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer/v2"

_TOKEN_KEY = "whoop_access_token"
_REFRESH_KEY = "whoop_refresh_token"
_REFRESH_FILE = "/app/data/whoop_refresh_token.txt"


def _read_refresh_file() -> Optional[str]:
    """Read refresh token from disk file, if present."""
    try:
        with open(_REFRESH_FILE) as f:
            tok = f.read().strip()
        return tok or None
    except (FileNotFoundError, OSError):
        return None


def _write_refresh_file(token: str) -> None:
    """Persist refresh token to disk as a fallback to SQLite."""
    try:
        os.makedirs(os.path.dirname(_REFRESH_FILE), exist_ok=True)
        with open(_REFRESH_FILE, "w") as f:
            f.write(token)
    except OSError as e:
        log.warning("Could not write refresh token to file: %s", e)


def _current_refresh_token() -> Optional[str]:
    """Return the most recent refresh token (DB > file > env)."""
    stored = storage.kv_get(_REFRESH_KEY)
    if stored and stored.get("refresh_token"):
        return stored["refresh_token"]
    file_tok = _read_refresh_file()
    if file_tok:
        return file_tok
    return Config.WHOOP_REFRESH_TOKEN or None


async def _get_access_token() -> Optional[str]:
    """Return a valid access token, refreshing if needed.

    Persists rotated refresh tokens to SQLite + file + log so we don't lose them.
    """
    refresh_token = _current_refresh_token()
    if not refresh_token:
        return None

    cached = storage.kv_get(_TOKEN_KEY)
    if cached and cached.get("expires_at", 0) > time.time() + 60:
        return cached["access_token"]

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": Config.WHOOP_CLIENT_ID,
                "client_secret": Config.WHOOP_CLIENT_SECRET,
                "scope": "offline read:recovery read:cycles read:sleep read:workout read:profile",
            },
        )
        if r.status_code != 200:
            # Surface a useful error so the bot's reply tells the user
            # exactly what to do.
            raise RuntimeError(
                f"WHOOP token refresh failed ({r.status_code}): {r.text[:200]}. "
                "Re-run scripts/whoop_setup and update WHOOP_REFRESH_TOKEN."
            )
        data = r.json()

    # Save the new access token
    token_info = {
        "access_token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 3600) - 60,
    }
    storage.kv_set(_TOKEN_KEY, token_info)

    # Save the rotated refresh token to BOTH SQLite and a file (so even if
    # SQLite gets wiped by a redeploy, the file survives if we have a volume,
    # AND we log the token prominently so the operator can recover it from
    # Runtime Logs if both fail).
    new_refresh = data.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        storage.kv_set(_REFRESH_KEY, {"refresh_token": new_refresh})
        _write_refresh_file(new_refresh)
        log.info(
            "WHOOP_REFRESH_TOKEN rotated. Latest token (copy this if needed): %s",
            new_refresh,
        )

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


async def get_recent_cycles(days: int = 3) -> list[dict]:
    """Recent physiological cycles (one per day usually).

    In v2, recovery data is nested inside the cycle response — see
    developer.whoop.com/docs/developing/user-data/recovery.
    """
    if not _current_refresh_token():
        return []
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    data = await _get("/cycle", params={"start": start, "limit": days + 1})
    return data.get("records", [])


async def get_recovery_today() -> dict:
    """Most recent recovery from the latest cycle."""
    cycles = await get_recent_cycles(days=2)
    if not cycles:
        return {}
    latest = cycles[0]
    cycle_id = latest.get("id")
    if not cycle_id:
        return {}

    # In v2 you fetch recovery for a specific cycle
    try:
        rec = await _get(f"/cycle/{cycle_id}/recovery")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {}  # not all cycles have recovery yet
        raise

    score = rec.get("score", {}) or {}
    return {
        "recovery_pct": score.get("recovery_score"),
        "hrv_ms": score.get("hrv_rmssd_milli"),
        "resting_hr": score.get("resting_heart_rate"),
        "skin_temp_c": score.get("skin_temp_celsius"),
        "spo2": score.get("spo2_percentage"),
    }


async def get_sleep_last_night() -> dict:
    """Last night's sleep summary (v2 endpoint)."""
    if not _current_refresh_token():
        return {}
    start = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    data = await _get("/activity/sleep", params={"start": start, "limit": 5})
    records = data.get("records", [])
    if not records:
        return {}
    latest = records[0]
    score = latest.get("score", {}) or {}
    stage = score.get("stage_summary", {}) or {}
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
    """Recent daily strain from cycles."""
    cycles = await get_recent_cycles(days=days)
    return [
        {
            "date": (c.get("start") or "")[:10],
            "strain": (c.get("score") or {}).get("strain"),
            "avg_hr": (c.get("score") or {}).get("average_heart_rate"),
            "max_hr": (c.get("score") or {}).get("max_heart_rate"),
            "kj": (c.get("score") or {}).get("kilojoule"),
        }
        for c in cycles
    ]


async def get_full_snapshot() -> dict:
    """Bundle everything Claude needs from WHOOP."""
    if not _current_refresh_token():
        return {"connected": False, "reason": "WHOOP_REFRESH_TOKEN not set"}
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
