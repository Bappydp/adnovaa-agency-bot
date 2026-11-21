"""Admin welcome editor: /setwelcome, /welcome, /resetwelcome.

The admin can set the message new members see in the group after
they join the channel and tap "I've Joined" — plain text, or a
photo with a caption. {name} in the text is replaced with the
joiner's name. If nothing custom is set, the default message
(content.GROUP_WELCOME_DEFAULT) is used.

All three commands are admin-only and DM-only. /setwelcome is a
ConversationHandler: its callbacks raise ApplicationHandlerStop so
the generic DM-text handler (FAQ matching) and the global /cancel
handler never also fire on the admin's input — the
ConversationHandler must therefore be registered BEFORE those
handlers in bot.py.
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
from content import GROUP_WELCOME_DEFAULT
from handlers.common import admin_only, is_admin

logger = logging.getLogger(__name__)

# Conversation state: waiting for the admin to send the new welcome.
WAITING_WELCOME = 0

# Max characters for the welcome text / photo caption.
WELCOME_MAX_LENGTH = 1000

_DM_ONLY = "Please use this command in a private chat with me."


def render_welcome_text(template: str, name: str) -> str:
    """Replace {name} with the joiner's (HTML-escaped) display name."""
    return template.replace("{name}", html.escape(name))


def welcome_text_error(text: str) -> str | None:
    """Validation error for a welcome text, or None if it's fine."""
    if len(text) > WELCOME_MAX_LENGTH:
        return (
            f"That's too long — {len(text)} characters. "
            f"Please keep the welcome under {WELCOME_MAX_LENGTH} "
            "characters and send it again."
        )
    return None


