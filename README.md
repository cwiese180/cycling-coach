# Cycling Coach Bot

Personal AI cycling coach. Pulls training data from **Intervals.icu** (Strava sync) and **WHOOP**, sends it to **Claude** for analysis, and delivers coaching via **Telegram**.

Features:
- Daily morning briefing (scheduled, your local time)
- Conversational chat — ask the coach anything
- Per-chat conversation memory (SQLite)
- Single-user by default; allowlist controlled

Architecture: long-running Python worker, deployed to DigitalOcean App Platform with auto-deploy from GitHub.

---

## 1. Get your API keys (15 min)

You need five things. Grab them all before deploying:

### Telegram bot token
1. Open Telegram, message **@BotFather**, send `/newbot`
2. Pick a name and username, save the token (`123456:ABC...`)
3. Message your new bot once (anything), then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` — find your numeric `chat.id`. That's your `ALLOWED_CHAT_IDS`.

### Anthropic API key
1. https://console.anthropic.com → API Keys → Create
2. Add credit (~$5 lasts months for personal use)

### Intervals.icu
1. Connect Strava in Intervals.icu settings (one-click)
2. Settings → Developer → grab your **API key** and **Athlete ID** (looks like `i12345`)

### WHOOP (optional but recommended)
1. https://developer.whoop.com → create an app
2. Set redirect URI to `http://localhost:8765/callback`
3. Save Client ID and Client Secret
4. Run the setup script locally to get a refresh token (instructions below)

---

## 2. WHOOP one-time auth (5 min)

WHOOP needs an OAuth handshake. Do this once on your laptop:

```bash
git clone https://github.com/YOUR_USERNAME/cycling-coach.git
cd cycling-coach
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export WHOOP_CLIENT_ID=your_id
export WHOOP_CLIENT_SECRET=your_secret
python -m scripts.whoop_setup
```

Browser opens, you authorise, the script prints `WHOOP_REFRESH_TOKEN=...`. Save it.

Skip this entirely if you don't want WHOOP — the bot works fine with just Intervals.icu.

---

## 3. Push to GitHub

```bash
cd cycling-coach
git init
git add .
git commit -m "Initial coach bot"
gh repo create cycling-coach --private --source=. --push
# or create on github.com and push manually
```

---

## 4. Deploy to DigitalOcean App Platform (10 min)

1. Go to https://cloud.digitalocean.com/apps → **Create App**
2. Connect your GitHub repo `cycling-coach`, branch `main`
3. **Important**: when DO detects the Dockerfile, change the resource type from "Web Service" to **"Worker"** (no public port needed — this is a long-polling bot, not an HTTP server)
4. Pick **Basic / $5 mo** (basic-xxs is plenty)
5. Add environment variables — copy from `.env.example`. Mark API keys as `SECRET`.
6. Click **Create Resources**

First deploy takes ~3 minutes. Once it's running, message your bot `/start` on Telegram. You should see a welcome reply.

Test the daily briefing immediately with `/briefing`. The scheduled version fires at `BRIEFING_HOUR:BRIEFING_MINUTE` in your timezone.

### Persistent storage gotcha

App Platform workers have **ephemeral filesystems** — SQLite data is lost on redeploy. For a single user this is fine (conversation history just resets when you push code). If you want true persistence, two options:

- **Cheap**: switch `DB_PATH` to `/tmp/coach.db` and accept it. History resets on redeploy only.
- **Proper**: attach a DigitalOcean Volume to a Droplet instead of using App Platform, OR migrate to DO Managed Postgres (~$15/mo).

For now the code defaults to `/app/data/coach.db` which survives across container restarts within a deploy, just not across deploys.

---

## 5. Local development

```bash
cp .env.example .env
# fill in .env
source .venv/bin/activate
python -m app.bot
```

The bot runs locally with long polling — same behaviour as production.

---

## Commands reference

| Command | What it does |
|---------|-------------|
| `/start` | Welcome message, command list |
| `/briefing` | Get today's morning briefing on demand |
| `/reset` | Clear conversation history |
| `/whoami` | Show your Telegram chat ID |
| (any text) | Chat with the coach |

---

## Cost estimate (single user)

- DO App Platform basic-xxs: **$5/mo**
- Anthropic API (Claude Opus): **~$2–5/mo** for daily briefing + ~30 messages/day
- Telegram, Intervals.icu free tier, WHOOP: **$0**

**Total: ~$7–10/mo**

---

## Customising the coach

Open `app/coach.py`. The `SYSTEM_PROMPT` constant is where the coaching philosophy lives. Edit it to match your style — more aggressive, more conservative, focused on a specific event, etc. Push to GitHub and DO redeploys automatically.

---

## Adding more athletes later

The code already supports multiple chats — just add more IDs to `ALLOWED_CHAT_IDS` (comma-separated). For multi-athlete with separate FTPs/goals, you'd extend `storage.py` with a `users` table keyed by `chat_id`. Left as a small extension.
