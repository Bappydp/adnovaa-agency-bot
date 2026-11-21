"""SQLite storage for the agency Telegram bot.

Simple synchronous sqlite3 access guarded by a threading lock.
Volume is low (a few messages per minute), so this is plenty —
no need for an async driver.
"""

import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import DATABASE_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    is_vip        INTEGER NOT NULL DEFAULT 0,
    is_lead       INTEGER NOT NULL DEFAULT 0,
    referred_by   INTEGER,
    blocked       INTEGER NOT NULL DEFAULT 0,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    followups_sent INTEGER NOT NULL DEFAULT 0,
    last_followup TEXT
);

CREATE TABLE IF NOT EXISTS button_clicks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    button     TEXT NOT NULL,
    clicked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS command_usage (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    command  TEXT NOT NULL,
    used_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coupons (
    code       TEXT PRIMARY KEY,
    percent    INTEGER NOT NULL,
    expiry     TEXT NOT NULL,
    created_by INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    redeemed_at TEXT NOT NULL,
    UNIQUE(code, user_id)
);

CREATE TABLE IF NOT EXISTS giveaways (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    ends_at    TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    winner_id  INTEGER,
    created_by INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id  INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    entries      INTEGER NOT NULL DEFAULT 1,
    UNIQUE(giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS keywords (
    word     TEXT PRIMARY KEY,
    reply    TEXT NOT NULL,
    added_by INTEGER
);

CREATE TABLE IF NOT EXISTS spam_words (
    word     TEXT PRIMARY KEY,
    added_by INTEGER
);

CREATE TABLE IF NOT EXISTS spam_strikes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    chat_id    INTEGER NOT NULL,
    reason     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spam_bans (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    chat_id   INTEGER NOT NULL,
    banned_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id      INTEGER NOT NULL,
    reported_user_id INTEGER,
    chat_id          INTEGER NOT NULL,
    message_id       INTEGER,
    reason           TEXT,
    status           TEXT NOT NULL DEFAULT 'open',
    action           TEXT,
    handled_by       INTEGER,
    handled_at       TEXT,
    admin_messages   TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS join_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    joined_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leave_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    left_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    with _lock:
        conn = _connect()
        conn.executescript(SCHEMA)
        conn.commit()


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


# ------------------------------------------------------------------
# Users
# ------------------------------------------------------------------

def add_or_update_user(user_id: int, username: str | None,
                       first_name: str | None,
                       referred_by: int | None = None) -> bool:
    """Insert or refresh a user. Returns True if this is a NEW user."""
    now = _now_iso()
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, referred_by FROM users WHERE user_id = ?",
            (user_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (user_id, username, first_name, "
                "referred_by, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, first_name, referred_by, now, now))
            conn.commit()
            return True
        # Keep the original referrer; never overwrite it.
        conn.execute(
            "UPDATE users SET username = ?, first_name = ?, last_seen = ? "
            "WHERE user_id = ?",
            (username, first_name, now, user_id))
        conn.commit()
        return False


def get_user(user_id: int) -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_activity(user_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute("UPDATE users SET last_seen = ? WHERE user_id = ?",
                     (_now_iso(), user_id))
        conn.commit()


def mark_lead(user_id: int) -> bool:
    """Flag a user as a lead. Returns True if they JUST became a lead."""
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT is_lead FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE users SET is_lead = 1, last_seen = ? WHERE user_id = ?",
            (_now_iso(), user_id))
        conn.commit()
        return row["is_lead"] == 0


def mark_blocked(user_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute("UPDATE users SET blocked = 1 WHERE user_id = ?",
                     (user_id,))
        conn.commit()


def get_all_user_ids() -> list[int]:
    with _lock:
        rows = _connect().execute(
            "SELECT user_id FROM users WHERE blocked = 0").fetchall()
    return [r["user_id"] for r in rows]


# ------------------------------------------------------------------
# Tracking (button clicks + commands) — feeds /stats
# ------------------------------------------------------------------

def record_button_click(user_id: int, button: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO button_clicks (user_id, button, clicked_at) "
            "VALUES (?, ?, ?)", (user_id, button, _now_iso()))
        conn.commit()


def record_command(user_id: int, command: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO command_usage (user_id, command, used_at) "
            "VALUES (?, ?, ?)", (user_id, command, _now_iso()))
        conn.commit()


def get_stats() -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0,
                              microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()
    with _lock:
        conn = _connect()
        total_users = conn.execute(
            "SELECT COUNT(*) FROM users").fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE first_seen >= ?",
            (today_start,)).fetchone()[0]
        new_week = conn.execute(
            "SELECT COUNT(*) FROM users WHERE first_seen >= ?",
            (week_start,)).fetchone()[0]
        total_leads = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_lead = 1").fetchone()[0]
        vip_count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_vip = 1").fetchone()[0]
        blocked_count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE blocked = 1").fetchone()[0]
        top_buttons = conn.execute(
            "SELECT button, COUNT(*) AS c FROM button_clicks "
            "GROUP BY button ORDER BY c DESC LIMIT 10").fetchall()
        top_commands = conn.execute(
            "SELECT command, COUNT(*) AS c FROM command_usage "
            "GROUP BY command ORDER BY c DESC LIMIT 10").fetchall()
    return {
        "total_users": total_users,
        "new_today": new_today,
        "new_week": new_week,
        "total_leads": total_leads,
        "vip_count": vip_count,
        "blocked_count": blocked_count,
        "top_buttons": [(r["button"], r["c"]) for r in top_buttons],
        "top_commands": [(r["command"], r["c"]) for r in top_commands],
    }


# ------------------------------------------------------------------
# Coupons
# ------------------------------------------------------------------

def add_coupon(code: str, percent: int, expiry: str,
               admin_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO coupons "
            "(code, percent, expiry, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (code.upper(), percent, expiry, admin_id, _now_iso()))
        conn.commit()


def list_coupons() -> list[dict]:
    with _lock:
        rows = _connect().execute(
            "SELECT c.*, (SELECT COUNT(*) FROM coupon_redemptions r "
            "WHERE r.code = c.code) AS redemptions "
            "FROM coupons c ORDER BY c.expiry").fetchall()
    return [dict(r) for r in rows]


def delete_coupon(code: str) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM coupons WHERE code = ?",
                           (code.upper(),))
        conn.commit()
        return cur.rowcount > 0


def redeem_coupon(code: str, user_id: int) -> tuple[bool, str]:
    """Try to redeem a coupon for a user. Returns (ok, message)."""
    code = code.strip().upper()
    today = date.today().isoformat()
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM coupons WHERE code = ?", (code,)).fetchone()
        if row is None:
            return False, "❌ That coupon code doesn't exist. Check the spelling and try again."
        if row["expiry"] < today:
            return False, f"❌ Coupon <b>{code}</b> expired on {row['expiry']}."
        already = conn.execute(
            "SELECT 1 FROM coupon_redemptions WHERE code = ? AND user_id = ?",
            (code, user_id)).fetchone()
        if already:
            return False, f"❌ You have already used coupon <b>{code}</b> — one use per person."
        conn.execute(
            "INSERT INTO coupon_redemptions (code, user_id, redeemed_at) "
            "VALUES (?, ?, ?)", (code, user_id, _now_iso()))
        conn.commit()
    return True, (
        f"🎉 Coupon <b>{code}</b> redeemed — <b>{row['percent']}% off</b>!\n\n"
        "Show this message when you order, or mention the code when you "
        "contact us, and we will apply your discount."
    )


# ------------------------------------------------------------------
# Giveaways
# ------------------------------------------------------------------

def create_giveaway(title: str, ends_at: datetime, admin_id: int) -> int:
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO giveaways (title, ends_at, created_by, created_at) "
            "VALUES (?, ?, ?, ?)",
            (title, ends_at.isoformat(), admin_id, _now_iso()))
        conn.commit()
        return cur.lastrowid


def get_active_giveaway() -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT * FROM giveaways WHERE active = 1 "
            "ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def join_giveaway(giveaway_id: int, user_id: int) -> bool:
    """Join a giveaway. Returns True if this is a NEW join."""
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT OR IGNORE INTO giveaway_entries "
            "(giveaway_id, user_id, entries) VALUES (?, ?, 1)",
            (giveaway_id, user_id))
        conn.commit()
        return cur.rowcount > 0


def add_entries(giveaway_id: int, user_id: int, n: int = 1) -> int:
    """Add entries (e.g. for a referral). Returns the new total."""
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO giveaway_entries (giveaway_id, user_id, entries) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(giveaway_id, user_id) DO UPDATE SET "
            "entries = entries + excluded.entries",
            (giveaway_id, user_id, n))
        conn.commit()
        row = conn.execute(
            "SELECT entries FROM giveaway_entries "
            "WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id)).fetchone()
    return row["entries"]


def get_user_entries(giveaway_id: int, user_id: int) -> int:
    with _lock:
        row = _connect().execute(
            "SELECT entries FROM giveaway_entries "
            "WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id)).fetchone()
    return row["entries"] if row else 0


def get_all_entries(giveaway_id: int) -> list[tuple[int, int]]:
    """All (user_id, entries) pairs for a giveaway."""
    with _lock:
        rows = _connect().execute(
            "SELECT user_id, entries FROM giveaway_entries "
            "WHERE giveaway_id = ?", (giveaway_id,)).fetchall()
    return [(r["user_id"], r["entries"]) for r in rows]


def close_giveaway(giveaway_id: int, winner_id: int | None) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE giveaways SET active = 0, winner_id = ? WHERE id = ?",
            (winner_id, giveaway_id))
        conn.commit()


# ------------------------------------------------------------------
# Group keywords
# ------------------------------------------------------------------

def seed_keywords(defaults: list[tuple[str, str]]) -> None:
    """Insert default keywords only if the table is empty."""
    with _lock:
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO keywords (word, reply, added_by) VALUES (?, ?, NULL)",
                defaults)
            conn.commit()


def get_keywords() -> list[tuple[str, str]]:
    with _lock:
        rows = _connect().execute(
            "SELECT word, reply FROM keywords ORDER BY word").fetchall()
    return [(r["word"], r["reply"]) for r in rows]


def add_keyword(word: str, reply: str, admin_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO keywords (word, reply, added_by) "
            "VALUES (?, ?, ?)", (word.lower().strip(), reply, admin_id))
        conn.commit()


def delete_keyword(word: str) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM keywords WHERE word = ?",
                           (word.lower().strip(),))
        conn.commit()
        return cur.rowcount > 0


# ------------------------------------------------------------------
# VIP
# ------------------------------------------------------------------

def set_vip(user_id: int, is_vip: bool) -> bool:
    """Set VIP status. Returns False if the user is unknown to the bot."""
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "UPDATE users SET is_vip = ? WHERE user_id = ?",
            (1 if is_vip else 0, user_id))
        conn.commit()
        return cur.rowcount > 0


def list_vips() -> list[dict]:
    with _lock:
        rows = _connect().execute(
            "SELECT user_id, username, first_name FROM users "
            "WHERE is_vip = 1 ORDER BY first_name").fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Lead follow-up
# ------------------------------------------------------------------

def get_leads_for_followup(days: int = 3, max_followups: int = 2) -> list[dict]:
    """Leads with no activity for `days`+ and fewer than max follow-ups."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _lock:
        rows = _connect().execute(
            "SELECT user_id, username, first_name, followups_sent "
            "FROM users WHERE is_lead = 1 AND blocked = 0 "
            "AND last_seen <= ? AND followups_sent < ?",
            (cutoff, max_followups)).fetchall()
    return [dict(r) for r in rows]


def mark_followup_sent(user_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE users SET followups_sent = followups_sent + 1, "
            "last_followup = ? WHERE user_id = ?",
            (_now_iso(), user_id))
        conn.commit()


# ------------------------------------------------------------------
# Anti-spam: words, strikes, bans
# ------------------------------------------------------------------

def seed_spam_words(defaults: list[str]) -> None:
    """Insert default spam words only if the table is empty."""
    with _lock:
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM spam_words").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO spam_words (word, added_by) VALUES (?, NULL)",
                [(w,) for w in defaults])
            conn.commit()


def get_spam_words() -> list[str]:
    with _lock:
        rows = _connect().execute(
            "SELECT word FROM spam_words ORDER BY word").fetchall()
    return [r["word"] for r in rows]


def add_spam_word(word: str, admin_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO spam_words (word, added_by) "
            "VALUES (?, ?)", (word.lower().strip(), admin_id))
        conn.commit()


def delete_spam_word(word: str) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM spam_words WHERE word = ?",
                           (word.lower().strip(),))
        conn.commit()
        return cur.rowcount > 0


def record_strike(user_id: int, chat_id: int, reason: str,
                  window_hours: int = 24) -> int:
    """Record a spam strike. Returns the user's strike count inside
    the rolling window (including the one just recorded)."""
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO spam_strikes (user_id, chat_id, reason, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, chat_id, reason, _now_iso()))
        conn.commit()
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=window_hours)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) FROM spam_strikes "
            "WHERE user_id = ? AND chat_id = ? AND created_at >= ?",
            (user_id, chat_id, cutoff)).fetchone()[0]
    return count


def get_strikes_24h(user_id: int, chat_id: int) -> int:
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=24)).isoformat()
    with _lock:
        count = _connect().execute(
            "SELECT COUNT(*) FROM spam_strikes "
            "WHERE user_id = ? AND chat_id = ? AND created_at >= ?",
            (user_id, chat_id, cutoff)).fetchone()[0]
    return count


def record_spam_ban(user_id: int, chat_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO spam_bans (user_id, chat_id, banned_at) "
            "VALUES (?, ?, ?)", (user_id, chat_id, _now_iso()))
        conn.commit()


def get_spam_stats() -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0,
                              microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()
    with _lock:
        conn = _connect()
        strikes_today = conn.execute(
            "SELECT COUNT(*) FROM spam_strikes WHERE created_at >= ?",
            (today_start,)).fetchone()[0]
        bans_today = conn.execute(
            "SELECT COUNT(*) FROM spam_bans WHERE banned_at >= ?",
            (today_start,)).fetchone()[0]
        strikes_week = conn.execute(
            "SELECT COUNT(*) FROM spam_strikes WHERE created_at >= ?",
            (week_start,)).fetchone()[0]
        bans_week = conn.execute(
            "SELECT COUNT(*) FROM spam_bans WHERE banned_at >= ?",
            (week_start,)).fetchone()[0]
    return {
        "strikes_today": strikes_today,
        "bans_today": bans_today,
        "strikes_week": strikes_week,
        "bans_week": bans_week,
    }


# ------------------------------------------------------------------
# Reports
# ------------------------------------------------------------------

def create_report(reporter_id: int, reported_user_id: int | None,
                  chat_id: int, message_id: int | None,
                  reason: str | None) -> int:
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO reports (reporter_id, reported_user_id, chat_id, "
            "message_id, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (reporter_id, reported_user_id, chat_id, message_id,
             reason, _now_iso()))
        conn.commit()
        return cur.lastrowid


def get_report(report_id: int) -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    return dict(row) if row else None


def set_report_admin_messages(report_id: int, admin_messages: str) -> None:
    """Store the JSON list of [admin_id, message_id] copies of the
    report, so an action can update every admin's copy."""
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE reports SET admin_messages = ? WHERE id = ?",
            (admin_messages, report_id))
        conn.commit()


