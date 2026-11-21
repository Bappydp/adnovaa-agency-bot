"""Scheduled jobs: the daily lead follow-up."""

import logging

from telegram.error import Forbidden
from telegram.ext import ContextTypes

import database as db
import keyboards
from content import FOLLOWUP_1, FOLLOWUP_2

logger = logging.getLogger(__name__)


async def daily_followup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Once a day: message leads with no activity for 3+ days.

    At most 2 follow-ups per lead, then we stop. Users who blocked
    the bot are flagged and never messaged again.
    """
    leads = db.get_leads_for_followup(days=3, max_followups=2)
    if not leads:
        logger.info("Lead follow-up: no leads due.")
        return
    sent = 0
    for lead in leads:
        text = FOLLOWUP_1 if lead["followups_sent"] == 0 else FOLLOWUP_2
        try:
            await context.bot.send_message(
                lead["user_id"], text,
                reply_markup=keyboards.main_menu())
            db.mark_followup_sent(lead["user_id"])
            sent += 1
        except Forbidden:
            db.mark_blocked(lead["user_id"])
            logger.info("Lead %s blocked the bot — flagged.",
                        lead["user_id"])
        except Exception as exc:
            logger.warning("Follow-up to %s failed: %s",
                           lead["user_id"], exc)
    logger.info("Lead follow-up: sent %d of %d due.", sent, len(leads))
