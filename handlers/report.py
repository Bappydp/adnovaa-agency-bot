"""/report — members flag a spam/abusive message to the admins.

In the group: reply to any message with /report (optional reason
after the command). The admins get the message with context plus
[Delete message] [Ban user] [Dismiss] buttons.

In a DM to the bot: /report <description> sends a text report to
the admins (Dismiss button only).

Rate limit: max 3 reports per user per hour (REPORT_LIMIT_PER_HOUR).
"""

import html
import json
import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import database as db
import keyboards
from config import REPORT_LIMIT_PER_HOUR
from content import (
    REPORT_ADMIN_TITLE,
    REPORT_LIMIT,
    REPORT_NEED_REPLY,
    REPORT_NEED_TEXT,
    REPORT_THANKS,
)
from handlers.common import describe_user, is_admin, message_link

logger = logging.getLogger(__name__)

_ACTIONS = {
    "delete": "🗑️ Message deleted",
    "ban": "🚫 User banned + message deleted",
    "dismiss": "Dismissed — no action taken",
}


def _report_text(report_id: int, chat_title: str, reporter,
                 reported, reason: str | None, excerpt: str | None,
                 link: str | None) -> str:
    lines = [
        REPORT_ADMIN_TITLE.format(report_id=report_id),
        "",
        f"💬 Chat: {html.escape(chat_title)}",
        f"👤 Reporter: {describe_user(reporter)}",
    ]
    if reported is not None:
        lines.append(f"🎯 Reported: {describe_user(reported)}")
    if reason:
        lines.append(f"📝 Reason: {html.escape(reason)}")
    if excerpt:
        lines.append(f"💬 Message:\n<i>{html.escape(excerpt)}</i>")
    if link:
        lines.append(f"🔗 <a href=\"{link}\">Open message</a>")
    return "\n".join(lines)


async def report_command(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """/report — group (reply to a message) or DM (describe it)."""
    user = update.effective_user
    msg = update.message
    chat = update.effective_chat
    reason = msg.text.partition(" ")[2].strip() or None
    is_group = chat.type in ("group", "supergroup")

    if is_group:
        target = msg.reply_to_message
        if not target:
            await msg.reply_text(REPORT_NEED_REPLY)
            return
        reported = target.from_user
        if reported is None or reported.is_bot:
            await msg.reply_text(
                "That message has no user to report.")
            return
        excerpt = target.text or target.caption
        if excerpt and len(excerpt) > 500:
            excerpt = excerpt[:497] + "…"
        link = message_link(chat, target.message_id)
        chat_title = chat.title or "Group"
        reported_id = reported.id
        message_id = target.message_id
    else:
        if not reason:
            await msg.reply_text(REPORT_NEED_TEXT)
            return
        reported = None
        reported_id = None
        message_id = None
        excerpt = reason
        reason = None
        link = None
        chat_title = "DM to the bot"

    # Rate limit: 3 reports per user per hour.
    if db.count_reports_last_hour(user.id) >= REPORT_LIMIT_PER_HOUR:
        await msg.reply_text(REPORT_LIMIT)
        return

    report_id = db.create_report(user.id, reported_id, chat.id,
                                 message_id, reason)
    text = _report_text(report_id, chat_title, user, reported, reason,
                        excerpt, link)
    markup = keyboards.report_keyboard(
        report_id, with_actions=is_group)

    # Send to every admin; remember the copies so an action can
    # update all of them.
    delivered = []
    from handlers.common import notify_admins
    delivered = await notify_admins(context, text, reply_markup=markup)
    if delivered:
        db.set_report_admin_messages(
            report_id, json.dumps(delivered))

    await msg.reply_text(REPORT_THANKS)


async def report_callback(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin buttons on a report: delete / ban / dismiss."""
    query = update.callback_query
    user = update.effective_user
    data = query.data or ""

    if not is_admin(user.id):
        await query.answer("Admins only.", show_alert=True)
        return

    parts = data.split(":")
    if len(parts) != 3:
        await query.answer("Invalid report button.", show_alert=True)
        return
    _, action, report_id_raw = parts
    if action not in _ACTIONS:
        await query.answer("Unknown action.", show_alert=True)
        return
    try:
        report_id = int(report_id_raw)
    except ValueError:
        await query.answer("Invalid report.", show_alert=True)
        return

    report = db.get_report(report_id)
    if report is None:
        await query.answer("That report no longer exists.",
                           show_alert=True)
        return
    if report["status"] != "open":
        await query.answer("This report was already handled.",
                           show_alert=True)
        return

    # Claim it first (race-safe: only the first admin wins).
    if not db.set_report_status(report_id, action, user.id):
        await query.answer("Another admin just handled this report.",
                           show_alert=True)
        return

    # Carry out the action. A message that is already gone counts
    # as done — never crash the handler on it.
    note = ""
    chat_id = report["chat_id"]
    message_id = report["message_id"]
    reported_id = report["reported_user_id"]

    if action in ("delete", "ban") and message_id:
        try:
            await context.bot.delete_message(chat_id, message_id)
        except BadRequest as exc:
            if "not found" in str(exc).lower():
                note = " (message was already gone)"
            else:
                logger.warning("Report delete failed: %s", exc)
                note = f" (delete failed: {exc})"
        except Exception as exc:
            logger.warning("Report delete failed: %s", exc)
            note = f" (delete failed: {exc})"

    if action == "ban" and reported_id:
        try:
            await context.bot.ban_chat_member(chat_id, reported_id)
        except Exception as exc:
            logger.warning("Report ban failed: %s", exc)
            note += f" (ban failed: {exc})"

    await query.answer(_ACTIONS[action].split("—")[0].strip())

    # Update the admin message(s) to show the outcome.
    admin_name = html.escape(user.full_name or "")
    outcome = (
        f"\n\n✅ <b>Handled by {admin_name}</b>\n"
        f"{_ACTIONS[action]}{html.escape(note)}"
    )
    original = query.message.text_html if query.message else ""
    new_text = original + outcome
    try:
        await query.edit_message_text(new_text, reply_markup=None)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            logger.warning("Could not edit report message: %s", exc)

    # Update the other admins' copies too, if we stored them.
    if report.get("admin_messages"):
        try:
            copies = json.loads(report["admin_messages"])
        except (ValueError, TypeError):
            copies = []
        for admin_id, mid in copies:
            if (query.message and query.message.chat_id == admin_id
                    and query.message.message_id == mid):
                continue  # already edited above
            try:
                await context.bot.edit_message_text(
                    new_text, chat_id=admin_id, message_id=mid)
            except Exception as exc:
                logger.warning("Could not update report copy %s:%s: %s",
                               admin_id, mid, exc)
