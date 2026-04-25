"""Configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
    # Comma-separated list of allowed chat IDs (your Telegram user ID)
    ALLOWED_CHAT_IDS = {
        int(x.strip()) for x in os.environ["ALLOWED_CHAT_IDS"].split(",") if x.strip()
    }

    # Anthropic
    ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
    CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5")

    # Intervals.icu
    INTERVALS_API_KEY = os.environ["INTERVALS_API_KEY"]
    INTERVALS_ATHLETE_ID = os.environ["INTERVALS_ATHLETE_ID"]

    # WHOOP (OAuth2)
    WHOOP_CLIENT_ID = os.environ.get("WHOOP_CLIENT_ID", "")
    WHOOP_CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET", "")
    WHOOP_REFRESH_TOKEN = os.environ.get("WHOOP_REFRESH_TOKEN", "")

    # Athlete profile (used in coaching prompt)
    ATHLETE_NAME = os.environ.get("ATHLETE_NAME", "Athlete")
    ATHLETE_FTP = int(os.environ.get("ATHLETE_FTP", "250"))
    ATHLETE_GOAL = os.environ.get(
        "ATHLETE_GOAL", "General cycling fitness and consistency"
    )
    ATHLETE_TIMEZONE = os.environ.get("ATHLETE_TIMEZONE", "Europe/London")

    # Morning briefing time (24h, athlete's local TZ)
    BRIEFING_HOUR = int(os.environ.get("BRIEFING_HOUR", "6"))
    BRIEFING_MINUTE = int(os.environ.get("BRIEFING_MINUTE", "30"))

    # Storage
    DB_PATH = os.environ.get("DB_PATH", "/app/data/coach.db")
