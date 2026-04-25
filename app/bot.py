"""Telegram bot entry point.

- Long polling (no webhook needed).
- APScheduler for the daily morning briefing.
- Runs as a single long-lived process — perfect for DO App Platform Worker.
"""
import asyncio
import logging
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app import storage, coach

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("coach-bot")


# ---------- Auth guard ----------

def _allowed(update: Update) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in Config.ALLOWED_CHAT_IDS


# ---------- Commands ----------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not _allowed(update):
        await update.message.reply_text(
            f"This bot is private. Your chat ID is {chat_id}. "
            "Add it to ALLOWED_CHAT_IDS to enable access."
        )
        return
    await update.message.reply_text(
        f"Hi {Config.ATHLETE_NAME} 👋 I'm your coach.\n\n"
        "Commands:\n"
        "/briefing — get today's briefing now\n"
        "/reset — clear conversation history\n"
        "/whoami — show your chat ID\n\n"
        "Or just message me anything — ride questions, how you're feeling, "
        "what to do today, etc."
    )


async def cmd_whoami(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def cmd_briefing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    chat_id = update.effective_chat.id
    await ctx.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        text = await coach.generate_morning_briefing()
        await update.message.reply_text(text)
    except Exception as e:
        log.exception("briefing failed")
        await update.message.reply_text(f"Couldn't pull your data: {e}")


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    storage.clear_history(update.effective_chat.id)
    await update.message.reply_text("History cleared. Fresh start. 🧹")


# ---------- Free-form chat ----------

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    await ctx.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        reply = await coach.chat(chat_id, user_text)
        # Telegram caps at 4096 chars
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i : i + 4000])
    except Exception as e:
        log.exception("chat failed")
        await update.message.reply_text(f"Hit an error: {e}")


# ---------- Scheduled morning briefing ----------

async def push_morning_briefing(app: Application):
    log.info("Running scheduled morning briefing")
    try:
        text = await coach.generate_morning_briefing()
        for chat_id in Config.ALLOWED_CHAT_IDS:
            await app.bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        log.exception("scheduled briefing failed")


def setup_scheduler(app: Application) -> AsyncIOScheduler:
    tz = ZoneInfo(Config.ATHLETE_TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        push_morning_briefing,
        "cron",
        hour=Config.BRIEFING_HOUR,
        minute=Config.BRIEFING_MINUTE,
        args=[app],
        id="morning_briefing",
    )
    return scheduler


# ---------- Main ----------

async def post_init(app: Application):
    storage.init_db()
    scheduler = setup_scheduler(app)
    scheduler.start()
    log.info(
        "Scheduler started. Briefing daily at %02d:%02d %s",
        Config.BRIEFING_HOUR,
        Config.BRIEFING_MINUTE,
        Config.ATHLETE_TIMEZONE,
    )


def main():
    app = (
        Application.builder()
        .token(Config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Coach bot starting (long polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
