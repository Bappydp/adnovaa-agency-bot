"""Admin content editors: /setservices, /setpricing, /setcontact,
/setpayment (and /resetservices, /resetpricing, /resetcontact,
/resetpayment).

The admin can set the details shown behind the main-menu buttons —
the same way /setwelcome sets the group welcome: plain text, or a
photo with a caption. When a custom text is set it FULLY replaces
the default (for Pricing that means the generated package list);
when reset, the default from content.py shows again.

All commands are admin-only and DM-only. The four /set... commands
share ONE ConversationHandler — the section being edited lives in
context.user_data — so only one edit can be in flight at a time.
Its callbacks raise ApplicationHandlerStop so the generic DM-text
handler (FAQ matching) and the global /cancel handler never also
fire on the admin's input — the ConversationHandler must therefore
be registered BEFORE those handlers in bot.py.
"""

import html
import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database as db
import keyboards
from content import (
    CONTACT,
    PAYMENT_INFO,
    render_packages,
    render_services,
)
from handlers.common import admin_only, is_admin

logger = logging.getLogger(__name__)

# Conversation state: waiting for the admin to send the new content.
WAITING_CONTENT = 0

# Max characters for a section text / photo caption. Longer than
# the welcome limit (1000) — services and pricing can be long.
CONTENT_MAX_LENGTH = 3000

_DM_ONLY = "Please use this command in a private chat with me."

# Section -> label shown to the admin.
SECTION_LABEL = {
    "services": "Services",
    "pricing": "Pricing",
    "contact": "Contact",
    "payment": "Payment Info",
}

# Section -> what the admin is editing, in the entry message.
SECTION_BLURB = {
    "services": "the text shown when someone taps 🚀 Services in the menu",
    "pricing": ("the text shown when someone taps 💰 Pricing in the menu — "
                "it fully replaces the package list"),
    "contact": "the text shown when someone taps 💬 Contact in the menu",
    "payment": ("the text shown when someone taps 💳 Payment Info in the "
                "menu"),
}


def default_section_text(section: str) -> str:
    """The default (content.py) text for a section."""
    if section == "services":
        return render_services()
    if section == "pricing":
        return render_packages()
    if section == "contact":
        return CONTACT
    return PAYMENT_INFO


def content_text_error(text: str) -> str | None:
    """Validation error for a section text, or None if it's fine."""
    if len(text) > CONTENT_MAX_LENGTH:
        return (
            f"That's too long — {len(text)} characters. "
            f"Please keep it under {CONTENT_MAX_LENGTH} "
            "characters and send it again."
        )
    return None


