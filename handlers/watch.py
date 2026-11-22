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
  • Auto-post auto-discovery: the moment the bot is PROMOTED to
    admin in a channel/group, that chat is added to the
    auto-post target list (and the admins get one short note);
    when the bot is demoted, kicked or leaves a saved target, the
    chat is dropped from the list (noted in the same alert).
    Chats where the bot was ALREADY an admin before this feature
    was deployed don't auto-register — those are added once by
    hand with /addposttarget.
  • Channel-gate cache refresh: the moment someone joins OUR
    channel, they are marked as a member in the membership cache
    (so their very next group message passes at once); when they
    leave the channel, the cached entry is dropped so the gate
    re-checks them live. Only updates about our gated channel
    touch the cache — group joins/leaves never do.
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
    AUTOPOST_TARGET_ADDED,
    AUTOPOST_TARGET_FULL,
)
from handlers.autopost import MAX_POST_TARGETS
from handlers.common import (
    invalidate_member_cache,
    is_our_channel,
    mark_member_cache,
    notify_admins,
)

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
            text = ALERT_BOT_REMOVED.format(chat=_chat_label(chat))
            if db.delete_post_target(chat.id):
                # It was an auto-post target — drop it and note it
                # in the SAME alert (still one message total).
                text += ("\n\nIt was also removed from the "
                         "auto-post target list.")
            await notify_admins(context, text)
        elif old == "administrator" and new == "member":
            logger.warning("Bot lost admin rights in %s", chat.id)
            text = ALERT_BOT_DEMOTED.format(chat=_chat_label(chat))
            if db.delete_post_target(chat.id):
                # Auto-post needs admin rights — drop it and note
                # it in the SAME alert (still one message total).
                text += ("\n\nIt was also removed from the "
                         "auto-post target list.")
            await notify_admins(context, text)
        elif (new == "administrator" and old != "administrator"
                and chat.type in ("channel", "group", "supergroup")):
            # Promoted to admin — auto-register as an auto-post
            # target (my_chat_member only fires on
            # CHANGES, so chats where the bot was already an admin
            # don't auto-register; those are added by hand with
            # /addposttarget).
            if db.get_post_target(chat.id) is None:
                if db.count_post_targets() >= MAX_POST_TARGETS:
                    logger.warning(
                        "Bot promoted in %s but the auto-post list "
                        "is full (%d targets)", chat.id,
                        MAX_POST_TARGETS)
                    await notify_admins(
                        context,
                        AUTOPOST_TARGET_FULL.format(
                            chat=_chat_label(chat),
                            max=MAX_POST_TARGETS))
                else:
                    db.add_post_target(
                        chat.id, getattr(chat, "title", None),
                        getattr(chat, "username", None), chat.type,
                        None)
                    count = db.count_post_targets()
                    logger.info("Bot promoted in %s — auto-added as "
                                "auto-post target (%d/%d)", chat.id,
                                count, MAX_POST_TARGETS)
                    await notify_admins(
                        context,
                        AUTOPOST_TARGET_ADDED.format(
                            chat=_chat_label(chat), count=count,
                            max=MAX_POST_TARGETS))
        return

    # --- Other members: joins and leaves ---------------------------
    if old in _GONE_STATUSES and new in _MEMBER_STATUSES:
        db.record_join(chat.id, user.id)
        logger.info("User %s joined %s", user.id, chat.id)
        if is_our_channel(chat):
            # They just joined the channel — their very next group
            # message must go through at once, no tap needed.
            mark_member_cache(user.id)
        return

    if old in _MEMBER_STATUSES and new in _GONE_STATUSES:
        db.record_leave(chat.id, user.id)
        logger.info("User %s left %s", user.id, chat.id)
        if is_our_channel(chat):
            # They left the channel — drop any cached "member"
            # result so the gate re-checks them live next time.
            invalidate_member_cache(user.id)
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
