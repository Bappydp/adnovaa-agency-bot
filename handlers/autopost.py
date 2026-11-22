"""Scheduled auto-post: one admin-set post, sent to every
channel/group where the bot is an admin — on a different schedule
per chat type:

- groups: every 2 hours (12 posts/day)
- channels: every 6 hours (4 posts/day)

Each type has its own JobQueue job (group_autopost /
channel_autopost, first run one interval after startup), but they
share one saved post, one enabled flag (/autopost on/off pauses
or resumes BOTH), and the same send logic.

The admin sets the post himself (/setpost — text, or a photo with
a caption, exactly like /setwelcome) and it goes out with the
3 fixed buttons (Chat with Owner / Website / Our Reviews —
keyboards.welcome_keyboard(), shared with the group welcome,
never duplicated here).

Targets are saved with /addposttarget (the bot must be an ADMIN
of the chat — a plain member can't post to a channel) or
auto-added the moment the bot is PROMOTED to admin somewhere
(see handlers/watch.py). Chats where the bot was ALREADY an admin
before this feature was deployed don't auto-register — the admin
adds those once with /addposttarget.

All commands are admin-only and DM-only. /setpost is a
ConversationHandler: its callbacks raise ApplicationHandlerStop
so the generic DM-text handler (FAQ matching) and the global
/cancel handler never also fire on the admin's input — the
ConversationHandler must therefore be registered BEFORE those
handlers in bot.py.

Same ephemeral-DB caveat as everything else in this bot: the
scheduled post and the target list are wiped on every Render
redeploy, so the admin re-sets the post and re-adds the targets
after a deploy.
"""

import asyncio
import html
import logging
import re

from telegram import Update
from telegram.error import (
    BadRequest,
    Forbidden,
    RetryAfter,
    TelegramError,
)
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
    ALERT_AUTOPOST_FAILED,
)
from handlers.common import admin_only, is_admin, notify_admins

logger = logging.getLogger(__name__)

# Conversation state: waiting for the admin to send the new post.
WAITING_POST = 0

# Max characters for the post text / photo caption (same as /setwelcome).
POST_MAX_LENGTH = 1000

# Max channels/groups the scheduled post goes to.
MAX_POST_TARGETS = 20

# Posting intervals (seconds) by chat type — groups every 2 hours
# (12 posts/day), channels every 6 hours (4 posts/day). Each job's
# first run is one interval after startup (see bot.py).
GROUP_POST_INTERVAL = 7200
CHANNEL_POST_INTERVAL = 21600

# Chat types each job sends to (Telegram reports groups as "group"
# or "supergroup"; channels as "channel").
_GROUP_TYPES = ("group", "supergroup")
_CHANNEL_TYPES = ("channel",)

# Pause between sends — keeps a burst of posts well under
# Telegram's per-minute limits (20 targets ≈ 10 seconds per run).
_POST_DELAY = 0.5

# Chat types that can be auto-post targets (channels and groups).
_TARGET_TYPES = ("channel", "group", "supergroup")

_DM_ONLY = "Please use this command in a private chat with me."

_INVITE_LINK_MSG = (
    "That is a private invite link, and Telegram doesn't let a bot "
    "open it. For a private channel or group, send its numeric ID "
    "instead — it starts with -100 (from a message link like "
    "t.me/c/1234567890/… the ID is -1001234567890)."
)

_ADMIN_STATUSES = ("administrator", "creator")


