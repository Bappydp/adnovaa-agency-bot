"""ALL editable bot content lives in this file.

Change texts, services, prices, FAQs, keyword replies and payment
details HERE — no other file needs touching for copy changes.

All user-facing text is in ENGLISH (international clients).

=====================================================================
TODO — PRICES AND PAYMENT DETAILS ARE PLACEHOLDERS
The package prices below come from the owner's own 2026-10-29
PROPOSAL — he has NOT confirmed them as final prices. The wallet
address is a placeholder ("PASTE_YOUR_WALLET_HERE"). Replace them
with real prices and a real wallet address before promoting the
bot to clients.
=====================================================================
"""

AGENCY_NAME = "Facebook | Google Ads Agencies"
WHATSAPP_NUMBER = "+1 (623) 329-7869"
TELEGRAM_CONTACT = "@Adnovaa_agency"
GROUP_URL = "https://t.me/Facebook_google_adnovaa"
WEBSITE_URL = "https://adnovaa.com"
INSTAGRAM_HANDLE = "@manikadsexpert"

# ------------------------------------------------------------------
# Welcome / help
# ------------------------------------------------------------------

WELCOME = (
    f"👋 Welcome to <b>{AGENCY_NAME}</b>!\n\n"
    "We help businesses get real sales from Facebook and Google Ads — "
    "no theory, no fluff.\n\n"
    "Choose below 👇"
)

WELCOME_NOT_SUBSCRIBED = (
    f"👋 Welcome to <b>{AGENCY_NAME}</b>!\n\n"
    "We help businesses get real sales from Facebook and Google Ads — "
    "no theory, no fluff.\n\n"
    "📢 <b>First, join our channel</b> for tips, offers and giveaways — "
    "then explore the menu below 👇"
)

HELP_TEXT = (
    "🤖 <b>How to use this bot</b>\n\n"
    "Tap the buttons in the menu, or use these commands:\n"
    "• /start — main menu\n"
    "• /faq — frequently asked questions\n"
    "• /redeem CODE — redeem a discount coupon\n"
    "• /giveawayinfo — current giveaway and your entries\n"
    "• /report — report a spam message (in the group, reply to the "
    "message with /report; here, just describe the problem)\n"
    "• /cancel — cancel what you are doing\n\n"
    "You can also just type a question — I answer common ones about "
    "pricing, delivery time, refunds and payments."
)

FALLBACK_TEXT = (
    "I didn't catch that 🙂\n\n"
    "Tap a button below, or type a question about pricing, services, "
    "delivery time, refunds or payment."
)

# ------------------------------------------------------------------
# Services
# ------------------------------------------------------------------
# (emoji, name, short description) — edit freely.

SERVICES = [
    ("📘", "Facebook Ads",
     "Full-funnel campaigns that find buyers, not just likes."),
    ("🔍", "Google Ads",
     "Search and Shopping campaigns that catch people ready to buy."),
    ("🌐", "Website Design",
     "Fast, clean websites and stores built to turn visitors into orders."),
    ("🛠️", "Ad Account Setup & Audit",
     "New ad account setup, Pixel / Conversion API, and a full audit "
     "that shows where your budget is being wasted."),
    ("🎯", "Retargeting",
     "Bring back the visitors who left without buying."),
    ("📊", "Pixel & Tracking Setup",
     "Pixel and Conversion API installed properly, so every sale is measured."),
]


