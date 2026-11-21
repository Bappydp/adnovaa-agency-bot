"""Group handling: force-subscribe gate + anti-spam + keyword auto-replies.

This handler runs in group -1 (before everything else) so a
non-member's message — including commands — is deleted before any
other handler can act on it.

Order inside this handler:
  1. Force-subscribe gate (non-members deleted)
  2. Anti-spam (obvious spam deleted, strikes recorded, 3 strikes = ban)
  3. Keyword auto-reply (only for messages that survived 1 and 2)

The gate warning is EPHEMERAL: it is posted in the group (never
DM — the owner doesn't want private warnings) and deletes itself
after 30 seconds, and each user gets at most one warning per hour.
"""

import asyncio
import html
import logging
import re
import time
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

import database as db
import keyboards
from config import SPAM_STRIKE_LIMIT, SPAM_STRIKE_WINDOW_HOURS
from content import (
    GROUP_JOIN_WARNING,
    SPAM_BANNED,
    SPAM_WARNING,
)
from handlers.common import (
    channel_url,
    is_admin,
    is_channel_member,
    is_group_admin,
    notify_admins,
)

logger = logging.getLogger(__name__)

# user_id -> timestamp of the last gate warning (5 minute cooldown,
# so repeat offenders don't get a new warning every message — but
# since the warning deletes itself after 30s, a user who missed it
# gets reminded on their next message after 5 minutes).
_warn_cooldown: dict[int, float] = {}
_WARN_TTL = 300

# Seconds before an in-group gate warning deletes itself.
_WARN_DELETE_AFTER = 30


