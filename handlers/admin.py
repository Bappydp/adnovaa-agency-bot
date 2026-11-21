"""Admin-only commands: /broadcast, /stats, coupons, VIP,
group keywords, and /adminhelp."""

import asyncio
import html
import logging
from datetime import date

from telegram import Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

import database as db
from config import (
    GROUP_ID,
    MASS_LEAVE_ALERT_COOLDOWN_HOURS,
    MASS_LEAVE_THRESHOLD,
    MASS_LEAVE_WINDOW_HOURS,
    SPAM_STRIKE_LIMIT,
    SPAM_STRIKE_WINDOW_HOURS,
)
from handlers.common import admin_only, describe_user

logger = logging.getLogger(__name__)


@admin_only
async def adminhelp_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🛠️ <b>Admin Commands</b>\n\n"
        "<b>Broadcast & stats</b>\n"
        "• <code>/broadcast &lt;message&gt;</code> — message all bot users\n"
        "• <code>/stats</code> — users, clicks, leads, VIPs\n\n"
        "<b>Coupons</b>\n"
        "• <code>/addcoupon CODE PERCENT EXPIRY</code> — e.g. <code>/addcoupon WELCOME20 20 2026-12-31</code>\n"
        "• <code>/coupons</code> — list coupons\n"
        "• <code>/delcoupon CODE</code> — delete a coupon\n\n"
        "<b>Giveaways</b>\n"
        "• <code>/giveaway Title | days</code> — start one\n"
        "• <code>/draw</code> — pick the winner\n"
        "• <code>/endgiveaway</code> — close without a winner\n"
        "• <code>/giveawayinfo</code> — current giveaway\n\n"
        "<b>VIP</b>\n"
        "• <code>/vip &lt;user_id&gt;</code> — or reply to their message\n"
        "• <code>/unvip &lt;user_id&gt;</code>\n"
        "• <code>/vipinfo</code> — list VIP members\n\n"
        "<b>Group keywords</b>\n"
        "• <code>/addkeyword word | reply</code>\n"
        "• <code>/delkeyword word</code>\n"
        "• <code>/keywords</code> — list them\n\n"
        "<b>Anti-spam</b>\n"
        "• <code>/spamstats</code> — strikes and bans\n"
        "• <code>/addspamword word</code> — add a spam word\n"
        "• <code>/delspamword word</code> — remove a spam word\n"
        "• <code>/spamwords</code> — list spam words\n\n"
        "<b>Alerts</b>\n"
        "• <code>/alerts</code> — recent leaves and alert status"
    )


# ------------------------------------------------------------------
# Broadcast
# ------------------------------------------------------------------

@admin_only
async def broadcast_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """/broadcast <message> — send to every user who started the bot."""
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text(
            "Usage: <code>/broadcast Your message here</code>")
        return
    user_ids = db.get_all_user_ids()
    if not user_ids:
        await update.message.reply_text("No users to broadcast to yet.")
        return
    status = await update.message.reply_text(
        f"📣 Broadcasting to {len(user_ids)} users…")
    sent = failed = blocked = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(user_id, text)
            sent += 1
        except Forbidden:
            db.mark_blocked(user_id)
            blocked += 1
        except Exception as exc:
            logger.warning("Broadcast to %s failed: %s", user_id, exc)
            failed += 1
        # ~20 messages/second — stays under Telegram's rate limit.
        await asyncio.sleep(0.05)
    await status.edit_text(
        f"📣 <b>Broadcast done</b>\n\n"
        f"✅ Sent: {sent}\n"
        f"🚫 Blocked the bot: {blocked}\n"
        f"❌ Failed: {failed}")


# ------------------------------------------------------------------
# Stats
# ------------------------------------------------------------------

