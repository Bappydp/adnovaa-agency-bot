"""Agency Telegram Bot — Facebook | Google Ads Agencies.

Features (all 18):
  1. /start welcome + button menu (Services, Pricing, Contact)
  2. Service details + 3 packages (prices are TODO placeholders in content.py)
  3. FAQ auto-reply (/faq + keyword matching in DMs)
  4. /broadcast to all users (admin only)
  5. Force-subscribe: group messages only from channel members
  6. /stats (admin only)
  7. Payment info (wallet is a TODO placeholder in content.py)
  8. Coupon system (/addcoupon, /redeem)
  9. Giveaway / contest with referral entries (/giveaway, /draw)
 10. Group keyword auto-replies (/addkeyword, /delkeyword)
 11. VIP membership (/vip, /unvip, /vipinfo)
 12. Daily lead follow-up (max 2 per lead, auto-stops on block)
 13. Group anti-spam: obvious spam deleted, 3 strikes in 24h = ban
     (/spamstats, /addspamword, /delspamword, /spamwords)
 14. /report — members flag a message to the admins (delete/ban/dismiss)
 15. Admin alerts: mass-leave watch + bot removed/lost-admin alerts
     (/alerts)
 16. Welcome editor: the admin sets the post-join group welcome
     himself, text or photo + caption (/setwelcome, /welcome,
     /resetwelcome)
 17. Menu content editors: the admin sets the details behind the
     Services / Pricing / Contact / Payment Info buttons himself,
     text or photo + caption (/setservices, /setpricing,
     /setcontact, /setpayment + /reset... for each)
 18. Scheduled auto-post: the admin sets one post himself (/setpost,
     text or photo + caption) and the bot sends it to every
     channel/group where it is an admin — groups every 2 hours
     (12/day), channels every 6 hours (4/day). Targets saved with
     /addposttarget, or auto-added when the bot is promoted to
     admin (/posttargets, /autopost on/off, /resetpost)

Runs with long polling + a tiny Flask health endpoint on $PORT,
so it fits Render's free web-service tier (kept awake by a
5-minute UptimeRobot ping, same as the MC ChatBot).

Typing "/" in Telegram shows command suggestions: regular users
see the user commands, and each admin additionally sees the admin
commands (registered at startup in post_init, never fatal).
"""

import logging
import sys
import threading
from datetime import time as dtime
from datetime import timezone

from flask import Flask
from telegram import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    Defaults,
    MessageHandler,
    filters,
)

import config
import database as db
from content import GROUP_KEYWORD_DEFAULTS, SPAM_WORD_DEFAULTS
from handlers import admin, autopost, content_editors, dm, giveaway, group, jobs, report, start_menu, watch, welcome

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Flask health endpoint (Render needs a listening port)
# ------------------------------------------------------------------

flask_app = Flask(__name__)


@flask_app.route("/")
def index():
    return "OK - Agency Bot is running", 200


@flask_app.route("/health")
def health():
    return "healthy", 200


def _run_flask() -> None:
    flask_app.run(host="0.0.0.0", port=config.PORT, threaded=True)


# ------------------------------------------------------------------
# Telegram app
# ------------------------------------------------------------------

# "/" command suggestions (Telegram "bot commands" menu).
# Regular users see USER_COMMANDS only; each admin additionally
# sees ADMIN_COMMANDS in their own chat with the bot
# (BotCommandScopeChat). Registered at startup by post_init —
# a failure only logs, the bot still starts and polls.
# Telegram rules: names lowercase, 1-32 chars; descriptions
# 1-256 chars. Keep these lists in sync with the handlers
# registered in build_application() (incl. the /set...
# conversation entry points in handlers/welcome.py,
# handlers/content_editors.py and handlers/autopost.py).

USER_COMMANDS = [
    BotCommand("start", "Show the main menu"),
    BotCommand("help", "How to use this bot"),
    BotCommand("faq", "Frequently asked questions"),
    BotCommand("redeem", "Redeem a discount coupon"),
    BotCommand("giveawayinfo", "Current giveaway and your entries"),
    BotCommand("report", "Report a message to the admins"),
    BotCommand("cancel", "Cancel what you are doing"),
]

