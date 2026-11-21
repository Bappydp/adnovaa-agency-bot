"""Auto-share: forward every new channel post to admin-saved groups.

The admin saves groups with /addsharegroup — the bot must already
be a member of the group (the owner adds it himself, the bot can't
join on its own). Whenever a new post appears in OUR channel, the
bot forwards it to every saved group, as itself
(@adnovaaagencybot) — never as the owner's personal account.
Edited channel posts are out of scope (new posts only).

Same ephemeral-DB caveat as everything else in this bot: the
saved-group list is wiped on every Render redeploy, so the admin
re-adds the groups with /addsharegroup after a deploy.
"""

import asyncio
import html
import logging
import re

from telegram import Update
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

import database as db
from content import ALERT_AUTOSHARE_FAILED
from handlers.common import (
    admin_only,
    is_our_channel,
    notify_admins,
)

logger = logging.getLogger(__name__)

# Max groups the admin can save for auto-share.
MAX_SHARE_GROUPS = 20

# Pause between forwards — keeps a burst of posts well under
# Telegram's per-minute limits (20 groups ≈ 10 seconds per post).
_FORWARD_DELAY = 0.5

_DM_ONLY = "Please use this command in a private chat with me."

_INVITE_LINK_MSG = (
    "That is a private invite link, and Telegram doesn't let a bot "
    "open it. For a private group, send its numeric ID instead — "
    "it starts with -100 (from a message link like "
    "t.me/c/1234567890/… the ID is -1001234567890)."
)

_MEMBER_STATUSES = ("creator", "administrator", "member", "restricted")


def _is_private(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == "private"


def _parse_target(raw: str) -> tuple[str | int | None, str | None]:
    """Parse a group identifier into something bot.get_chat accepts.

    Accepts a @username, a plain username, a t.me link, or a numeric
    chat ID. Returns (target, None) on success, or (None, error
    message) when the identifier can't be used.
    """
    raw = raw.strip()
    if not raw:
        return None, "Send a group link, @username or numeric ID."
    lowered = raw.lower()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/",
                   "https://telegram.me/", "http://telegram.me/",
                   "telegram.me/"):
        if lowered.startswith(prefix):
            path = raw[len(prefix):].strip("/").split("/")[0].split("?")[0]
            if (not path or path.startswith("+")
                    or path in ("joinchat", "c")):
                return None, _INVITE_LINK_MSG
            return "@" + path, None
    if raw.startswith("+"):
        return None, _INVITE_LINK_MSG
    if raw.startswith("@"):
        return raw, None
    # Numeric chat ID (groups are negative, e.g. -1001234567890).
    try:
        return int(raw), None
    except ValueError:
        pass
    # Plain username (must start with a letter, 5-32 chars).
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", raw):
        return "@" + raw, None
    return None, "I don't recognise that — send a group link, @username or numeric ID."


def _group_label(group: dict) -> str:
    """Safe one-line label for a saved group (HTML-escaped)."""
    title = html.escape(group.get("title") or "Untitled group")
    username = group.get("username")
    if username:
        return f"{title} (@{html.escape(username)})"
    return title


async def _bot_is_member(bot, chat_id: int) -> bool:
    """Is the bot itself a member of this chat?

    Fails CLOSED (False) on API errors: if we can't confirm the bot
    is in the group, the admin is told to add it and retry — a
    group we can't post to is useless for auto-share anyway.
    """
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        return member.status in _MEMBER_STATUSES
    except TelegramError as exc:
        logger.info("Bot membership check failed for %s: %s", chat_id, exc)
        return False


# ------------------------------------------------------------------
# Admin commands
# ------------------------------------------------------------------

@admin_only
async def addsharegroup_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addsharegroup <group link | @username | numeric chat id> —
    save a group so every new channel post is forwarded to it."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.message.reply_text(
            "Usage: <code>/addsharegroup &lt;group link or @username or ID&gt;</code>\n\n"
            "Example: <code>/addsharegroup @mygroup</code>\n\n"
            "Add me to the group FIRST — I can only share to groups "
            "I'm a member of.")
        return
    target, error = _parse_target(raw)
    if error:
        await update.message.reply_text(error)
        return
    try:
        chat = await context.bot.get_chat(target)
    except TelegramError:
        await update.message.reply_text(
            "Couldn't find that group — check the link, username or ID "
            "and try again.")
        return
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "That is not a group — auto-share only works with groups.")
        return
    if db.get_share_group(chat.id) is not None:
        await update.message.reply_text(
            f"That group is already on the auto-share list: "
            f"<b>{html.escape(chat.title or '')}</b> "
            f"(<code>{chat.id}</code>).")
        return
    if db.count_share_groups() >= MAX_SHARE_GROUPS:
        await update.message.reply_text(
            f"⚠️ The auto-share list is full ({MAX_SHARE_GROUPS} groups). "
            "Remove one with /delsharegroup before adding another.")
        return
    if not await _bot_is_member(context.bot, chat.id):
        await update.message.reply_text(
            f"I'm not a member of <b>{html.escape(chat.title or '')}</b> "
            "yet — add me to the group first, then run this command "
            "again.")
        return
    db.add_share_group(chat.id, chat.title, getattr(chat, "username", None),
                       update.effective_user.id)
    count = db.count_share_groups()
    await update.message.reply_text(
        f"✅ <b>{html.escape(chat.title or '')}</b> added to auto-share "
        f"({count}/{MAX_SHARE_GROUPS} groups).\n\n"
        "Every new channel post will be forwarded there.")