@admin_only
async def stats_command(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — users, growth, clicks, commands, leads, VIPs."""
    s = db.get_stats()
    lines = [
        "📊 <b>Bot Stats</b>\n",
        f"👥 Total users: <b>{s['total_users']}</b>",
        f"🆕 New today: <b>{s['new_today']}</b>",
        f"📈 New this week: <b>{s['new_week']}</b>",
        f"🎯 Leads: <b>{s['total_leads']}</b>",
        f"👑 VIP members: <b>{s['vip_count']}</b>",
        f"🚫 Blocked the bot: <b>{s['blocked_count']}</b>",
    ]
    if s["top_buttons"]:
        lines.append("\n<b>Top buttons:</b>")
        for button, count in s["top_buttons"]:
            lines.append(f"  • <code>{html.escape(button)}</code> — {count}")
    if s["top_commands"]:
        lines.append("\n<b>Top commands:</b>")
        for command, count in s["top_commands"]:
            lines.append(f"  • <code>{html.escape(command)}</code> — {count}")
    await update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------
# Coupons
# ------------------------------------------------------------------

@admin_only
async def addcoupon_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addcoupon CODE PERCENT EXPIRY — e.g. /addcoupon WELCOME20 20 2026-12-31"""
    args = context.args or []
    if len(args) != 3:
        await update.message.reply_text(
            "Usage: <code>/addcoupon CODE PERCENT EXPIRY</code>\n\n"
            "Example: <code>/addcoupon WELCOME20 20 2026-12-31</code>")
        return
    code, percent_raw, expiry = args
    try:
        percent = int(percent_raw)
        if not 1 <= percent <= 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Percent must be a number from 1 to 100.")
        return
    try:
        date.fromisoformat(expiry)
    except ValueError:
        await update.message.reply_text(
            "Expiry must be a date like 2026-12-31.")
        return
    db.add_coupon(code, percent, expiry, update.effective_user.id)
    await update.message.reply_text(
        f"✅ Coupon <b>{html.escape(code.upper())}</b> created — "
        f"{percent}% off, expires {expiry}.")


@admin_only
async def coupons_command(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """/coupons — list all coupons with expiry and redemption counts."""
    coupons = db.list_coupons()
    if not coupons:
        await update.message.reply_text(
            "No coupons yet. Create one with "
            "<code>/addcoupon CODE PERCENT EXPIRY</code>.")
        return
    today = date.today().isoformat()
    lines = ["🎟️ <b>Coupons</b>\n"]
    for c in coupons:
        expired = " ⏰ EXPIRED" if c["expiry"] < today else ""
        lines.append(
            f"• <code>{html.escape(c['code'])}</code> — {c['percent']}% off, "
            f"expires {c['expiry']}, used {c['redemptions']}×{expired}")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def delcoupon_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delcoupon CODE"""
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Usage: <code>/delcoupon CODE</code>")
        return
    if db.delete_coupon(args[0]):
        await update.message.reply_text(
            f"Coupon <b>{html.escape(args[0].upper())}</b> deleted.")
    else:
        await update.message.reply_text(
            f"No coupon named <b>{html.escape(args[0].upper())}</b>.")


# ------------------------------------------------------------------
# VIP
# ------------------------------------------------------------------

def _resolve_target(update: Update) -> int | None:
    """User ID from a reply, or from the first command argument."""
    replied = update.message.reply_to_message
    if replied and replied.from_user:
        return replied.from_user.id
    args = update.effective_message.text.split()
    if len(args) >= 2 and args[1].isdigit():
        return int(args[1])
    return None


@admin_only
async def vip_command(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    """/vip <user_id> — or reply to the user's message with /vip."""
    target = _resolve_target(update)
    if target is None:
        await update.message.reply_text(
            "Usage: <code>/vip &lt;user_id&gt;</code> — or reply to the "
            "user's message with /vip.")
        return
    if not db.set_vip(target, True):
        await update.message.reply_text(
            "That user hasn't started the bot yet — I don't know them.")
        return
    await update.message.reply_text(f"👑 User <code>{target}</code> is now VIP.")
    try:
        await context.bot.send_message(
            target,
            "👑 <b>You're now a VIP member!</b>\n\n"
            "You get early access to offers, priority replies and "
            "VIP-only discounts. Tap /start to see your VIP menu.")
    except Exception as exc:
        logger.warning("Could not notify new VIP %s: %s", target, exc)


@admin_only
async def unvip_command(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unvip <user_id> — or reply to the user's message with /unvip."""
    target = _resolve_target(update)
    if target is None:
        await update.message.reply_text(
            "Usage: <code>/unvip &lt;user_id&gt;</code> — or reply to the "
            "user's message with /unvip.")
        return
    if not db.set_vip(target, False):
        await update.message.reply_text(
            "That user hasn't started the bot yet — I don't know them.")
        return
    await update.message.reply_text(
        f"User <code>{target}</code> is no longer VIP.")


@admin_only
async def vipinfo_command(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """/vipinfo — list all VIP members."""
    vips = db.list_vips()
    if not vips:
        await update.message.reply_text(
            "No VIP members yet. Add one with <code>/vip &lt;user_id&gt;</code>.")
        return
    lines = [f"👑 <b>VIP Members ({len(vips)})</b>\n"]
    for v in vips:
        name = html.escape(v.get("first_name") or "")
        uname = f"@{v['username']}" if v.get("username") else ""
        lines.append(f"• {name} {html.escape(uname)} — <code>{v['user_id']}</code>")
    await update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------
# Group keywords
# ------------------------------------------------------------------

@admin_only
async def addkeyword_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addkeyword word | reply"""
    raw = update.message.text.partition(" ")[2].strip()
    if "|" not in raw:
        await update.message.reply_text(
            "Usage: <code>/addkeyword word | reply text</code>\n\n"
            "Example: <code>/addkeyword website | We build fast websites — DM this bot!</code>")
        return
    word, _, reply = raw.partition("|")
    word, reply = word.strip(), reply.strip()
    if not word or not reply:
        await update.message.reply_text("Both the word and the reply are needed.")
        return
    db.add_keyword(word, reply, update.effective_user.id)
    await update.message.reply_text(
        f"✅ Keyword <b>{html.escape(word.lower())}</b> added.")


@admin_only
async def delkeyword_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delkeyword word"""
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Usage: <code>/delkeyword word</code>")
        return
    if db.delete_keyword(args[0]):
        await update.message.reply_text(
            f"Keyword <b>{html.escape(args[0].lower())}</b> deleted.")
    else:
        await update.message.reply_text(
            f"No keyword named <b>{html.escape(args[0].lower())}</b>.")


@admin_only
async def keywords_command(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/keywords — list all group auto-reply keywords."""
    keywords = db.get_keywords()
    if not keywords:
        await update.message.reply_text("No keywords set.")
        return
    lines = ["🔑 <b>Group Keywords</b>\n"]
    for word, reply in keywords:
        short = reply if len(reply) <= 60 else reply[:57] + "…"
        lines.append(f"• <b>{html.escape(word)}</b> → {html.escape(short)}")
    await update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------
# Anti-spam
# ------------------------------------------------------------------

@admin_only
async def spamstats_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """/spamstats — spam strikes and bans today / this week."""
    s = db.get_spam_stats()
    await update.message.reply_text(
        "🛡️ <b>Anti-Spam Stats</b>\n\n"
        f"⚠️ Strikes today: <b>{s['strikes_today']}</b>\n"
        f"🚫 Bans today: <b>{s['bans_today']}</b>\n"
        f"⚠️ Strikes this week: <b>{s['strikes_week']}</b>\n"
        f"🚫 Bans this week: <b>{s['bans_week']}</b>\n\n"
        f"Rule: {SPAM_STRIKE_LIMIT} strikes in "
        f"{SPAM_STRIKE_WINDOW_HOURS}h = ban.")


@admin_only
async def addspamword_command(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addspamword <word or phrase> — add to the spam list."""
    word = update.message.text.partition(" ")[2].strip()
    if not word:
        await update.message.reply_text(
            "Usage: <code>/addspamword word or phrase</code>\n\n"
            "Only add OBVIOUS spam — never normal words like "
            "<i>price</i> or <i>service</i>, or real members' "
            "messages will be deleted.")
        return
    db.add_spam_word(word, update.effective_user.id)
    await update.message.reply_text(
        f"✅ Spam word <b>{html.escape(word.lower())}</b> added.")


@admin_only
async def delspamword_command(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delspamword <word or phrase>"""
    word = update.message.text.partition(" ")[2].strip()
    if not word:
        await update.message.reply_text(
            "Usage: <code>/delspamword word or phrase</code>")
        return
    if db.delete_spam_word(word):
        await update.message.reply_text(
            f"Spam word <b>{html.escape(word.lower())}</b> deleted.")
    else:
        await update.message.reply_text(
            f"No spam word named <b>{html.escape(word.lower())}</b>.")


@admin_only
async def spamwords_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """/spamwords — list all spam words/phrases."""
    words = db.get_spam_words()
    if not words:
        await update.message.reply_text("No spam words set.")
        return
    lines = [f"🚫 <b>Spam Words ({len(words)})</b>\n"]
    for word in words:
        lines.append(f"• <code>{html.escape(word)}</code>")
    await update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------
# Alerts
# ------------------------------------------------------------------

@admin_only
async def alerts_command(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """/alerts — recent leaves, member count and alert status."""
    if not GROUP_ID:
        await update.message.reply_text(
            "⚠️ <b>Alerts</b>\n\n"
            "GROUP_ID is not set, so I can't show the group's member "
            "count. Set the group's numeric ID (starts with -100) as "
            "GROUP_ID on Render.\n\n"
            "Mass-leave alerts still work — they are checked per chat "
            "whenever someone leaves.")
        return
    stats = db.get_leave_stats(GROUP_ID)
    try:
        members = await context.bot.get_chat_member_count(GROUP_ID)
        members_line = f"👥 Current members: <b>{members}</b>"
    except Exception as exc:
        logger.warning("Could not get member count: %s", exc)
        members_line = "👥 Current members: <i>unknown (bot may not be a group admin)</i>"
    last_alert = db.get_alert_value(f"mass_leave:{GROUP_ID}")
    if last_alert:
        alert_line = f"🔔 Last mass-leave alert: {last_alert[:16]} UTC"
    else:
        alert_line = "🔔 Last mass-leave alert: never"
    await update.message.reply_text(
        "🔔 <b>Group Alerts</b>\n\n"
        f"{members_line}\n"
        f"👋 Leaves in the last hour: <b>{stats['last_hour']}</b>\n"
        f"👋 Leaves in the last 24h: <b>{stats['last_24h']}</b>\n\n"
        f"{alert_line}\n"
        f"Alert rule: {MASS_LEAVE_THRESHOLD}+ leaves in "
        f"{MASS_LEAVE_WINDOW_HOURS:g}h triggers one alert, "
        f"at most once per {MASS_LEAVE_ALERT_COOLDOWN_HOURS:g}h.")
