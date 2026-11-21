"""Inline keyboards for the agency bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from content import FAQ
from handlers.common import channel_url


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def main_menu(is_vip: bool = False, subscribed: bool = True) -> InlineKeyboardMarkup:
    """The main menu shown on /start and after most actions."""
    rows = []
    url = channel_url()
    if not subscribed and url:
        rows.append([InlineKeyboardButton("📢 Join Our Channel", url=url)])
        rows.append([_btn("✅ I've Joined", "check_joined")])
    rows += [
        [_btn("🚀 Services", "menu_services"),
         _btn("💰 Pricing", "menu_pricing")],
        [_btn("🌐 Portfolio", "menu_portfolio"),
         _btn("💬 Contact", "menu_contact")],
        [_btn("💳 Payment Info", "menu_payment"),
         _btn("❓ FAQ", "menu_faq")],
        [_btn("🎁 Giveaway", "menu_giveaway"),
         _btn("🎟️ Redeem Coupon", "menu_redeem")],
    ]
    if is_vip:
        rows.append([_btn("👑 VIP Offers", "menu_vip")])
    return InlineKeyboardMarkup(rows)


def back_menu() -> InlineKeyboardMarkup:
    """A single Back button returning to the main menu."""
    return InlineKeyboardMarkup(
        [[_btn("⬅️ Back to Menu", "menu_back")]])


def faq_keyboard() -> InlineKeyboardMarkup:
    """One button per FAQ topic, two per row."""
    rows = []
    for i in range(0, len(FAQ), 2):
        row = [_btn(FAQ[i]["topic"], f"faq:{i}")]
        if i + 1 < len(FAQ):
            row.append(_btn(FAQ[i + 1]["topic"], f"faq:{i + 1}"))
        rows.append(row)
    rows.append([_btn("⬅️ Back to Menu", "menu_back")])
    return InlineKeyboardMarkup(rows)


def faq_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("⬅️ All Questions", "menu_faq")],
        [_btn("🏠 Main Menu", "menu_back")],
    ])


def giveaway_join_keyboard(giveaway_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🎁 Join Giveaway", f"join_giveaway:{giveaway_id}")],
    ])


def channel_join_keyboard() -> InlineKeyboardMarkup:
    """Join + I've Joined buttons (used for the group gate warning)."""
    url = channel_url()
    buttons = []
    if url:
        buttons.append(InlineKeyboardButton("📢 Join Channel", url=url))
    buttons.append(_btn("✅ I've Joined", "check_joined"))
    return InlineKeyboardMarkup([buttons])


def report_keyboard(report_id: int,
                    with_actions: bool = True) -> InlineKeyboardMarkup:
    """Admin buttons on a /report message. DM reports (no reported
    message) only get Dismiss."""
    if with_actions:
        return InlineKeyboardMarkup([
            [_btn("🗑️ Delete message", f"report:delete:{report_id}"),
             _btn("🚫 Ban user", f"report:ban:{report_id}")],
            [_btn("✔️ Dismiss", f"report:dismiss:{report_id}")],
        ])
    return InlineKeyboardMarkup([
        [_btn("✔️ Dismiss", f"report:dismiss:{report_id}")],
    ])
