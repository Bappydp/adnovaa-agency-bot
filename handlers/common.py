"""Shared helpers for handlers: admin checks, channel membership,
lead notifications and small utilities."""

import html
import logging
import time
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from config import ADMIN_IDS, BOT_USERNAME, CHANNEL_ID

logger = logging.getLogger(__name__)

# Membership cache: user_id -> (True, checked_at).
# ONLY positive results are cached (members re-checked every
# 10 minutes). "Not a member" is NEVER cached: a user who joins
# the channel must be able to write in the group with their very
# next message, without tapping anything or waiting for a cache
# to expire.
_member_cache: dict[int, tuple[bool, float]] = {}
_MEMBER_TTL = 600        # members re-checked every 10 minutes

# Group-admin cache: (chat_id, user_id) -> (is_admin, checked_at).
_group_admin_cache: dict[tuple[int, int], tuple[bool, float]] = {}
_GROUP_ADMIN_TTL = 300   # re-checked every 5 minutes


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_only(func):
    """Decorator: only ADMIN_IDS may run this handler."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      *args, **kwargs):
        if not is_admin(update.effective_user.id):
            await update.effective_message.reply_text(
                "⛔ This command is for admins only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def channel_url() -> str | None:
    """Public t.me link for the channel, or None if not configured
    as a @username (a numeric channel ID has no public link)."""
    if CHANNEL_ID.startswith("@"):
        return f"https://t.me/{CHANNEL_ID[1:]}"
    return None


def invalidate_member_cache(user_id: int) -> None:
    _member_cache.pop(user_id, None)


def mark_member_cache(user_id: int) -> None:
    """Record a user as a channel member (used when the channel
    join update arrives, so their very next group message passes
    at once even before any live re-check)."""
    _member_cache[user_id] = (True, time.time())


def is_our_channel(chat) -> bool:
    """Is this chat our gated channel? Matches by @username when
    CHANNEL_ID is a username, or by numeric chat ID when it is one."""
    if not CHANNEL_ID:
        return False
    if CHANNEL_ID.startswith("@"):
        return getattr(chat, "username", None) == CHANNEL_ID[1:]
    return str(getattr(chat, "id", "")) == CHANNEL_ID


async def is_channel_member(bot, user_id: int) -> bool | None:
    """Check whether a user is a member of the channel.

    Returns True (member), False (not a member) or None (the check
    failed — e.g. bot is not a channel admin, or Telegram errored).
    Callers must treat None as "don't block" so a config problem
    never locks real users out.

    Only "is a member" is cached (10 minutes). "Not a member" is
    NEVER cached — every message from a non-member re-checks live,
    so the first message after joining the channel goes through
    immediately, with no tap and no wait.
    """
    if not CHANNEL_ID:
        return True  # channel not configured yet — don't block anyone

    cached = _member_cache.get(user_id)
    if cached is not None:
        result, checked_at = cached
        if time.time() - checked_at < _MEMBER_TTL:
            return result
        _member_cache.pop(user_id, None)

    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        result = member.status in (
            "creator", "administrator", "member", "restricted")
    except Exception as exc:
        # Log and fail open: never block users because of our own error.
        logger.warning("Channel membership check failed for %s: %s",
                       user_id, exc)
        return None

    # Cache ONLY "is a member" — never "not a member" (see above).
    if result:
        _member_cache[user_id] = (True, time.time())
    return result


def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Bot username without @ — live value from getMe if available,
    otherwise the BOT_USERNAME fallback from config."""
    return (context.bot_data.get("bot_username")
            or BOT_USERNAME
            or context.bot.username or "")


def referral_link(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    username = get_bot_username(context)
    if not username:
        return ""
    return f"https://t.me/{username}?start=ref_{user_id}"


async def mark_lead_and_notify(context: ContextTypes.DEFAULT_TYPE,
                               user) -> None:
    """Flag a user as a lead; notify admins the FIRST time only."""
    if db.mark_lead(user.id):
        text = (
            "🆕 <b>New lead</b>\n\n"
            f"👤 {describe_user(user)}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, text)
            except Exception as exc:
                logger.warning("Could not notify admin %s: %s",
                               admin_id, exc)


def describe_user(user) -> str:
    """Safe one-line description of a Telegram user (HTML-escaped)."""
    name = html.escape(user.full_name or "Unknown")
    uname = f"@{user.username}" if user.username else "(no username)"
    return f"{name} {html.escape(uname)} (id <code>{user.id}</code>)"


async def is_group_admin(bot, chat_id: int, user_id: int) -> bool:
    """Is this user a creator/admin of the group? Cached briefly.

    Fails OPEN (returns True) on API errors: deleting a group
    admin's message by mistake is worse than missing one spam
    message, and a failed check usually means the bot can't act
    in the group at all anyway.
    """
    cached = _group_admin_cache.get((chat_id, user_id))
    if cached is not None:
        result, checked_at = cached
        if time.time() - checked_at < _GROUP_ADMIN_TTL:
            return result
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        result = member.status in ("creator", "administrator")
    except Exception as exc:
        logger.warning("Group admin check failed for %s in %s: %s",
                       user_id, chat_id, exc)
        return True
    _group_admin_cache[(chat_id, user_id)] = (result, time.time())
    return result


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str,
                        reply_markup=None) -> list[tuple[int, int]]:
    """Send a message to every ADMIN_ID. Returns the list of
    (admin_id, message_id) pairs that were delivered, so callers
    can edit those copies later (e.g. report actions)."""
    delivered: list[tuple[int, int]] = []
    for admin_id in ADMIN_IDS:
        try:
            sent = await context.bot.send_message(
                admin_id, text, reply_markup=reply_markup)
            delivered.append((admin_id, sent.message_id))
        except Exception as exc:
            logger.warning("Could not notify admin %s: %s", admin_id, exc)
    return delivered


def message_link(chat, message_id: int) -> str | None:
    """Public t.me link to a message, or None if the chat has no
    public link form."""
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}/{message_id}"
    cid = str(chat.id)
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return None