def render_services() -> str:
    lines = ["🚀 <b>Our Services</b>\n"]
    for emoji, name, desc in SERVICES:
        lines.append(f"{emoji} <b>{name}</b> — {desc}")
    lines.append(
        "\n💬 Tap <b>Contact</b> and tell us what you need — "
        "we reply with a plan and a quote within 24 hours."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Packages / pricing
# ------------------------------------------------------------------
# TODO: prices below are PLACEHOLDER examples from the 2026-10-29
# proposal — NOT confirmed. Replace with real prices before launch.

PACKAGES = [
    {
        "name": "Starter",
        "emoji": "🟢",
        # TODO: replace with your real Starter price
        "price": "$300 one-time (example)",
        "tagline": "For businesses just starting with paid ads.",
        "includes": [
            "Ad account setup",
            "First campaign (Facebook or Google)",
            "Pixel / tracking check",
        ],
    },
    {
        "name": "Growth",
        "emoji": "🔵",
        # TODO: replace with your real Growth price
        "price": "$500/month (example)",
        "tagline": "Ongoing management for steady growth.",
        "includes": [
            "Ongoing Facebook / Google Ads management",
            "Weekly testing and optimisation",
            "Monthly performance report",
        ],
    },
    {
        "name": "Premium",
        "emoji": "🟣",
        # TODO: replace with your real Premium price
        "price": "$1,000/month (example)",
        "tagline": "Full growth partner for scaling brands.",
        "includes": [
            "Everything in Growth",
            "Sales funnels and landing pages",
            "Retargeting and scaling strategy",
            "Priority support",
        ],
    },
]


def render_packages() -> str:
    lines = ["💰 <b>Packages</b>\n"]
    for pkg in PACKAGES:
        lines.append(f"{pkg['emoji']} <b>{pkg['name']}</b> — {pkg['price']}")
        lines.append(f"<i>{pkg['tagline']}</i>")
        for item in pkg["includes"]:
            lines.append(f"  • {item}")
        lines.append("")
    lines.append(
        "Ad spend is always separate, and always from <b>your</b> card — never ours.\n"
        "Exact quote after a free audit of your account."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Contact / payment
# ------------------------------------------------------------------

CONTACT = (
    "💬 <b>Contact</b>\n\n"
    f"• WhatsApp: {WHATSAPP_NUMBER}\n"
    f"• Telegram: {TELEGRAM_CONTACT}\n"
    f"• Group: {GROUP_URL}\n\n"
    "Tell us your business and what you need — we reply with a plan "
    "and a quote within 24 hours."
)

# TODO: replace the placeholder wallet with your REAL wallet address.
PAYMENT_INFO = (
    "💳 <b>Payment Info</b>\n\n"
    "We accept:\n"
    "• <b>USDT (TRC20)</b> — wallet address:\n"
    "<code>PASTE_YOUR_WALLET_HERE</code>\n"
    "• Bank transfer — ask us on WhatsApp for details\n"
    "• Other methods — message us and we will arrange it\n\n"
    "⚠️ Always confirm the wallet address with us on WhatsApp or "
    "Telegram before sending any payment.\n\n"
    f"WhatsApp: {WHATSAPP_NUMBER}\n"
    f"Telegram: {TELEGRAM_CONTACT}"
)

# ------------------------------------------------------------------
# FAQ — shown by /faq and matched against free text in DMs.
# Each entry: topic shown as a button, keywords that trigger it,
# and the answer.
# ------------------------------------------------------------------

FAQ = [
    {
        "topic": "Pricing",
        "keywords": ("price", "pricing", "cost", "how much", "package"),
        "answer": (
            "💰 <b>Pricing</b>\n\n"
            "We have 3 packages — Starter, Growth and Premium. "
            "Tap <b>Pricing</b> in the menu for details.\n\n"
            "Ad spend is always separate, from your own card. "
            "Exact quote after a free audit of your account."
        ),
    },
    {
        "topic": "Delivery time",
        "keywords": ("delivery", "how long", "time", "when", "fast", "start"),
        # TODO: confirm these turnaround times are accurate.
        "answer": (
            "⏱️ <b>Delivery time</b>\n\n"
            "• Free ad account audit: within 24–48 hours\n"
            "• First campaign live: usually within 3–5 working days\n"
            "• Website / landing page: depends on scope, usually 1–2 weeks\n\n"
            "Message us with your deadline and we will confirm."
        ),
    },
    {
        "topic": "Refund policy",
        "keywords": ("refund", "money back", "cancel"),
        "answer": (
            "↩️ <b>Refund policy</b>\n\n"
            "Ad spend goes directly to Facebook / Google from your own "
            "card, so there is nothing for us to refund on spend.\n\n"
            "Management fees are agreed before work starts. If we have "
            "not started your work yet, the fee is refundable — message "
            "us and we will sort it out."
        ),
    },
    {
        "topic": "Free audit",
        "keywords": ("audit", "free audit", "check my account"),
        "answer": (
            "🎁 <b>Free Ad Account Audit</b>\n\n"
            "We personally check your ad account and tell you where "
            "budget is being wasted and what to fix first — free.\n\n"
            f"Message us on WhatsApp {WHATSAPP_NUMBER} or Telegram "
            f"{TELEGRAM_CONTACT} with your business name and ad account "
            "details to book your audit."
        ),
    },
    {
        "topic": "Payment methods",
        "keywords": ("payment", "pay", "usdt", "wallet", "bank"),
        "answer": (
            "💳 <b>Payment methods</b>\n\n"
            "We accept USDT (TRC20) and bank transfer. Tap <b>Payment Info</b> "
            "in the menu for the wallet address and details.\n\n"
            "⚠️ Always confirm the wallet address with us before sending "
            "any payment."
        ),
    },
    {
        "topic": "Contact a human",
        "keywords": ("contact", "talk", "human", "whatsapp", "support", "help"),
        "answer": CONTACT,
    },
    {
        "topic": "Our services",
        "keywords": ("service", "services", "offer", "what do you do"),
        "answer": (
            "🚀 <b>Our services</b>\n\n"
            "Facebook Ads, Google Ads, website design, ad account setup "
            "and audit, retargeting, and Pixel / tracking setup.\n\n"
            "Tap <b>Services</b> in the menu for the full list."
        ),
    },
]

# ------------------------------------------------------------------
# Group keyword auto-replies (defaults — admins can add/remove
# words at runtime with /addkeyword and /delkeyword).
# ------------------------------------------------------------------

GROUP_KEYWORD_DEFAULTS = [
    ("price",
     "💰 Our packages start from the Starter plan — DM this bot and tap "
     "Pricing for details, or message us for an exact quote after a free audit."),
    ("pricing",
     "💰 Our packages start from the Starter plan — DM this bot and tap "
     "Pricing for details, or message us for an exact quote after a free audit."),
    ("service",
     "🚀 We do Facebook Ads, Google Ads, website design, ad account setup "
     "and audit, retargeting and tracking setup. DM this bot and tap Services!"),
    ("audit",
     "🎁 We offer a FREE ad account audit — we check where your budget is "
     "being wasted and what to fix first. DM this bot for details!"),
    ("contact",
     f"💬 You can reach us on WhatsApp {WHATSAPP_NUMBER} or Telegram "
     f"{TELEGRAM_CONTACT} — or DM this bot and tap Contact."),
    ("discount",
     "🎟️ Discounts and coupons are announced in our channel — join it so "
     "you don't miss the next one! DM this bot and tap Redeem Coupon if "
     "you already have a code."),
]

# ------------------------------------------------------------------
# VIP
# ------------------------------------------------------------------

VIP_OFFERS = (
    "👑 <b>VIP Member Offers</b>\n\n"
    "As a VIP member you get:\n"
    "• Early access to new services and offers\n"
    "• Priority replies — your messages come first\n"
    "• Exclusive VIP-only discounts and giveaways\n\n"
    "New VIP offers are announced here first. Stay tuned!"
)

# ------------------------------------------------------------------
# Lead follow-up (sent automatically, max 2 per lead)
# ------------------------------------------------------------------

FOLLOWUP_1 = (
    "👋 Hi! You checked out our services a few days ago — just "
    "wondering if you still need help with Facebook or Google Ads?\n\n"
    "If you have any questions, just reply here — or tap Contact to "
    "talk to us directly."
)

FOLLOWUP_2 = (
    "👋 One last check-in — if you are still thinking about ads for "
    "your business, we are here whenever you are ready.\n\n"
    "🎁 A free ad account audit is a good first step — no commitment, "
    "just honest feedback on your account. Tap Contact to book it."
)

# ------------------------------------------------------------------
# Giveaway
# ------------------------------------------------------------------

GIVEAWAY_NONE_ACTIVE = (
    "🎁 <b>Giveaway</b>\n\n"
    "No giveaway is running right now. Join our channel so you don't "
    "miss the next one!"
)

# ------------------------------------------------------------------
# Force-subscribe (group warning)
# ------------------------------------------------------------------

GROUP_JOIN_WARNING = (
    "👋 Hi {name}! To write in this group, please join our channel first:\n"
    "{channel_url}\n\n"
    "Join, then tap <b>✅ I've Joined</b> below."
)

# Default post-join welcome in the group (after a member taps
# "I've Joined"). The admin can replace it with /setwelcome —
# the custom text supports the same {name} placeholder.
GROUP_WELCOME_DEFAULT = (
    "✅ {name}, you're in — welcome! You can write in the group now."
)

# ------------------------------------------------------------------
# Group protection: anti-spam, /report, admin alerts
# ------------------------------------------------------------------
# Spam words: OBVIOUS spam only. Never add normal words here
# ("price", "service", "audit" ...) — those belong to the keyword
# auto-reply above. A single word is matched as a whole word;
# a phrase (contains a space) is matched as a substring.
# Admins can add/remove words at runtime with /addspamword and
# /delspamword.

SPAM_WORD_DEFAULTS = [
    # Crypto / money scams
    "double your crypto",
    "double your bitcoin",
    "double your money",
    "double your investment",
    "free money",
    "free usdt",
    "free bitcoin",
    "free crypto",
    "click here to earn",
    "earn money fast",
    "guaranteed profit",
    "guaranteed returns",
    "crypto giveaway",
    "bitcoin giveaway",
    "send 0.1 btc",
    "send 1 eth",
    "investment opportunity guaranteed",
    "dm me to earn",
    # Casino / betting promos
    "casino",
    "online casino",
    "betting site",
    "slot machine",
    # Adult spam
    "porn",
    "xxx video",
    "onlyfans",
    "adult video",
    # Fake growth services
    "buy followers",
    "buy subscribers",
    "cheap followers",
]

SPAM_WARNING = (
    "⚠️ {name}, your message was removed as spam. "
    "(Strike {strikes} of {limit} — {limit} strikes in 24 hours = ban.)"
)

SPAM_BANNED = (
    "🚫 {name} has been banned from the group for repeated spam."
)

# --- /report ------------------------------------------------------

REPORT_NEED_REPLY = (
    "To report a message, <b>reply</b> to it with /report "
    "(you can add a reason after the command, e.g. "
    "<code>/report spam link</code>)."
)

REPORT_NEED_TEXT = (
    "Please describe the problem after the command, e.g. "
    "<code>/report someone is spamming the group</code>."
)

REPORT_LIMIT = (
    "You've reached the report limit, try again later."
)

REPORT_THANKS = (
    "✅ Thanks — the admins have been notified and will check it."
)

REPORT_ADMIN_TITLE = "🚨 <b>New Report #{report_id}</b>"

# --- Admin alerts ---------------------------------------------------

ALERT_MASS_LEAVE = (
    "⚠️ <b>Mass leave alert</b>\n\n"
    "<b>{count} members</b> left {chat} in the last {window}.\n"
    "Check the group — something may be wrong (spam attack, "
    "bad post, or a raid)."
)

ALERT_BOT_REMOVED = (
    "🚨 <b>Bot removed!</b>\n\n"
    "This bot was removed/kicked from {chat}. "
    "Force-subscribe, anti-spam and keyword replies there have "
    "stopped working until the bot is added back as admin."
)

ALERT_BOT_DEMOTED = (
    "⚠️ <b>Bot lost admin rights</b>\n\n"
    "This bot is no longer an admin in {chat}. "
    "It can no longer delete messages or ban spammers there — "
    "please make it an admin again."
)

ALERT_AUTOPOST_FAILED = (
    "⚠️ <b>Auto-post failed in some places</b>\n\n"
    "{failures}{removed_note}"
)

AUTOPOST_TARGET_ADDED = (
    "📢 <b>Auto-post target added</b>\n\n"
    "I was made an admin in {chat}, so the scheduled post will now "
    "go there too. ({count}/{max} targets)"
)

AUTOPOST_TARGET_FULL = (
    "📢 <b>Auto-post target NOT added</b>\n\n"
    "I was made an admin in {chat}, but the auto-post list is "
    "full ({max} targets). Remove one with /delposttarget first, "
    "then add this chat with /addposttarget."
)