ADMIN_COMMANDS = [
    BotCommand("adminhelp", "List all admin commands"),
    BotCommand("broadcast", "Send a message to all users"),
    BotCommand("stats", "Show bot statistics"),
    BotCommand("addcoupon", "Create a discount coupon"),
    BotCommand("coupons", "List all coupons"),
    BotCommand("delcoupon", "Delete a coupon"),
    BotCommand("vip", "Grant VIP membership to a user"),
    BotCommand("unvip", "Remove VIP membership from a user"),
    BotCommand("vipinfo", "Show a user's VIP status"),
    BotCommand("addkeyword", "Add a group keyword auto-reply"),
    BotCommand("delkeyword", "Remove a group keyword auto-reply"),
    BotCommand("keywords", "List group keyword auto-replies"),
    BotCommand("spamstats", "Show anti-spam statistics"),
    BotCommand("addspamword", "Add a word to the spam list"),
    BotCommand("delspamword", "Remove a word from the spam list"),
    BotCommand("spamwords", "List the spam words"),
    BotCommand("alerts", "Show recent admin alerts"),
    BotCommand("welcome", "Preview the group welcome message"),
    BotCommand("resetwelcome", "Reset the welcome to the default"),
    BotCommand("setwelcome", "Set the group welcome message"),
    BotCommand("giveaway", "Create a giveaway"),
    BotCommand("draw", "Draw the giveaway winner"),
    BotCommand("endgiveaway", "End the current giveaway"),
    BotCommand("setservices", "Set the Services details"),
    BotCommand("setpricing", "Set the Pricing details"),
    BotCommand("setcontact", "Set the Contact details"),
    BotCommand("setpayment", "Set the Payment Info details"),
    BotCommand("resetservices", "Reset Services to the default"),
    BotCommand("resetpricing", "Reset Pricing to the default"),
    BotCommand("resetcontact", "Reset Contact to the default"),
    BotCommand("resetpayment", "Reset Payment Info to the default"),
    BotCommand("setpost", "Set the scheduled auto-post"),
    BotCommand("post", "Preview the scheduled auto-post"),
    BotCommand("resetpost", "Clear the scheduled auto-post"),
    BotCommand("autopost", "Auto-post status / on / off"),
    BotCommand("addposttarget", "Add an auto-post channel/group"),
    BotCommand("delposttarget", "Remove an auto-post target"),
    BotCommand("posttargets", "List auto-post targets"),
]


async def post_init(application: Application) -> None:
    """Runs once at startup: learn our own username, seed keywords."""
    me = await application.bot.get_me()
    application.bot_data["bot_username"] = me.username
    db.seed_keywords(GROUP_KEYWORD_DEFAULTS)
    db.seed_spam_words(SPAM_WORD_DEFAULTS)
    logger.info("Bot started as @%s", me.username)
    await _set_bot_commands(application)