def set_report_status(report_id: int, action: str,
                      handled_by: int) -> bool:
    """Mark a report handled — but ONLY if it is still open.
    Returns False if another admin already handled it (race-safe)."""
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "UPDATE reports SET status = 'handled', action = ?, "
            "handled_by = ?, handled_at = ? "
            "WHERE id = ? AND status = 'open'",
            (action, handled_by, _now_iso(), report_id))
        conn.commit()
        return cur.rowcount > 0


def count_reports_last_hour(reporter_id: int) -> int:
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=1)).isoformat()
    with _lock:
        count = _connect().execute(
            "SELECT COUNT(*) FROM reports "
            "WHERE reporter_id = ? AND created_at >= ?",
            (reporter_id, cutoff)).fetchone()[0]
    return count


# ------------------------------------------------------------------
# Join / leave tracking + alert state
# ------------------------------------------------------------------

def record_join(chat_id: int, user_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO join_events (chat_id, user_id, joined_at) "
            "VALUES (?, ?, ?)", (chat_id, user_id, _now_iso()))
        conn.commit()


def get_last_join(chat_id: int, user_id: int) -> datetime | None:
    """When the user last joined this chat, or None if unknown
    (e.g. they joined before the bot was added)."""
    with _lock:
        row = _connect().execute(
            "SELECT joined_at FROM join_events "
            "WHERE chat_id = ? AND user_id = ? "
            "ORDER BY joined_at DESC LIMIT 1",
            (chat_id, user_id)).fetchone()
    if not row:
        return None
    return datetime.fromisoformat(row["joined_at"])


