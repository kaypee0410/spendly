import os
import sqlite3
from datetime import date, datetime

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "expense_tracker.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount      REAL NOT NULL,
    category    TEXT NOT NULL,
    date        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

# (day of current month, amount, category, description)
SEED_EXPENSES = [
    (1, 1200.00, "Bills", "Monthly rent"),
    (3, 45.50, "Food", "Groceries"),
    (5, 30.00, "Transport", "Metro card top-up"),
    (8, 60.00, "Health", "Pharmacy"),
    (12, 25.00, "Entertainment", "Movie tickets"),
    (15, 89.99, "Shopping", "New shoes"),
    (20, 18.75, "Food", "Lunch with friends"),
    (25, 15.00, "Other", None),
]


def get_db():
    """Return a SQLite connection with dict-like rows and FK enforcement."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables. Safe to call multiple times."""
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_user_by_email(email):
    """Return the users row matching email, or None."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, name, email, password_hash, created_at "
            "FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()


def create_user(name, email, password):
    """Insert a user with a hashed password. Return the new id, or None if the email exists."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def authenticate_user(email, password):
    """Return the users row if email and password match, otherwise None."""
    user = get_user_by_email(email)
    if user is None or not check_password_hash(user["password_hash"], password):
        return None
    return user


def seed_db():
    """Insert a demo user and sample expenses, only if no users exist."""
    conn = get_db()
    try:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count > 0:
            return

        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
        )
        user_id = cur.lastrowid

        today = date.today()
        rows = [
            (user_id, amount, category, today.replace(day=day).isoformat(), description)
            for day, amount, category, description in SEED_EXPENSES
        ]
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Profile queries                                                     #
# ------------------------------------------------------------------ #

def get_user_by_id(user_id):
    """Return {name, email, member_since} for user_id, or None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    return {
        "name": row["name"],
        "email": row["email"],
        "member_since": created.strftime("%B %Y"),
    }


def _date_range_clause(start_date, end_date):
    """Return (sql_fragment, params) limiting expenses.date to an inclusive range.

    The fragment is built only from constant strings; dates go in params.
    """
    clause = ""
    params = []
    if start_date is not None:
        clause += " AND date >= ?"
        params.append(start_date)
    if end_date is not None:
        clause += " AND date <= ?"
        params.append(end_date)
    return clause, params


def get_summary_stats(user_id, start_date=None, end_date=None):
    """Return total spent, transaction count and top category for a user."""
    date_sql, date_params = _date_range_clause(start_date, end_date)
    params = [user_id, *date_params]
    conn = get_db()
    try:
        totals = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(ROUND(SUM(amount), 2), 0) AS total "
            "FROM expenses WHERE user_id = ?" + date_sql,
            params,
        ).fetchone()
        if totals["cnt"] == 0:
            return {"total_spent": 0, "transaction_count": 0, "top_category": "—"}

        top = conn.execute(
            "SELECT category FROM expenses WHERE user_id = ?" + date_sql
            + " GROUP BY category ORDER BY SUM(amount) DESC, category ASC LIMIT 1",
            params,
        ).fetchone()
        return {
            "total_spent": float(totals["total"]),
            "transaction_count": totals["cnt"],
            "top_category": top["category"],
        }
    finally:
        conn.close()


def get_recent_transactions(user_id, limit=10, start_date=None, end_date=None):
    """Return a user's most recent expenses, newest first, as plain dicts."""
    date_sql, date_params = _date_range_clause(start_date, end_date)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT date, description, category, amount FROM expenses "
            "WHERE user_id = ?" + date_sql + " ORDER BY date DESC, id DESC LIMIT ?",
            [user_id, *date_params, limit],
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_category_breakdown(user_id, start_date=None, end_date=None):
    """Return [{name, amount, pct}] by amount desc; pct ints summing to 100."""
    date_sql, date_params = _date_range_clause(start_date, end_date)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category AS name, ROUND(SUM(amount), 2) AS amount "
            "FROM expenses WHERE user_id = ?" + date_sql
            + " GROUP BY category ORDER BY amount DESC, name ASC",
            [user_id, *date_params],
        ).fetchall()
    finally:
        conn.close()

    categories = [{"name": r["name"], "amount": r["amount"], "pct": 0} for r in rows]
    total = sum(c["amount"] for c in categories)
    if total <= 0:
        return categories

    for c in categories:
        c["pct"] = round(c["amount"] / total * 100)
    # The largest category absorbs any rounding remainder so pcts sum to 100.
    categories[0]["pct"] += 100 - sum(c["pct"] for c in categories)
    return categories