async def _set_bot_commands(application: Application) -> None:
    """Register "/" command suggestions: user commands for
    everyone (default scope), user + admin commands for each
    admin (per-chat scope). Never raises — each call is guarded
    separately, so one failure can't block the others or the
    startup."""
    try:
        await application.bot.set_my_commands(
            USER_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as exc:
        logger.warning("Could not set default bot commands: %s", exc)
    admin_commands = USER_COMMANDS + ADMIN_COMMANDS
    for admin_id in config.ADMIN_IDS:
        try:
            await application.bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as exc:
            logger.warning(
                "Could not set bot commands for admin %s: %s",
                admin_id, exc)


def build_application() -> Application:
    """Build the Application with all handlers registered."""
    defaults = Defaults(parse_mode=ParseMode.HTML)
    app = (Application.builder()
           .token(config.BOT_TOKEN)
           .defaults(defaults)
           .post_init(post_init)
           .build())

    # Group gate FIRST (group -1): force-subscribe + keyword replies.
    # It raises ApplicationHandlerStop for non-members, so no other
    # handler ever sees their messages.
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS,
                       group.handle_group_message),
        group=-1)

    # /setwelcome conversation FIRST in group 0: its callbacks raise
    # ApplicationHandlerStop so the generic /cancel handler and the
    # DM free-text handler (FAQ matching) never also fire on the
    # admin's input — and that only works for handlers registered
    # AFTER this one. Outside a conversation it matches nothing, so
    # normal commands and DM text are unaffected.
    app.add_handler(welcome.setwelcome_conversation())

    # Same ordering for the /set... content editors (Services /
    # Pricing / Contact / Payment Info): one ConversationHandler
    # with four entry points, also before /cancel and DM text.
    app.add_handler(content_editors.setcontent_conversation())

    # Same ordering for the /setpost auto-post editor: one
    # ConversationHandler, also before /cancel and DM text.
    app.add_handler(autopost.setpost_conversation())

    # User commands.
    app.add_handler(CommandHandler("start", start_menu.start))
    app.add_handler(CommandHandler("help", start_menu.help_command))
    app.add_handler(CommandHandler("cancel", start_menu.cancel_command))
    app.add_handler(CommandHandler("faq", dm.faq_command))
    app.add_handler(CommandHandler("redeem", dm.redeem_command))
    app.add_handler(CommandHandler("report", report.report_command))
    app.add_handler(CommandHandler("giveawayinfo",
                                   giveaway.giveawayinfo_command))

    # Admin commands.
    app.add_handler(CommandHandler("adminhelp", admin.adminhelp_command))
    app.add_handler(CommandHandler("broadcast", admin.broadcast_command))
    app.add_handler(CommandHandler("stats", admin.stats_command))
    app.add_handler(CommandHandler("addcoupon", admin.addcoupon_command))
    app.add_handler(CommandHandler("coupons", admin.coupons_command))
    app.add_handler(CommandHandler("delcoupon", admin.delcoupon_command))
    app.add_handler(CommandHandler("vip", admin.vip_command))
    app.add_handler(CommandHandler("unvip", admin.unvip_command))
    app.add_handler(CommandHandler("vipinfo", admin.vipinfo_command))
    app.add_handler(CommandHandler("addkeyword", admin.addkeyword_command))
    app.add_handler(CommandHandler("delkeyword", admin.delkeyword_command))
    app.add_handler(CommandHandler("keywords", admin.keywords_command))
    app.add_handler(CommandHandler("spamstats", admin.spamstats_command))
    app.add_handler(CommandHandler("addspamword",
                                   admin.addspamword_command))
    app.add_handler(CommandHandler("delspamword",
                                   admin.delspamword_command))
    app.add_handler(CommandHandler("spamwords", admin.spamwords_command))
    app.add_handler(CommandHandler("alerts", admin.alerts_command))
    app.add_handler(CommandHandler("welcome", welcome.welcome_command))
    app.add_handler(CommandHandler("resetwelcome",
                                   welcome.resetwelcome_command))
    app.add_handler(CommandHandler(
        "resetservices", content_editors.resetservices_command))
    app.add_handler(CommandHandler(
        "resetpricing", content_editors.resetpricing_command))
    app.add_handler(CommandHandler(
        "resetcontact", content_editors.resetcontact_command))
    app.add_handler(CommandHandler(
        "resetpayment", content_editors.resetpayment_command))
    app.add_handler(CommandHandler("post", autopost.post_command))
    app.add_handler(CommandHandler("resetpost",
                                   autopost.resetpost_command))
    app.add_handler(CommandHandler("autopost",
                                   autopost.autopost_command))
    app.add_handler(CommandHandler("addposttarget",
                                   autopost.addposttarget_command))
    app.add_handler(CommandHandler("delposttarget",
                                   autopost.delposttarget_command))
    app.add_handler(CommandHandler("posttargets",
                                   autopost.posttargets_command))
    app.add_handler(CommandHandler("giveaway",
                                   giveaway.create_giveaway_command))
    app.add_handler(CommandHandler("draw", giveaway.draw_command))
    app.add_handler(CommandHandler("endgiveaway",
                                   giveaway.end_giveaway_command))

    # Membership watch (joins/leaves + bot-status alerts).
    app.add_handler(ChatMemberHandler(watch.track_membership))

    # Button taps: giveaway join and report actions first (specific
    # patterns), then the generic menu dispatcher.
    app.add_handler(CallbackQueryHandler(
        giveaway.join_callback, pattern=r"^join_giveaway:"))
    app.add_handler(CallbackQueryHandler(
        report.report_callback, pattern=r"^report:"))
    app.add_handler(CallbackQueryHandler(start_menu.on_callback))

    # Free text in DMs (coupon codes + FAQ keyword matching).
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        dm.handle_dm_text))

    # Daily lead follow-up, 10:00 UTC.
    if app.job_queue is not None:
        app.job_queue.run_daily(
            jobs.daily_followup,
            time=dtime(hour=10, minute=0, tzinfo=timezone.utc),
            name="lead_followup")
        # Scheduled auto-post, one job per chat type — groups
        # every 2 hours (12/day), channels every 6 hours (4/day);
        # each job's first run is one interval after startup.
        app.job_queue.run_repeating(
            autopost.group_post,
            interval=autopost.GROUP_POST_INTERVAL,
            first=autopost.GROUP_POST_INTERVAL,
            name="group_autopost")
        app.job_queue.run_repeating(
            autopost.channel_post,
            interval=autopost.CHANNEL_POST_INTERVAL,
            first=autopost.CHANNEL_POST_INTERVAL,
            name="channel_autopost")
    else:
        logger.warning(
            "JobQueue is not available — install "
            "python-telegram-bot[job-queue] to enable lead follow-ups "
            "and the auto-post.")

    return app


def main() -> None:
    if not config.BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not set.\n"
              "Create a .env file (see .env.example) or set the "
              "BOT_TOKEN environment variable, then run again.",
              file=sys.stderr)
        sys.exit(1)
    if not config.ADMIN_IDS:
        print("WARNING: ADMIN_IDS is empty — no one can use the admin "
              "commands until you set it.", file=sys.stderr)
    if not config.CHANNEL_ID:
        print("WARNING: CHANNEL_ID is not set — force-subscribe is "
              "disabled until you set it.", file=sys.stderr)

    db.init_db()

    # Health endpoint in a background thread (Render needs a port).
    threading.Thread(target=_run_flask, daemon=True).start()
    logger.info("Health endpoint listening on port %d", config.PORT)

    app = build_application()
    logger.info("Starting polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