def _is_private(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == "private"


async def _send_rendered(bot, chat_id: int, text: str,
                         reply_markup=None) -> None:
    """Send text as-is (admin HTML like <b> works); if Telegram
    rejects it as bad HTML, retry with the text escaped."""
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except BadRequest:
        await bot.send_message(chat_id, html.escape(text),
                               reply_markup=reply_markup)


async def try_send_section_photo(bot, chat_id: int, photo_file_id: str,
                                 caption: str,
                                 reply_markup=None) -> bool:
    """Send a section photo. Retries once with an escaped caption
    if Telegram rejects the HTML. Returns False if the photo itself
    can't be sent (e.g. a stale file_id)."""
    for cap in (caption, html.escape(caption)):
        try:
            await bot.send_photo(chat_id, photo_file_id, caption=cap,
                                 reply_markup=reply_markup)
            return True
        except BadRequest:
            continue
        except Exception as exc:
            logger.warning("Sending section photo failed: %s", exc)
            return False
    return False


async def send_section_preview(context: ContextTypes.DEFAULT_TYPE,
                               chat_id: int, section: str) -> None:
    """Send a section exactly as a user sees it when tapping the
    menu button — custom text/photo if set, else the default —
    with the Back button attached, like the real menu page."""
    markup = keyboards.back_menu()
    custom = db.get_content_section(section)
    if custom and custom.get("photo_file_id"):
        caption = custom.get("text") or ""
        if await try_send_section_photo(context.bot, chat_id,
                                        custom["photo_file_id"], caption,
                                        reply_markup=markup):
            return
        # The saved photo can't be sent (stale file_id?) — show the
        # text version and tell the admin to re-set the image.
        await _send_rendered(context.bot, chat_id, caption,
                             reply_markup=markup)
        await context.bot.send_message(
            chat_id,
            "⚠️ The saved photo could not be sent — it may be outdated. "
            f"Use /set{section} to set it again with a new photo.")
        return
    if custom and custom.get("text"):
        await _send_rendered(context.bot, chat_id, custom["text"],
                             reply_markup=markup)
        return
    await _send_rendered(context.bot, chat_id,
                         default_section_text(section),
                         reply_markup=markup)


# ------------------------------------------------------------------
# /set... conversation (one ConversationHandler, four entry points)
# ------------------------------------------------------------------

def _make_entry(section: str):
    """Build the /set<section> entry callback for one section."""
    label = SECTION_LABEL[section]

    @admin_only
    async def entry(update: Update,
                    context: ContextTypes.DEFAULT_TYPE) -> int:
        if not _is_private(update):
            await update.message.reply_text(_DM_ONLY)
            return ConversationHandler.END
        current = ""
        if db.get_content_section(section):
            current = (
                f"\nYou already have a custom {label} text set — "
                "sending a new one will replace it."
            )
        context.user_data["editing_section"] = section
        await update.message.reply_text(
            f"✏️ <b>Set the {label} details</b>\n\n"
            f"Send {SECTION_BLURB[section]}.\n\n"
            "• Send <b>plain text</b> for a text-only page, or\n"
            "• Send a <b>photo with a caption</b> for an image page.\n\n"
            f"Max {CONTENT_MAX_LENGTH} characters.{current}\n\n"
            "Send /cancel to abort."
        )
        return WAITING_CONTENT

    return entry


async def receive_content(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the admin's text or photo+caption as the new section
    content, then preview it exactly as users will see it."""
    msg = update.message
    user = update.effective_user
    section = context.user_data.get("editing_section")
    if not is_admin(user.id) or section not in SECTION_LABEL:
        # Unreachable in practice (only admins can enter the
        # conversation, and the entry always sets the section),
        # but end it cleanly if it ever happens.
        context.user_data.pop("editing_section", None)
        raise ApplicationHandlerStop(ConversationHandler.END)
    label = SECTION_LABEL[section]

    text: str | None = None
    photo_file_id: str | None = None
    if msg.photo:
        photo_file_id = msg.photo[-1].file_id  # largest size
        text = (msg.caption or "").strip()
        if not text:
            await msg.reply_text(
                "A photo page needs a <b>caption</b> — that's the "
                "message shown with the image. Please send the photo "
                "again with a caption, or send plain text instead.")
            raise ApplicationHandlerStop(WAITING_CONTENT)
    else:
        text = (msg.text or "").strip()

    error = content_text_error(text)
    if error:
        await msg.reply_text(error)
        raise ApplicationHandlerStop(WAITING_CONTENT)

    db.set_content_section(section, text, photo_file_id)
    context.user_data.pop("editing_section", None)

    # Preview exactly what users will see, then confirm.
    await send_section_preview(context, msg.chat_id, section)
    await msg.reply_text(
        f"✅ <b>{label} saved.</b>\n\n"
        f"Tap <b>{label}</b> in the menu to see it.")
    raise ApplicationHandlerStop(ConversationHandler.END)


async def reject_content_input(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> int:
    """Anything that isn't text or a photo — explain and stay."""
    await update.message.reply_text(
        "Please send <b>text</b> or a <b>photo with a caption</b> — "
        "stickers, videos and other message types can't be used as "
        "menu content. (Or /cancel to abort.)")
    raise ApplicationHandlerStop(WAITING_CONTENT)


async def cancel_content_setup(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> int:
    """/cancel during a /set... conversation — abort without saving."""
    context.user_data.pop("editing_section", None)
    await update.message.reply_text(
        "Content setup cancelled — nothing was changed.")
    raise ApplicationHandlerStop(ConversationHandler.END)


def setcontent_conversation() -> ConversationHandler:
    """The /set... conversation: one text or photo message.

    Four entry points, one shared state — the section being edited
    is kept in context.user_data, so starting a second /set...
    while one is open simply switches the section being edited.
    """
    return ConversationHandler(
        entry_points=[CommandHandler(f"set{s}", _make_entry(s))
                      for s in ("services", "pricing", "contact",
                                "payment")],
        states={
            WAITING_CONTENT: [
                MessageHandler(
                    filters.PHOTO | (filters.TEXT & ~filters.COMMAND),
                    receive_content),
                MessageHandler(filters.ALL & ~filters.COMMAND,
                               reject_content_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_content_setup)],
    )


# ------------------------------------------------------------------
# /reset...
# ------------------------------------------------------------------

def _make_reset(section: str):
    """Build the /reset<section> command for one section."""
    label = SECTION_LABEL[section]

    @admin_only
    async def reset_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
        """/reset<section> — delete the custom text, restore default."""
        if not _is_private(update):
            await update.message.reply_text(_DM_ONLY)
            return
        if db.reset_content_section(section):
            await update.message.reply_text(
                f"✅ Custom {label} removed — the default {label} "
                "shows again:")
            await send_section_preview(
                context, update.effective_chat.id, section)
        else:
            await update.message.reply_text(
                f"No custom {label} was set — the default {label} is "
                "already in use.")

    return reset_command


resetservices_command = _make_reset("services")
resetpricing_command = _make_reset("pricing")
resetcontact_command = _make_reset("contact")
resetpayment_command = _make_reset("payment")
