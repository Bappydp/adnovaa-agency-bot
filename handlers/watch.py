"""Membership watch: join/leave tracking, mass-leave alerts and
bot-status alerts.

Needs the bot to be an ADMIN of the group/channel to receive
chat_member updates — without that, Telegram sends nothing and
this handler stays silent (joins/leaves simply aren't recorded).

What it does:
  • Records every join (feeds the anti-spam "new member" check)
    and every leave.
  • Mass-leave alert: 5+ leaves in 1 hour (config thresholds)
    → one alert to the admins, at most once per 6 hours.
  • Bot-status alert: if the bot itself is removed/kicked from a
    chat, or loses its admin rights there, the admins are told
    immediately.
"""

import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from config import (
    MASS_LEAVE_ALERT_COOLDOWN_HOURS,
    MASS_LEAVE_THRESHOLD,
    MASS_LEAVE_WINDOW_HOURS,
)
from content import (
    ALERT_BOT_DEMOTED,
    ALERT_BOT_REMOVED,
    ALERT_MASS_LEAVE,
)
from handlers.common import notify_admins

logger = logging.getLogger(__name__)

_MEMBER_STATUSES = ("member", "administrator", "creator", "restricted")
_GONE_STATUSES = ("left", "kicked")


def _chat_label(chat) -> str:
    title = getattr(chat, "title", None) or getattr(
        chat, "username", None) or str(chat.id)
    kind = {"group": "group", "supergroup": "group",
            "channel": "channel"}.get(chat.type, chat.type)
    return f"{kind} <b>{html.escape(str(title))}</b>"


async def track_membership(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """ChatMemberHandler callback — covers both other members
    (update.chat_member) and the bot itself (update.my_chat_member)."""
    member_update = update.chat_member or update.my_chat_member
    if member_update is None:
        return
    chat = member_update.chat
    old = member_update.old_chat_member.status
    new = member_update.new_chat_member.status
    user = member_update.new_chat_member.user

    # --- The bot's OWN status changed ------------------------------
    if user.id == context.bot.id:
        if new in _GONE_STATUSES and old not in _GONE_STATUSES:
            logger.warning("Bot was removed from %s", chat.id)
            await notify_admins(
                context,
                ALERT_BOT_REMOVED.format(chat=_chat_label(chat)))
        elif old == "administrator" and new == "member":
            logger.warning("Bot lost admin rights in %s", chat.id)
            await notify_admins(
                context,
                ALERT_BOT_DEMOTED.format(chat=_chat_label(chat)))
        return

    # --- Other members: joins and leaves ---------------------------
    if old in _GONE_STATUSES and new in _MEMBER_STATUSES:
        db.record_join(chat.id, user.id)
        logger.info("User %s joined %s", user.id, chat.id)
        return

    if old in _MEMBER_STATUSES and new in _GONE_STATUSES:
        db.record_leave(chat.id, user.id)
        logger.info("User %s left %s", user.id, chat.id)
        due, leaves = db.mass_leave_alert_due(
            chat.id, MASS_LEAVE_THRESHOLD, MASS_LEAVE_WINDOW_HOURS,
            MASS_LEAVE_ALERT_COOLDOWN_HOURS)
        if due:
            window = (f"{MASS_LEAVE_WINDOW_HOURS:g} hour"
                      if MASS_LEAVE_WINDOW_HOURS == 1
                      else f"{MASS_LEAVE_WINDOW_HOURS:g} hours")
            await notify_admins(
                context,
                ALERT_MASS_LEAVE.format(
                    count=leaves, chat=_chat_label(chat),
                    window=window))
            db.record_mass_leave_alert(chat.id)