@admin_only
async def delsharegroup_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delsharegroup <group link | @username | numeric chat id> —
    stop forwarding channel posts to a group."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.message.reply_text(
            "Usage: <code>/delsharegroup &lt;group link or @username or ID&gt;</code>")
        return
    target, error = _parse_target(raw)
    if error:
        await update.message.reply_text(error)
        return
    if isinstance(target, int):
        chat_id = target
    else:
        try:
            chat = await context.bot.get_chat(target)
        except TelegramError:
            await update.message.reply_text(
                "Couldn't find that group — if it was deleted, remove it "
                "with its numeric ID instead.")
            return
        chat_id = chat.id
    if db.delete_share_group(chat_id):
        await update.message.reply_text(
            f"Group <code>{chat_id}</code> removed from auto-share.")
    else:
        await update.message.reply_text(
            f"Group <code>{chat_id}</code> is not on the auto-share list.")


@admin_only
async def sharegroups_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sharegroups — list all groups channel posts are shared to."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    groups = db.list_share_groups()
    if not groups:
        await update.message.reply_text(
            "No groups saved yet. Add one with "
            "<code>/addsharegroup &lt;group link or @username or ID&gt;</code> "
            "(add me to the group first).")
        return
    lines = [f"📤 <b>Auto-share groups ({len(groups)}/{MAX_SHARE_GROUPS})</b>\n"]
    for group in groups:
        lines.append(
            f"• {_group_label(group)} — <code>{group['chat_id']}</code>")
    await update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------
# Channel post handler
# ------------------------------------------------------------------

async def _forward_with_retry(bot, chat_id: int, from_chat_id: int,
                              message_id: int) -> None:
    """Forward one message, retrying ONCE after a RetryAfter wait.

    Any other error (or a second RetryAfter) is raised to the
    caller, which records it as a per-group failure.
    """
    try:
        await bot.forward_message(
            chat_id=chat_id, from_chat_id=from_chat_id,
            message_id=message_id)
    except RetryAfter as exc:
        logger.warning("Flood control for %s — waiting %ss and retrying "
                       "once", chat_id, exc.retry_after)
        await asyncio.sleep(exc.retry_after)
        await bot.forward_message(
            chat_id=chat_id, from_chat_id=from_chat_id,
            message_id=message_id)


async def handle_channel_post(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forward every new post from OUR channel to the saved groups.

    Posts from any other channel are ignored. A failure in one
    group never stops the others — all failures are collected and
    reported to the admins in ONE summary alert.
    """
    post = update.channel_post
    if post is None:
        return
    if not is_our_channel(update.effective_chat):
        return
    groups = db.list_share_groups()
    if not groups:
        logger.info("Channel post %s: no auto-share groups saved",
                    post.message_id)
        return
    logger.info("Auto-sharing channel post %s to %d group(s)",
                post.message_id, len(groups))
    failures: list[str] = []
    removed_any = False
    for i, group in enumerate(groups):
        if i:
            await asyncio.sleep(_FORWARD_DELAY)
        label = _group_label(group)
        try:
            await _forward_with_retry(
                context.bot, group["chat_id"],
                post.chat.id, post.message_id)
        except Forbidden as exc:
            # The bot was kicked/removed or can't send here — the
            # group is dead for auto-share, so drop it from the
            # list instead of failing on every future post.
            logger.warning("Auto-share to %s failed (%s) — removing "
                           "it from the list", group["chat_id"], exc)
            db.delete_share_group(group["chat_id"])
            removed_any = True
            failures.append(
                f"• {label} — bot was removed or can't send here "
                "(removed from the list)")
        except TelegramError as exc:
            logger.warning("Auto-share to %s failed: %s",
                           group["chat_id"], exc)
            reason = str(exc)[:100] or exc.__class__.__name__
            failures.append(f"• {label} — {html.escape(reason)}")
    if failures:
        removed_note = (
            "\n\nGroups marked 'removed from the list' were dropped — "
            "add them again with /addsharegroup after adding the bot "
            "back to the group."
            if removed_any else ""
        )
        await notify_admins(
            context,
            ALERT_AUTOSHARE_FAILED.format(
                failures="\n".join(failures),
                removed_note=removed_note))
