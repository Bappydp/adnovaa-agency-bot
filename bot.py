"""Agency Telegram Bot — Facebook | Google Ads Agencies.

Features (all 15):
  1. /start welcome + button menu (Services, Portfolio, Pricing, Contact)
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

Runs with long polling + a tiny Flask health endpoint on $PORT,
so it fits Render's free web-service tier (kept awake by a
5-minute UptimeRobot ping, same as the MC ChatBot).
"""

import logging
import sys
import threading
from datetime import time as dtime
from datetime import timezone

from flask import Flask
from telegram import Update
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
from handlers import admin, dm, giveaway, group, jobs, report, start_menu, watch

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

async def post_init(application: Application) -> None:
    """Runs once at startup: learn our own username, seed keywords."""
    me = await application.bot.get_me()
    application.bot_data["bot_username"] = me.username
    db.seed_keywords(GROUP_KEYWORD_DEFAULTS)
    db.seed_spam_words(SPAM_WORD_DEFAULTS)
    logger.info("Bot started as @%s", me.username)


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
    else:
        logger.warning(
            "JobQueue is not available — install "
            "python-telegram-bot[job-queue] to enable lead follow-ups.")

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
