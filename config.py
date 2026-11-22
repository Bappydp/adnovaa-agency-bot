"""Configuration for the agency Telegram bot.

All secrets come from environment variables (or a local .env file).
NEVER hard-code a token or wallet address in this repo.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Required -------------------------------------------------------
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Comma-separated Telegram user IDs of the bot admins, e.g. "123456789,987654321".
# Get your own ID from @userinfobot on Telegram.
# Default: the owner's ID (6824922316) + the second admin's ID
# (9027179219), pre-filled so the admin commands work even if
# ADMIN_IDS is never set on Render.
# Override via the ADMIN_IDS env var to add or change admins.
ADMIN_IDS: list[int] = [
    int(x) for x in os.getenv("ADMIN_IDS", "6824922316,9027179219").split(",")
    if x.strip().isdigit()
]

# --- Channel / group -------------------------------------------------
# Channel username WITH @, e.g. "@YourChannel" — used for the
# force-subscribe check and the Join button. The bot must be an
# admin of the channel for the membership check to work.
# Default: the agency channel @facebookads_adnovaa
# (https://t.me/facebookads_adnovaa). Override via .env if needed.
CHANNEL_ID: str = os.getenv("CHANNEL_ID", "@facebookads_adnovaa")

# Bot username WITHOUT @ — used for referral links
# (t.me/<username>?start=ref_<userid>). The bot also learns its own
# username at startup via getMe; this is the fallback.
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "adnovaaagencybot")

# Numeric group chat ID (e.g. -1001234567890), optional.
# Used for giveaway announcements. Leave empty if not needed.
GROUP_ID: int = int(os.getenv("GROUP_ID", "0") or 0)

# --- Protection (anti-spam / report / alerts) ----------------------
# 3 spam strikes within 24 hours = ban from the group.
SPAM_STRIKE_LIMIT: int = int(os.getenv("SPAM_STRIKE_LIMIT", "3"))
SPAM_STRIKE_WINDOW_HOURS: int = int(
    os.getenv("SPAM_STRIKE_WINDOW_HOURS", "24"))
# Max reports one user can send per hour.
REPORT_LIMIT_PER_HOUR: int = int(os.getenv("REPORT_LIMIT_PER_HOUR", "3"))
# Mass-leave alert: this many leaves within the window triggers one
# alert to the admins; the same alert won't repeat before the cooldown.
MASS_LEAVE_THRESHOLD: int = int(os.getenv("MASS_LEAVE_THRESHOLD", "5"))
MASS_LEAVE_WINDOW_HOURS: int = int(
    os.getenv("MASS_LEAVE_WINDOW_HOURS", "1"))
MASS_LEAVE_ALERT_COOLDOWN_HOURS: int = int(
    os.getenv("MASS_LEAVE_ALERT_COOLDOWN_HOURS", "6"))

# --- Hosting ----------------------------------------------------------
# Render sets PORT automatically; local default is 10000.
PORT: int = int(os.getenv("PORT", "10000"))

# SQLite file. On Render free tier the disk is ephemeral, so the DB
# resets on redeploy — acceptable for this bot's volume. (A managed
# Postgres can replace it later without changing the handlers.)
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "bot.db")
