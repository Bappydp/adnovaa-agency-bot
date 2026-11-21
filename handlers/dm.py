"""DM handling: /faq, /redeem, coupon-code input and free-text
FAQ keyword matching in private chats."""

import database as db
import keyboards
from content import FAQ, FALLBACK_TEXT
from telegram import Update
from telegram.ext import ContextTypes


async def faq_command(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    db.record_command(update.effective_user.id, "/faq")
    await update.message.reply_text(
        "❓ <b>Frequently Asked Questions</b>\n\nTap a topic 👇",
        reply_markup=keyboards.faq_keyboard())


async def redeem_command(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.record_command(user.id, "/redeem")
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/redeem CODE</code>\n\n"
            "Example: <code>/redeem WELCOME20</code>")
        return
    ok, msg = db.redeem_coupon(context.args[0], user.id)
    await update.message.reply_text(msg,
                                    reply_markup=keyboards.back_menu())


async def handle_dm_text(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free text in a DM: coupon code input, then FAQ keyword match."""
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return
    db.update_activity(user.id)

    # Coupon code being entered after tapping "Redeem Coupon".
    if context.user_data.pop("awaiting_coupon", False):
        ok, msg = db.redeem_coupon(text, user.id)
        await update.message.reply_text(msg,
                                        reply_markup=keyboards.back_menu())
        return

    # FAQ keyword match.
    low = text.lower()
    for entry in FAQ:
        if any(kw in low for kw in entry["keywords"]):
            await update.message.reply_text(
                entry["answer"],
                reply_markup=keyboards.main_menu())
            return

    await update.message.reply_text(
        FALLBACK_TEXT, reply_markup=keyboards.main_menu())