async def _delete_gate_warning(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback: delete an expired gate warning. The
    message may already be gone (the user tapped "✅ I've Joined"
    first, or an admin deleted it) — that is fine, never crash."""
    job = context.job
    try:
        await context.bot.delete_message(job.chat_id, job.data)
    except Exception as exc:
        logger.debug("Gate warning %s already gone: %s", job.data, exc)


async def _delete_gate_warning_soon(context, chat_id: int,
                                    message_id: int) -> None:
    """asyncio fallback when no JobQueue is available: wait, then
    delete. Same tolerance for an already-gone message."""
    await asyncio.sleep(_WARN_DELETE_AFTER)
    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception as exc:
        logger.debug("Gate warning %s already gone: %s", message_id, exc)


def _schedule_warning_delete(context: ContextTypes.DEFAULT_TYPE,
                             chat_id: int, message_id: int) -> None:
    """Delete a gate warning ~30s after it is posted, so the group
    never fills up with stale warnings. JobQueue first (the pattern
    the bot already uses for delayed work); an asyncio task if no
    JobQueue is available."""
    job_queue = getattr(context, "job_queue", None)
    if job_queue is not None:
        try:
            job_queue.run_once(
                _delete_gate_warning, when=_WARN_DELETE_AFTER,
                data=message_id, chat_id=chat_id,
                name=f"gate_warning:{chat_id}:{message_id}")
            return
        except Exception as exc:
            logger.warning("Could not schedule gate-warning delete: %s",
                           exc)
    try:
        asyncio.create_task(
            _delete_gate_warning_soon(context, chat_id, message_id))
    except RuntimeError as exc:
        # No running loop (shouldn't happen inside a handler).
        logger.warning("Could not schedule gate-warning delete: %s",
                       exc)

# user_id -> timestamp of the last keyword auto-reply (60s cooldown).
_keyword_cooldown: dict[int, float] = {}
_KEYWORD_TTL = 60

# user_id -> timestamp of the last spam warning (10 min cooldown,
# so a spammer doesn't flood the group with warnings).
_spam_warn_cooldown: dict[int, float] = {}
_SPAM_WARN_TTL = 600

_URL_RE = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@[A-Za-z0-9_]{5,}")
_NEW_MEMBER_HOURS = 24


def _matches_spam_word(text: str, word: str) -> bool:
    """Match one spam-word entry against lowercased text.

    Phrases (contain a space) match as substrings; single words
    match as whole words only, so "casino" never matches inside
    another word.
    """
    if " " in word:
        return word in text
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def _find_spam(text: str, chat_id: int, user_id: int) -> str | None:
    """Check a message for obvious spam. Returns a short reason
    string if it is spam, otherwise None.

    Checks, in order:
      1. Spam keyword/phrase from the (admin-managed) list.
      2. 3 or more URLs in one message.
      3. A URL + an @mention from a member who joined <24h ago.
         (Join time comes from the membership tracker; if the join
         is unknown — e.g. they joined before the bot was added —
         this check simply doesn't fire.)
    """
    low = text.lower()
    for word in db.get_spam_words():
        if _matches_spam_word(low, word.lower()):
            return f"spam word: {word}"
    urls = _URL_RE.findall(text)
    if len(urls) >= 3:
        return f"{len(urls)} links in one message"
    if urls and _MENTION_RE.search(text):
        joined = db.get_last_join(chat_id, user_id)
        if joined is not None:
            age = datetime.now(timezone.utc) - joined
            if age.total_seconds() < _NEW_MEMBER_HOURS * 3600:
                return "new member posting a link + @mention"
    return None


async def _handle_spam(update: Update,
                       context: ContextTypes.DEFAULT_TYPE,
                       reason: str) -> None:
    """Delete a spam message, record a strike, warn the user and
    log it to the admins. Bans on reaching the strike limit."""
    msg = update.message
    user = msg.from_user
    chat = msg.chat
    name = html.escape(user.first_name or "")

    try:
        await msg.delete()
    except Exception as exc:
        logger.warning("Could not delete spam message: %s", exc)

    strikes = db.record_strike(user.id, chat.id, reason,
                               window_hours=SPAM_STRIKE_WINDOW_HOURS)

    # Public warning (cooldown-guarded so one spammer can't flood).
    now = time.time()
    if now - _spam_warn_cooldown.get(user.id, 0) > _SPAM_WARN_TTL:
        _spam_warn_cooldown[user.id] = now
        try:
            await context.bot.send_message(
                chat.id,
                SPAM_WARNING.format(name=name, strikes=strikes,
                                    limit=SPAM_STRIKE_LIMIT))
        except Exception as exc:
            logger.warning("Could not send spam warning: %s", exc)

    # Log the delete to the admins.
    await notify_admins(
        context,
        "🗑️ <b>Spam deleted</b>\n\n"
        f"👤 {name} (id <code>{user.id}</code>)\n"
        f"💬 Group: {html.escape(chat.title or '')}\n"
        f"📌 Reason: {html.escape(reason)}\n"
        f"⚠️ Strikes (24h): <b>{strikes}/{SPAM_STRIKE_LIMIT}</b>")

    # 3rd strike within 24h = ban.
    if strikes >= SPAM_STRIKE_LIMIT:
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            db.record_spam_ban(user.id, chat.id)
            try:
                await context.bot.send_message(
                    chat.id, SPAM_BANNED.format(name=name))
            except Exception as exc:
                logger.warning("Could not send ban notice: %s", exc)
            await notify_admins(
                context,
                "🚫 <b>User banned for spam</b>\n\n"
                f"👤 {name} (id <code>{user.id}</code>)\n"
                f"💬 Group: {html.escape(chat.title or '')}\n"
                f"Reached {strikes} strikes in 24 hours.")
        except Exception as exc:
            # Usually: the bot lacks the "Ban Users" permission.
            logger.warning("Could not ban spammer %s: %s", user.id, exc)
            await notify_admins(
                context,
                "⚠️ <b>Could NOT ban a spammer</b>\n\n"
                f"👤 {name} (id <code>{user.id}</code>) reached "
                f"{strikes} strikes, but the ban failed: "
                f"{html.escape(str(exc))}\n"
                "Check that the bot is a group admin with the "
                "<b>Ban Users</b> permission.")


async def handle_group_message(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.from_user or msg.from_user.is_bot:
        return
    # Skip service messages (joins, leaves, pins, ...).
    if (msg.new_chat_members or msg.left_chat_member
            or msg.pinned_message or msg.group_chat_created):
        return

    user = msg.from_user

    # --- Force-subscribe gate (bot admins are exempt) --------------
    if not is_admin(user.id):
        member = await is_channel_member(context.bot, user.id)
        if member is False:
            try:
                await msg.delete()
            except Exception as exc:
                # Deleting needs "Delete Messages" admin permission.
                logger.warning("Could not delete group message: %s", exc)
            now = time.time()
            if now - _warn_cooldown.get(user.id, 0) > _WARN_TTL:
                _warn_cooldown[user.id] = now
                url = channel_url() or ""
                sent = await context.bot.send_message(
                    msg.chat_id,
                    GROUP_JOIN_WARNING.format(
                        name=html.escape(user.first_name or ""),
                        channel_url=url),
                    reply_markup=keyboards.channel_join_keyboard())
                # Ephemeral: the warning deletes itself after 30s.
                _schedule_warning_delete(context, msg.chat_id,
                                         sent.message_id)
            # Stop here: no other handler should process this message.
            raise ApplicationHandlerStop

    # --- Anti-spam (text/caption, not commands; admins exempt) -----
    # Runs BEFORE keyword auto-reply, and a deleted spam message
    # never reaches the auto-reply (ApplicationHandlerStop).
    text = msg.text or msg.caption
    if text and not text.startswith("/"):
        if not is_admin(user.id) and not await is_group_admin(
                context.bot, msg.chat_id, user.id):
            reason = _find_spam(text, msg.chat_id, user.id)
            if reason:
                await _handle_spam(update, context, reason)
                raise ApplicationHandlerStop

    # --- Keyword auto-reply (text messages only, not commands) ------
    if not msg.text or msg.text.startswith("/"):
        return
    now = time.time()
    if now - _keyword_cooldown.get(user.id, 0) < _KEYWORD_TTL:
        return
    low = msg.text.lower()
    for word, reply in db.get_keywords():
        if word.lower() in low:
            _keyword_cooldown[user.id] = now
            try:
                await msg.reply_text(reply)
            except Exception as exc:
                logger.warning("Keyword reply failed: %s", exc)
            return