def record_leave(chat_id: int, user_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO leave_events (chat_id, user_id, left_at) "
            "VALUES (?, ?, ?)", (chat_id, user_id, _now_iso()))
        conn.commit()


def count_leaves_since(chat_id: int, hours: float) -> int:
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=hours)).isoformat()
    with _lock:
        count = _connect().execute(
            "SELECT COUNT(*) FROM leave_events "
            "WHERE chat_id = ? AND left_at >= ?",
            (chat_id, cutoff)).fetchone()[0]
    return count


def get_leave_stats(chat_id: int) -> dict:
    return {
        "last_hour": count_leaves_since(chat_id, 1),
        "last_24h": count_leaves_since(chat_id, 24),
    }


def get_alert_value(key: str) -> str | None:
    with _lock:
        row = _connect().execute(
            "SELECT value FROM alert_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_alert_value(key: str, value: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO alert_state (key, value) VALUES (?, ?)",
            (key, value))
        conn.commit()


def mass_leave_alert_due(chat_id: int, threshold: int,
                         window_hours: float,
                         cooldown_hours: float) -> tuple[bool, int]:
    """Check whether a mass-leave alert should fire for this chat.

    Returns (due, leaves_in_window). The alert fires when leaves in
    the window reach the threshold AND the cooldown has passed since
    the last alert for this chat. Does NOT update the cooldown —
    callers record it after sending the alert.
    """
    leaves = count_leaves_since(chat_id, window_hours)
    if leaves < threshold:
        return False, leaves
    last = get_alert_value(f"mass_leave:{chat_id}")
    if last:
        last_dt = datetime.fromisoformat(last)
        elapsed = datetime.now(timezone.utc) - last_dt
        if elapsed < timedelta(hours=cooldown_hours):
            return False, leaves
    return True, leaves


def record_mass_leave_alert(chat_id: int) -> None:
    set_alert_value(f"mass_leave:{chat_id}", _now_iso())
