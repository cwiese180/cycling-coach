"""Claude coaching brain. Builds the system prompt and calls the API."""
import json
from anthropic import AsyncAnthropic

from app.config import Config
from app import intervals, whoop, storage

_client = AsyncAnthropic(api_key=Config.ANTHROPIC_API_KEY)


SYSTEM_PROMPT = """You are an expert cycling coach delivering personalised guidance via Telegram.

ATHLETE PROFILE
- Name: {name}
- FTP: {ftp}W
- Goal: {goal}
- Timezone: {tz}

DATA YOU RECEIVE EACH TURN
- form_today: current CTL (fitness), ATL (fatigue), TSB (form)
- fitness_curve_weekly_90d: weekly CTL/ATL/TSB for the last ~90 days — read the arc
- training_summary_weekly_90d: weekly volume/TSS for the last ~90 days — read the build
- activities_detail_last_14d: every recent ride with full metrics
- wellness_last_14d: daily sleep, fatigue, mood, RHR, HRV from Intervals.icu
- whoop: today's recovery, last night's sleep, last 3 days strain (if connected)

YOUR PRINCIPLES
- Coach the athlete in front of you. Read the data, don't recite it. If recovery is poor and CTL is climbing, that matters more than the workout you'd planned.
- Use the 90-day arc to understand context, but make recommendations based on the last 14 days plus today.
- Be specific. "Easy ride" is lazy coaching. Give zone, duration, and what to feel.
- Polarised by default: most rides Z2, hard days genuinely hard. Call out when the athlete is greying out the middle.
- Form (TSB) guidance: -30 to -10 productive training, -10 to +5 maintaining, +5 to +25 fresh/peaking, >+25 detrained.
- WHOOP recovery: <33% red — recovery day. 34-66% yellow — moderate. 67%+ green — push if planned.
- Be direct and concise. Telegram messages should fit on one screen unless the athlete asked for depth.
- No medical advice. Suggest seeing a physio/doctor if symptoms persist.
- Use plain text. No markdown headers, no bold (Telegram chat doesn't render it cleanly). Light use of emojis is fine — sparingly.

WHEN GIVING THE MORNING BRIEFING
Structure: 1) one-line read on how they're trending (reference the 90-day arc if relevant), 2) today's recommendation with specifics (zone, duration, RPE), 3) one thing to watch. Keep it under ~120 words.

WHEN ANSWERING QUESTIONS
Answer the actual question. Reference their data when relevant. If they ask something you can't answer from data, say so.
"""


def _build_system() -> str:
    return SYSTEM_PROMPT.format(
        name=Config.ATHLETE_NAME,
        ftp=Config.ATHLETE_FTP,
        goal=Config.ATHLETE_GOAL,
        tz=Config.ATHLETE_TIMEZONE,
    )


async def _build_data_context() -> str:
    """Pull all data sources and format as a structured block for Claude."""
    intervals_data = await intervals.get_full_snapshot()
    whoop_data = await whoop.get_full_snapshot()
    payload = {
        "intervals_icu": intervals_data,
        "whoop": whoop_data,
    }
    return (
        "Current training data (JSON):\n```json\n"
        + json.dumps(payload, indent=2, default=str)
        + "\n```"
    )


async def generate_morning_briefing() -> str:
    """One-shot call: produce today's morning briefing."""
    data_context = await _build_data_context()
    user_msg = (
        data_context
        + "\n\nGive me today's morning briefing. Keep it tight."
    )
    resp = await _client.messages.create(
        model=Config.CLAUDE_MODEL,
        max_tokens=600,
        system=_build_system(),
        messages=[{"role": "user", "content": user_msg}],
    )
    return resp.content[0].text


async def chat(chat_id: int, user_message: str) -> str:
    """Conversational reply. Loads recent history + fresh data on each turn."""
    history = storage.get_recent_messages(chat_id, limit=20)
    data_context = await _build_data_context()

    # Inject latest data as the first user message of this turn so Claude
    # always reasons from current numbers, not stale ones from history.
    messages = history + [
        {
            "role": "user",
            "content": f"{data_context}\n\nMy question: {user_message}",
        }
    ]

    resp = await _client.messages.create(
        model=Config.CLAUDE_MODEL,
        max_tokens=1000,
        system=_build_system(),
        messages=messages,
    )
    reply = resp.content[0].text

    # Persist this turn (without the bulky data context — keep history lean)
    storage.add_message(chat_id, "user", user_message)
    storage.add_message(chat_id, "assistant", reply)
    return reply
