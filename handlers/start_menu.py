"""/start, /help, /cancel and the main-menu button callbacks."""

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import database as db
import keyboards
from content import (
    CONTACT,
    FAQ,
    GIVEAWAY_NONE_ACTIVE,
    HELP_TEXT,
    PAYMENT_INFO,
    PORTFOLIO,
    VIP_OFFERS,
    WELCOME,
    WELCOME_NOT_SUBSCRIBED,
    render_packages,
    render_services,
)
from handlers.common import (
    channel_url,
    get_bot_username,
    invalidate_member_cache,
    is_channel_member,
    mark_lead_and_notify,
    referral_link,
)

logger = logging.getLogger(__name__)


async def _safe_edit(query, text: str, reply_markup=None) -> None:
    """Edit a message, ignoring the harmless 'not modified' error."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


def _menu_for(user_id: int, subscribed: bool):
    user = db.get_user(user_id)
    is_vip = bool(user and user["is_vip"])
    return keyboards.main_menu(is_vip=is_vip, subscribed=subscribed)


# ------------------------------------------------------------------
# /start — welcome + menu, referral handling, subscribe gate
# ------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.record_command(user.id, "/start")

    # Referral deep link: /start ref_<user_id>
    referred_by = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                ref_id = int(arg[4:])
                if ref_id != user.id:
                    referred_by = ref_id
            except ValueError:
                pass

    is_new = db.add_or_update_user(user.id, user.username,
                                   user.first_name, referred_by)

    # Referral bonus: if the referrer joined the active giveaway,
    # they get +1 entry for bringing a new user.
    if is_new and referred_by:
        giveaway = db.get_active_giveaway()
        if giveaway and db.get_user_entries(giveaway["id"], referred_by) > 0:
            total = db.add_entries(giveaway["id"], referred_by, 1)
            try:
                await context.bot.send_message(
                    referred_by,
                    "🎉 Someone joined through your referral link!\n"
                    f"You now have <b>{total} entries</b> in the giveaway "
                    f"<b>{html.escape(giveaway['title'])}</b>.")
            except Exception as exc:
                logger.warning("Could not notify referrer %s: %s",
                               referred_by, exc)

    member = await is_channel_member(context.bot, user.id)
    subscribed = member is not False  # None (check failed) => don't block
    text = WELCOME if subscribed else WELCOME_NOT_SUBSCRIBED
    await update.message.reply_text(
        text, reply_markup=_menu_for(user.id, subscribed))


async def help_command(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    db.record_command(update.effective_user.id, "/help")
    await update.message.reply_text(
        HELP_TEXT, reply_markup=keyboards.main_menu())


async def cancel_command(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_coupon", None)
    await update.message.reply_text(
        "Cancelled 🙂", reply_markup=keyboards.main_menu())


# ------------------------------------------------------------------
# Button callbacks
# ------------------------------------------------------------------

async def on_callback(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    user = update.effective_user
    db.record_button_click(user.id, data)
    db.update_activity(user.id)
    await query.answer()

    if data == "menu_services":
        await mark_lead_and_notify(context, user)
        await _safe_edit(query, render_services(),
                         keyboards.back_menu())

    elif data == "menu_pricing":
        await mark_lead_and_notify(context, user)
        await _safe_edit(query, render_packages(),
                         keyboards.back_menu())

    elif data == "menu_portfolio":
        await _safe_edit(query, PORTFOLIO, keyboards.back_menu())

    elif data == "menu_contact":
        await mark_lead_and_notify(context, user)
        await _safe_edit(query, CONTACT, keyboards.back_menu())

    elif data == "menu_payment":
        await _safe_edit(query, PAYMENT_INFO, keyboards.back_menu())

    elif data == "menu_vip":
        await _safe_edit(query, VIP_OFFERS, keyboards.back_menu())

    elif data == "menu_faq":
        await _safe_edit(
            query,
            "❓ <b>Frequently Asked Questions</b>\n\nTap a topic 👇",
            keyboards.faq_keyboard())

    elif data.startswith("faq:"):
        try:
            idx = int(data.split(":", 1)[1])
            entry = FAQ[idx]
        except (ValueError, IndexError):
            await _safe_edit(query, "That question no longer exists.",
                             keyboards.faq_keyboard())
            return
        await _safe_edit(query, entry["answer"],
                         keyboards.faq_back_keyboard())

    elif data == "menu_giveaway":
        await _show_giveaway(query, context, user.id)

    elif data == "menu_redeem":
        context.user_data["awaiting_coupon"] = True
        await _safe_edit(
            query,
            "🎟️ <b>Redeem a Coupon</b>\n\n"
            "Send your coupon code as your next message "
            "(or /cancel to go back).",
            keyboards.back_menu())

    elif data == "menu_back":
        member = await is_channel_member(context.bot, user.id)
        subscribed = member is not False
        await _safe_edit(query, WELCOME,
                         _menu_for(user.id, subscribed))

    elif data == "check_joined":
        # Re-check right now (bypass the cache).
        invalidate_member_cache(user.id)
        member = await is_channel_member(context.bot, user.id)
        if member is False:
            url = channel_url() or ""
            await query.answer(
                "You haven't joined the channel yet — tap Join Channel first.",
                show_alert=True)
            return
        # Joined (or the check failed — fail open, welcome them).
        chat_type = query.message.chat.type if query.message else "private"
        if chat_type in ("group", "supergroup"):
            await _safe_edit(
                query,
                f"✅ {html.escape(user.first_name or '')}, you're in — "
                "welcome! You can write in the group now.")
        else:
            await _safe_edit(query, WELCOME, _menu_for(user.id, True))


async def _show_giveaway(query, context: ContextTypes.DEFAULT_TYPE,
                         user_id: int) -> None:
    giveaway = db.get_active_giveaway()
    if not giveaway:
        await _safe_edit(query, GIVEAWAY_NONE_ACTIVE,
                         keyboards.back_menu())
        return
    entries = db.get_user_entries(giveaway["id"], user_id)
    link = referral_link(context, user_id)
    text = (
        f"🎁 <b>Giveaway: {html.escape(giveaway['title'])}</b>\n\n"
        f"Ends: {giveaway['ends_at'][:10]}\n"
        f"Your entries: <b>{entries}</b>\n\n"
        "Share your referral link — every friend who joins through it "
        "gives you +1 extra entry:\n"
        f"<code>{html.escape(link)}</code>"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎁 Join Giveaway",
            callback_data=f"join_giveaway:{giveaway['id']}")],
        [InlineKeyboardButton(
            "⬅️ Back to Menu", callback_data="menu_back")],
    ])
    await _safe_edit(query, text, markup)