def _is_private(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == "private"


async def _send_rendered(bot, chat_id: int, text: str) -> None:
    """Send text as-is (admin HTML like <b> works); if Telegram
    rejects it as bad HTML, retry with the text escaped."""
    try:
        await bot.send_message(chat_id, text)
    except BadRequest:
        await bot.send_message(chat_id, html.escape(text))


async def try_send_welcome_photo(bot, chat_id: int, photo_file_id: str,
                                 caption: str) -> bool:
    """Send the welcome photo. Retries once with an escaped caption
    if Telegram rejects the HTML. Returns False if the photo itself
    can't be sent (e.g. a stale file_id)."""
    for cap in (caption, html.escape(caption)):
        try:
            await bot.send_photo(chat_id, photo_file_id, caption=cap)
            return True
        except BadRequest:
            continue
        except Exception as exc:
            logger.warning("Sending welcome photo failed: %s", exc)
            return False
    return False


async def send_welcome_preview(context: ContextTypes.DEFAULT_TYPE,
                               chat_id: int, sample_name: str) -> None:
    """Send the current welcome exactly as a joiner sees it.
    The group welcome carries no buttons, so none are attached."""
    welcome = db.get_welcome()
    if welcome and welcome.get("photo_file_id"):
        caption = render_welcome_text(welcome.get("text") or "",
                                      sample_name)
        if await try_send_welcome_photo(context.bot, chat_id,
                                        welcome["photo_file_id"], caption):
            return
        # The saved photo can't be sent (stale file_id?) — show the
        # text version and tell the admin to re-set the image.
        await _send_rendered(context.bot, chat_id, caption)
        await context.bot.send_message(
            chat_id,
            "⚠️ The saved photo could not be sent — it may be outdated. "
            "Use /setwelcome to set the welcome again with a new photo.")
        return
    if welcome and welcome.get("text"):
        await _send_rendered(
            context.bot, chat_id,
            render_welcome_text(welcome["text"], sample_name))
        return
    await context.bot.send_message(
        chat_id,
        GROUP_WELCOME_DEFAULT.format(name=html.escape(sample_name)))


# ------------------------------------------------------------------
# /setwelcome conversation
# ------------------------------------------------------------------

@admin_only
async def setwelcome_entry(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> int:
    """/setwelcome — start setting a custom group welcome (DM only)."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return ConversationHandler.END
    current = ""
    if db.get_welcome():
        current = (
            "\nYou already have a custom welcome set — sending a new "
            "one will replace it."
        )
    await update.message.reply_text(
        "👋 <b>Set the group welcome message</b>\n\n"
        "Send the message new members will see in the group after "
        "they join the channel and tap <b>✅ I've Joined</b>.\n\n"
        "• Send <b>plain text</b> for a text-only welcome, or\n"
        "• Send a <b>photo with a caption</b> for an image welcome.\n\n"
        "Use <code>{name}</code> where the new member's name should "
        "appear.\n"
        f"Max {WELCOME_MAX_LENGTH} characters.{current}\n\n"
        "Send /cancel to abort."
    )
    return WAITING_WELCOME


async def receive_welcome(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the admin's text or photo+caption as the new welcome."""
    msg = update.message
    user = update.effective_user
    if not is_admin(user.id):
        # Unreachable in practice (only admins can enter the
        # conversation), but end it cleanly if it ever happens.
        raise ApplicationHandlerStop(ConversationHandler.END)

    text: str | None = None
    photo_file_id: str | None = None
    if msg.photo:
        photo_file_id = msg.photo[-1].file_id  # largest size
        text = (msg.caption or "").strip()
        if not text:
            await msg.reply_text(
                "A photo welcome needs a <b>caption</b> — that's the "
                "message shown with the image. Please send the photo "
                "again with a caption, or send plain text instead.")
            raise ApplicationHandlerStop(WAITING_WELCOME)
    else:
        text = (msg.text or "").strip()

    error = welcome_text_error(text)
    if error:
        await msg.reply_text(error)
        raise ApplicationHandlerStop(WAITING_WELCOME)

    db.set_welcome(text, photo_file_id)

    # Preview exactly what joiners will see, then confirm.
    await send_welcome_preview(context, msg.chat_id,
                               user.first_name or "there")
    await msg.reply_text(
        "✅ <b>Welcome message saved.</b>\n\n"
        "New members will see this after joining the channel and "
        "tapping <b>✅ I've Joined</b> in the group.")
    raise ApplicationHandlerStop(ConversationHandler.END)


async def reject_welcome_input(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> int:
    """Anything that isn't text or a photo — explain and stay."""
    await update.message.reply_text(
        "Please send <b>text</b> or a <b>photo with a caption</b> — "
        "stickers, videos and other message types can't be used as "
        "the welcome message. (Or /cancel to abort.)")
    raise ApplicationHandlerStop(WAITING_WELCOME)


async def cancel_welcome_setup(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> int:
    """/cancel during /setwelcome — abort without saving."""
    await update.message.reply_text(
        "Welcome setup cancelled — nothing was changed.")
    raise ApplicationHandlerStop(ConversationHandler.END)


def setwelcome_conversation() -> ConversationHandler:
    """The /setwelcome conversation: one text or photo message."""
    return ConversationHandler(
        entry_points=[CommandHandler("setwelcome", setwelcome_entry)],
        states={
            WAITING_WELCOME: [
                MessageHandler(
                    filters.PHOTO | (filters.TEXT & ~filters.COMMAND),
                    receive_welcome),
                MessageHandler(filters.ALL & ~filters.COMMAND,
                               reject_welcome_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_welcome_setup)],
    )


# ------------------------------------------------------------------
# /welcome and /resetwelcome
# ------------------------------------------------------------------

@admin_only
async def welcome_command(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """/welcome — preview the current group welcome (DM only)."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    if db.get_welcome():
        await update.message.reply_text(
            "👋 <b>Current custom welcome</b> — this is what new "
            "members see:")
    else:
        await update.message.reply_text(
            "No custom welcome is set — new members see the "
            "<b>default</b> message:")
    await send_welcome_preview(
        context, update.effective_chat.id,
        update.effective_user.first_name or "there")


@admin_only
async def resetwelcome_command(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resetwelcome — delete the custom welcome, restore default."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    if db.reset_welcome():
        await update.message.reply_text(
            "✅ Custom welcome removed — new members will see the "
            "default welcome message again:")
        await send_welcome_preview(
            context, update.effective_chat.id,
            update.effective_user.first_name or "there")
    else:
        await update.message.reply_text(
            "No custom welcome was set — the default welcome is "
            "already in use.")
