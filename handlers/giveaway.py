"""Giveaway / contest: create, join (with referral entries),
info, draw a weighted random winner, end early."""

import html
import logging
import random
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards
from config import GROUP_ID
from content import GIVEAWAY_NONE_ACTIVE
from handlers.common import admin_only, describe_user, referral_link

logger = logging.getLogger(__name__)


def _giveaway_text(giveaway: dict, user_id: int,
                   context: ContextTypes.DEFAULT_TYPE) -> str:
    entries = db.get_user_entries(giveaway["id"], user_id)
    link = referral_link(context, user_id)
    total = sum(n for _, n in db.get_all_entries(giveaway["id"]))
    return (
        f"🎁 <b>Giveaway: {html.escape(giveaway['title'])}</b>\n\n"
        f"Ends: {giveaway['ends_at'][:10]}\n"
        f"Your entries: <b>{entries}</b>\n"
        f"Total entries so far: {total}\n\n"
        "Share your referral link — every friend who joins through it "
        "gives you +1 extra entry:\n"
        f"<code>{html.escape(link)}</code>"
    )


# ------------------------------------------------------------------
# Admin: create / draw / end
# ------------------------------------------------------------------

@admin_only
async def create_giveaway_command(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """/giveaway <title> | <days> — e.g. /giveaway Free Audit | 7"""
    raw = update.message.text.partition(" ")[2].strip()
    if "|" not in raw:
        await update.message.reply_text(
            "Usage: <code>/giveaway Title | days</code>\n\n"
            "Example: <code>/giveaway Free Ad Audit | 7</code>")
        return
    title, _, days_raw = raw.partition("|")
    title = title.strip()
    try:
        days = int(days_raw.strip())
        if days < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Days must be a whole number, 1 or more.")
        return
    if db.get_active_giveaway():
        await update.message.reply_text(
            "⚠️ A giveaway is already running. /draw or /endgiveaway it first.")
        return
    ends_at = datetime.now(timezone.utc) + timedelta(days=days)
    gid = db.create_giveaway(title, ends_at, update.effective_user.id)
    text = (
        f"🎁 <b>New Giveaway: {html.escape(title)}</b>\n\n"
        f"Ends: {ends_at.date().isoformat()} — join below!\n\n"
        "Share your referral link after joining to earn extra entries."
    )
    await update.message.reply_text(
        f"✅ Giveaway <b>#{gid}</b> created: {html.escape(title)} "
        f"(ends {ends_at.date().isoformat()}).")
    # Announce in the group, if configured.
    if GROUP_ID:
        try:
            await context.bot.send_message(
                GROUP_ID, text,
                reply_markup=keyboards.giveaway_join_keyboard(gid))
        except Exception as exc:
            logger.warning("Could not announce giveaway in group: %s", exc)
            await update.message.reply_text(
                "⚠️ Could not post the announcement in the group — "
                "is the bot an admin there, and is GROUP_ID correct?")


@admin_only
async def draw_command(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """/draw — pick a weighted random winner and announce them."""
    giveaway = db.get_active_giveaway()
    if not giveaway:
        await update.message.reply_text("No active giveaway to draw.")
        return
    entries = db.get_all_entries(giveaway["id"])
    if not entries:
        db.close_giveaway(giveaway["id"], None)
        await update.message.reply_text(
            "Nobody joined this giveaway — it has been closed.")
        return
    # Weighted draw: each entry is one ticket.
    tickets: list[int] = []
    for user_id, n in entries:
        tickets.extend([user_id] * n)
    winner_id = random.choice(tickets)
    db.close_giveaway(giveaway["id"], winner_id)

    winner = db.get_user(winner_id)
    if winner and winner.get("username"):
        winner_label = f"@{winner['username']}"
    elif winner:
        winner_label = html.escape(winner.get("first_name") or "Winner")
    else:
        winner_label = f"user {winner_id}"
    total_entries = len(tickets)
    text = (
        f"🏆 <b>Giveaway Winner: {html.escape(giveaway['title'])}</b>\n\n"
        f"🎉 Congratulations {winner_label}!\n"
        f"You won out of {len(entries)} participants "
        f"({total_entries} total entries).\n\n"
        "We will contact you shortly to arrange your prize."
    )
    await update.message.reply_text(text)
    try:
        await context.bot.send_message(
            winner_id,
            f"🏆 <b>You won the giveaway!</b>\n\n"
            f"Giveaway: {html.escape(giveaway['title'])}\n"
            "We will contact you shortly to arrange your prize. "
            "Congratulations! 🎉")
    except Exception as exc:
        logger.warning("Could not DM giveaway winner %s: %s", winner_id, exc)
    if GROUP_ID:
        try:
            await context.bot.send_message(GROUP_ID, text)
        except Exception as exc:
            logger.warning("Could not announce winner in group: %s", exc)


@admin_only
async def end_giveaway_command(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """/endgiveaway — close the active giveaway without a winner."""
    giveaway = db.get_active_giveaway()
    if not giveaway:
        await update.message.reply_text("No active giveaway to end.")
        return
    db.close_giveaway(giveaway["id"], None)
    await update.message.reply_text(
        f"Giveaway <b>{html.escape(giveaway['title'])}</b> has been ended.")


# ------------------------------------------------------------------
# Users: join + info
# ------------------------------------------------------------------

async def join_callback(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """'Join Giveaway' button — works in DMs and in the group."""
    query = update.callback_query
    data = query.data or ""
    user = update.effective_user
    db.record_button_click(user.id, "join_giveaway")
    try:
        gid = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Invalid giveaway.", show_alert=True)
        return
    giveaway = db.get_active_giveaway()
    if not giveaway or giveaway["id"] != gid:
        await query.answer("This giveaway has ended.", show_alert=True)
        return
    # Make sure the user is registered (group joins may be first contact).
    db.add_or_update_user(user.id, user.username, user.first_name)
    is_new = db.join_giveaway(gid, user.id)
    entries = db.get_user_entries(gid, user.id)
    link = referral_link(context, user.id)
    if is_new:
        await query.answer("You're in! Good luck 🍀")
    else:
        await query.answer(f"You're already in — {entries} entries.")
    # Send details as a DM so the referral link is easy to copy.
    try:
        await context.bot.send_message(
            user.id,
            f"🎁 You're in the giveaway: "
            f"<b>{html.escape(giveaway['title'])}</b>\n"
            f"Your entries: <b>{entries}</b>\n\n"
            "Share your referral link for +1 entry per friend who joins:\n"
            f"<code>{html.escape(link)}</code>")
    except Exception as exc:
        # User never started the bot in DM — the group answer above
        # already confirmed the join.
        logger.info("Could not DM giveaway join details to %s: %s",
                    user.id, exc)


async def giveawayinfo_command(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """/giveawayinfo — active giveaway + the user's entries."""
    user = update.effective_user
    db.record_command(user.id, "/giveawayinfo")
    giveaway = db.get_active_giveaway()
    if not giveaway:
        await update.message.reply_text(GIVEAWAY_NONE_ACTIVE)
        return
    await update.message.reply_text(
        _giveaway_text(giveaway, user.id, context),
        reply_markup=keyboards.giveaway_join_keyboard(giveaway["id"]))