def _is_private(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == "private"


def post_text_error(text: str) -> str | None:
    """Validation error for a post text, or None if it's fine."""
    if len(text) > POST_MAX_LENGTH:
        return (
            f"That's too long — {len(text)} characters. "
            f"Please keep the post under {POST_MAX_LENGTH} "
            "characters and send it again."
        )
    return None


def _parse_target(raw: str) -> tuple[str | int | None, str | None]:
    """Parse a channel/group identifier into something bot.get_chat
    accepts.

    Accepts a @username, a plain username, a t.me link, or a
    numeric chat ID. Returns (target, None) on success, or
    (None, error message) when the identifier can't be used.
    """
    raw = raw.strip()
    if not raw:
        return None, "Send a channel/group link, @username or numeric ID."
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
    # Numeric chat ID (channels/groups are negative, e.g. -1001234567890).
    try:
        return int(raw), None
    except ValueError:
        pass
    # Plain username (must start with a letter, 5-32 chars).
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", raw):
        return "@" + raw, None
    return None, ("I don't recognise that — send a channel/group link, "
                  "@username or numeric ID.")


def _target_label(target: dict) -> str:
    """Safe one-line label for a saved target (HTML-escaped)."""
    title = html.escape(target.get("title") or "Untitled chat")
    username = target.get("username")
    if username:
        return f"{title} (@{html.escape(username)})"
    return title


def _type_label(chat_type: str | None) -> str:
    return {"channel": "channel", "group": "group",
            "supergroup": "group"}.get(chat_type or "", "chat")


async def _bot_is_admin(bot, chat_id: int) -> bool:
    """Is the bot itself an ADMINISTRATOR of this chat?

    Fails CLOSED (False) on API errors: if we can't confirm the
    bot is an admin there, the admin is told to make it one and
    retry — a chat we can't post to is useless as a target anyway.
    """
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        return member.status in _ADMIN_STATUSES
    except TelegramError as exc:
        logger.info("Bot admin check failed for %s: %s", chat_id, exc)
        return False


async def _send_rendered(bot, chat_id: int, text: str,
                         reply_markup=None) -> None:
    """Send text as-is (admin HTML like <b> works); if Telegram
    rejects it as bad HTML, retry with the text escaped."""
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except BadRequest:
        await bot.send_message(chat_id, html.escape(text),
                               reply_markup=reply_markup)


async def try_send_post_photo(bot, chat_id: int, photo_file_id: str,
                              caption: str,
                              reply_markup=None) -> bool:
    """Send the post photo. Retries once with an escaped caption
    if Telegram rejects the HTML. Returns False if the photo itself
    can't be sent (e.g. a stale file_id). RetryAfter is NOT
    swallowed — the caller retries the whole send after the wait.
    """
    for cap in (caption, html.escape(caption)):
        try:
            await bot.send_photo(chat_id, photo_file_id, caption=cap,
                                 reply_markup=reply_markup)
            return True
        except BadRequest:
            continue
        except RetryAfter:
            raise
        except Exception as exc:
            logger.warning("Sending auto-post photo failed: %s", exc)
            return False
    return False


async def send_post_preview(context: ContextTypes.DEFAULT_TYPE,
                            chat_id: int) -> bool:
    """Send the saved post exactly as the targets see it —
    including the 3 fixed buttons. Returns False if no post is set.
    If the saved photo can't be sent (stale file_id?), the text
    version is shown instead and the admin is told to re-set it.
    """
    markup = keyboards.welcome_keyboard()
    post = db.get_autopost()
    if not post:
        return False
    text = post.get("text") or ""
    if post.get("photo_file_id"):
        if await try_send_post_photo(context.bot, chat_id,
                                     post["photo_file_id"], text,
                                     reply_markup=markup):
            return True
        await _send_rendered(context.bot, chat_id, text,
                             reply_markup=markup)
        await context.bot.send_message(
            chat_id,
            "⚠️ The saved photo could not be sent — it may be outdated. "
            "Use /setpost to set the post again with a new photo.")
        return True
    await _send_rendered(context.bot, chat_id, text, reply_markup=markup)
    return True


# ------------------------------------------------------------------
# /setpost conversation
# ------------------------------------------------------------------

@admin_only
async def setpost_entry(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """/setpost — start setting the scheduled post (DM only)."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return ConversationHandler.END
    current = ""
    if db.get_autopost():
        current = (
            "\nYou already have a scheduled post — sending a new "
            "one will replace it."
        )
    targets = db.count_post_targets()
    await update.message.reply_text(
        "📢 <b>Set the scheduled auto-post</b>\n\n"
        "Send the post that will go out to all "
        f"saved targets ({targets}/{MAX_POST_TARGETS} saved) — "
        "<b>every 2 hours</b> to groups (12/day) and <b>every 6 "
        "hours</b> to channels (4/day).\n\n"
        "• Send <b>plain text</b> for a text-only post, or\n"
        "• Send a <b>photo with a caption</b> for an image post.\n\n"
        "The post always carries the 3 buttons: Chat with Owner, "
        "Website and Our Reviews.\n"
        f"Max {POST_MAX_LENGTH} characters.{current}\n\n"
        "Send /cancel to abort."
    )
    return WAITING_POST


async def receive_post(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the admin's text or photo+caption as the scheduled post."""
    msg = update.message
    if not is_admin(update.effective_user.id):
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
                "A photo post needs a <b>caption</b> — that's the "
                "message shown with the image. Please send the photo "
                "again with a caption, or send plain text instead.")
            raise ApplicationHandlerStop(WAITING_POST)
    else:
        text = (msg.text or "").strip()

    error = post_text_error(text)
    if error:
        await msg.reply_text(error)
        raise ApplicationHandlerStop(WAITING_POST)

    db.set_autopost(text, photo_file_id)

    # Preview exactly what the targets will see, then confirm.
    await send_post_preview(context, msg.chat_id)
    targets = db.count_post_targets()
    if targets:
        targets_note = (
            f"It will go out to all {targets} saved "
            f"target{'s' if targets != 1 else ''} — groups every "
            "2 hours, channels every 6 hours."
        )
    else:
        targets_note = (
            "No targets are saved yet — add channels/groups with "
            "/addposttarget (make me an admin there first) and the "
            "post will start going out (groups every 2 hours, "
            "channels every 6 hours)."
        )
    await msg.reply_text(
        "✅ <b>Scheduled post saved.</b>\n\n" + targets_note)
    raise ApplicationHandlerStop(ConversationHandler.END)


async def reject_post_input(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> int:
    """Anything that isn't text or a photo — explain and stay."""
    await update.message.reply_text(
        "Please send <b>text</b> or a <b>photo with a caption</b> — "
        "stickers, videos and other message types can't be used as "
        "the scheduled post. (Or /cancel to abort.)")
    raise ApplicationHandlerStop(WAITING_POST)


async def cancel_post_setup(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> int:
    """/cancel during /setpost — abort without saving."""
    await update.message.reply_text(
        "Post setup cancelled — nothing was changed.")
    raise ApplicationHandlerStop(ConversationHandler.END)


def setpost_conversation() -> ConversationHandler:
    """The /setpost conversation: one text or photo message."""
    return ConversationHandler(
        entry_points=[CommandHandler("setpost", setpost_entry)],
        states={
            WAITING_POST: [
                MessageHandler(
                    filters.PHOTO | (filters.TEXT & ~filters.COMMAND),
                    receive_post),
                MessageHandler(filters.ALL & ~filters.COMMAND,
                               reject_post_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_post_setup)],
    )


# ------------------------------------------------------------------
# /post, /resetpost, /autopost
# ------------------------------------------------------------------

@admin_only
async def post_command(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """/post — preview the currently scheduled post (DM only)."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    if not db.get_autopost():
        await update.message.reply_text(
            "No scheduled post is set yet — use /setpost to set one.")
        return
    await update.message.reply_text(
        "📢 <b>Current scheduled post</b> — this goes out to all "
        "saved targets (groups every 2 hours, channels every "
        "6 hours):")
    await send_post_preview(context, update.effective_chat.id)


@admin_only
async def resetpost_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resetpost — clear the scheduled post; auto-posting stops
    until a new post is set."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    if db.reset_autopost():
        await update.message.reply_text(
            "✅ Scheduled post cleared — the auto-post has "
            "stopped. Set a new post with /setpost to start it again.")
    else:
        await update.message.reply_text(
            "No scheduled post was set — nothing to clear.")


def _status_text() -> str:
    """The /autopost status block: on/off, both schedules, post,
    targets."""
    post = db.get_autopost()
    targets = db.list_post_targets()
    if not post:
        status = ("No post is set — use /setpost to set one, then "
                  "posting starts automatically.")
    elif post.get("enabled"):
        status = "✅ <b>ON</b>"
    else:
        status = ("⏸️ <b>PAUSED</b> — use <code>/autopost on</code> "
                  "to resume.")
    if post:
        length = len(post.get("text") or "")
        photo_note = ", with photo" if post.get("photo_file_id") else ""
        post_line = f"Post: set ({length} characters{photo_note})"
    else:
        post_line = "Post: not set"
    lines = ["📢 <b>Scheduled auto-post</b>\n",
             f"Status: {status}\n",
             "Schedule: groups every 2 hours (12/day), channels "
             "every 6 hours (4/day)\n",
             post_line,
             f"Targets ({len(targets)}/{MAX_POST_TARGETS}):"]
    if targets:
        for target in targets:
            lines.append(
                f"• {_target_label(target)} — "
                f"{_type_label(target.get('type'))} "
                f"(<code>{target['chat_id']}</code>)")
    else:
        lines.append("No targets saved yet — add channels/groups with "
                     "/addposttarget (make me an admin there first).")
    return "\n".join(lines)


@admin_only
async def autopost_command(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/autopost — status; /autopost on resumes, /autopost off
    pauses the scheduled post (both jobs — groups and channels)
    (DM only)."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    args = [a.lower() for a in (context.args or [])]
    if not args:
        await update.message.reply_text(_status_text())
        return
    if args[0] == "on":
        if db.set_autopost_enabled(True):
            targets = db.count_post_targets()
            await update.message.reply_text(
                "✅ <b>Auto-post resumed.</b>\n\n"
                f"The post will go out to all {targets} "
                f"saved target{'s' if targets != 1 else ''} — "
                "groups every 2 hours, channels every 6 hours.")
        else:
            await update.message.reply_text(
                "No post is set yet — use /setpost to set one first.")
        return
    if args[0] == "off":
        if db.set_autopost_enabled(False):
            await update.message.reply_text(
                "⏸️ <b>Auto-post paused.</b>\n\n"
                "The post stays saved — use <code>/autopost on</code> "
                "to resume it.")
        else:
            await update.message.reply_text(
                "No post is set yet — use /setpost to set one first.")
        return
    await update.message.reply_text(
        "Usage: <code>/autopost</code> (status), "
        "<code>/autopost on</code> (resume) or "
        "<code>/autopost off</code> (pause).")


# ------------------------------------------------------------------
# Targets: /addposttarget, /delposttarget, /posttargets
# ------------------------------------------------------------------

@admin_only
async def addposttarget_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addposttarget <channel/group link | @username | numeric id>
    — save a channel or group so the scheduled post goes there.
    The bot must be an ADMIN of the chat."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.message.reply_text(
            "Usage: <code>/addposttarget &lt;channel/group link or "
            "@username or ID&gt;</code>\n\n"
            "Example: <code>/addposttarget @mygroup</code>\n\n"
            "Make me an <b>admin</b> of the channel/group FIRST — "
            "I can only post where I'm an admin.")
        return
    target, error = _parse_target(raw)
    if error:
        await update.message.reply_text(error)
        return
    try:
        chat = await context.bot.get_chat(target)
    except TelegramError:
        await update.message.reply_text(
            "Couldn't find that channel or group — check the link, "
            "username or ID and try again.")
        return
    if chat.type not in _TARGET_TYPES:
        await update.message.reply_text(
            "That is not a channel or group — auto-post only works "
            "with channels and groups.")
        return
    if db.get_post_target(chat.id) is not None:
        await update.message.reply_text(
            f"That chat is already on the auto-post list: "
            f"<b>{html.escape(chat.title or '')}</b> "
            f"(<code>{chat.id}</code>).")
        return
    if db.count_post_targets() >= MAX_POST_TARGETS:
        await update.message.reply_text(
            f"⚠️ The auto-post list is full ({MAX_POST_TARGETS} "
            "targets). Remove one with /delposttarget before adding "
            "another.")
        return
    if not await _bot_is_admin(context.bot, chat.id):
        await update.message.reply_text(
            f"I'm not an admin of <b>{html.escape(chat.title or '')}</b> "
            "yet — make me an admin there first, then run this "
            "command again.")
        return
    db.add_post_target(chat.id, chat.title,
                       getattr(chat, "username", None), chat.type,
                       update.effective_user.id)
    count = db.count_post_targets()
    if chat.type in _CHANNEL_TYPES:
        schedule = "The post will go there every 6 hours (4/day)."
    else:
        schedule = "The post will go there every 2 hours (12/day)."
    await update.message.reply_text(
        f"✅ <b>{html.escape(chat.title or '')}</b> added to "
        f"auto-post ({count}/{MAX_POST_TARGETS} targets).\n\n"
        + schedule)


@admin_only
async def delposttarget_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delposttarget <channel/group link | @username | numeric id>
    — stop sending the scheduled post to a channel or group."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.message.reply_text(
            "Usage: <code>/delposttarget &lt;channel/group link or "
            "@username or ID&gt;</code>")
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
                "Couldn't find that channel or group — if it was "
                "deleted, remove it with its numeric ID instead.")
            return
        chat_id = chat.id
    if db.delete_post_target(chat_id):
        await update.message.reply_text(
            f"Chat <code>{chat_id}</code> removed from auto-post.")
    else:
        await update.message.reply_text(
            f"Chat <code>{chat_id}</code> is not on the auto-post list.")


@admin_only
async def posttargets_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/posttargets — list all channels/groups the scheduled post
    goes to."""
    if not _is_private(update):
        await update.message.reply_text(_DM_ONLY)
        return
    targets = db.list_post_targets()
    if not targets:
        await update.message.reply_text(
            "No targets saved yet. Add one with "
            "<code>/addposttarget &lt;channel/group link or @username "
            "or ID&gt;</code> (make me an admin there first).")
        return
    lines = [f"📢 <b>Auto-post targets "
             f"({len(targets)}/{MAX_POST_TARGETS})</b>\n"]
    for target in targets:
        lines.append(
            f"• {_target_label(target)} — "
            f"{_type_label(target.get('type'))} "
            f"(<code>{target['chat_id']}</code>)")
    await update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------
# Scheduled jobs — one per chat type, same send logic
# ------------------------------------------------------------------

async def _send_post_once(bot, chat_id: int, post: dict,
                          markup) -> str:
    """Send the saved post to one target, once. Returns "sent", or
    "text_fallback" when the photo couldn't be sent and the text
    went out instead. Raises TelegramError on failure."""
    text = post.get("text") or ""
    photo = post.get("photo_file_id")
    if photo:
        if await try_send_post_photo(bot, chat_id, photo, text,
                                     reply_markup=markup):
            return "sent"
        if text:
            await _send_rendered(bot, chat_id, text,
                                 reply_markup=markup)
            return "text_fallback"
        raise TelegramError(
            "photo could not be sent and there is no text")
    await _send_rendered(bot, chat_id, text, reply_markup=markup)
    return "sent"


async def _send_post_with_retry(bot, chat_id: int, post: dict,
                                markup) -> str:
    """Send the post, retrying ONCE after a RetryAfter wait.

    Any other error (or a second RetryAfter) is raised to the
    caller, which records it as a per-target failure.
    """
    try:
        return await _send_post_once(bot, chat_id, post, markup)
    except RetryAfter as exc:
        logger.warning("Flood control for %s — waiting %ss and "
                       "retrying once", chat_id, exc.retry_after)
        await asyncio.sleep(exc.retry_after)
        return await _send_post_once(bot, chat_id, post, markup)


async def _run_post_job(context: ContextTypes.DEFAULT_TYPE,
                        target_types: tuple[str, ...],
                        label: str) -> None:
    """Send the saved post to all saved targets of the given chat
    types (groups or channels).

    Shared by both jobs: does nothing when no post is set, when
    posting is paused (/autopost off — one flag pauses BOTH jobs),
    or when no targets of this type are saved. A failure in one
    target never stops the others — all failures are collected and
    reported to the admins in ONE summary alert per job run.
    """
    post = db.get_autopost()
    if not post:
        logger.info("%s: no post set.", label)
        return
    if not post.get("enabled"):
        logger.info("%s: paused (/autopost off).", label)
        return
    targets = [t for t in db.list_post_targets()
               if t.get("type") in target_types]
    if not targets:
        logger.info("%s: no targets of this type saved.", label)
        return
    markup = keyboards.welcome_keyboard()
    logger.info("%s: sending to %d target(s)", label, len(targets))
    failures: list[str] = []
    removed_any = False
    for i, target in enumerate(targets):
        if i:
            await asyncio.sleep(_POST_DELAY)
        label_target = _target_label(target)
        try:
            result = await _send_post_with_retry(
                context.bot, target["chat_id"], post, markup)
            if result == "text_fallback":
                failures.append(
                    f"• {label_target} — photo could not be sent, "
                    "text was sent instead (re-set the post with "
                    "/setpost)")
        except Forbidden as exc:
            # The bot was kicked/removed or lost posting rights —
            # the target is dead for auto-post, so drop it from
            # the list instead of failing on every future run.
            logger.warning("%s to %s failed (%s) — "
                           "removing it from the list",
                           label, target["chat_id"], exc)
            db.delete_post_target(target["chat_id"])
            removed_any = True
            failures.append(
                f"• {label_target} — bot was removed or can't post "
                "here (removed from the list)")
        except TelegramError as exc:
            logger.warning("%s to %s failed: %s",
                           label, target["chat_id"], exc)
            reason = str(exc)[:100] or exc.__class__.__name__
            failures.append(
                f"• {label_target} — {html.escape(reason)}")
    if failures:
        removed_note = (
            "\n\nTargets marked 'removed from the list' were dropped "
            "— add them again with /addposttarget after making the "
            "bot an admin there."
            if removed_any else ""
        )
        await notify_admins(
            context,
            ALERT_AUTOPOST_FAILED.format(
                failures="\n".join(failures),
                removed_note=removed_note))


async def group_post(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback, every 2 hours: send the saved post to
    all saved GROUP targets (12 posts/day)."""
    await _run_post_job(context, _GROUP_TYPES, "Group auto-post")


async def channel_post(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback, every 6 hours: send the saved post to
    all saved CHANNEL targets (4 posts/day)."""
    await _run_post_job(context, _CHANNEL_TYPES, "Channel auto-post")
