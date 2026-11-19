"""Step 5: profile query helpers in database/db.py and the live /profile route."""
import re
from datetime import date, datetime

import pytest

from database.db import (
    SEED_EXPENSES,
    create_user,
    get_category_breakdown,
    get_db,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_email,
    get_user_by_id,
)

DEMO = {"email": "demo@spendly.com", "password": "demo123"}


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def demo_id():
    return get_user_by_email(DEMO["email"])["id"]


def new_user(email="empty@example.com", name="Empty User"):
    return create_user(name, email, "password123")


def add_expense(user_id, amount, category, day, description=None):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, seed_date(day), description),
        )
        conn.commit()
    finally:
        conn.close()


def seed_date(day):
    return date.today().replace(day=day).isoformat()


def log_in_as(client, user_id, name="Demo User"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = name


# ------------------------------------------------------------------ #
# get_user_by_id                                                      #
# ------------------------------------------------------------------ #

def test_get_user_by_id_valid(app):
    user = get_user_by_id(demo_id())
    created_at = get_user_by_email(DEMO["email"])["created_at"]
    expected = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").strftime("%B %Y")

    assert user == {
        "name": "Demo User",
        "email": "demo@spendly.com",
        "member_since": expected,
    }
    assert re.fullmatch(r"[A-Z][a-z]+ \d{4}", user["member_since"])


def test_get_user_by_id_missing(app):
    assert get_user_by_id(99999) is None


# ------------------------------------------------------------------ #
# get_summary_stats                                                   #
# ------------------------------------------------------------------ #

def test_summary_stats_seeded_user(app):
    stats = get_summary_stats(demo_id())
    assert stats["total_spent"] == pytest.approx(1484.24)
    assert isinstance(stats["total_spent"], float)
    assert stats["transaction_count"] == 8
    assert stats["top_category"] == "Bills"


def test_summary_stats_empty_user(app):
    assert get_summary_stats(new_user()) == {
        "total_spent": 0,
        "transaction_count": 0,
        "top_category": "—",
    }


def test_summary_stats_top_category_tie_breaks_alphabetically(app):
    user_id = new_user(email="tie@example.com")
    add_expense(user_id, 10.00, "Food", 1)
    add_expense(user_id, 10.00, "Bills", 2)

    stats = get_summary_stats(user_id)
    assert stats["top_category"] == "Bills"
    assert stats["transaction_count"] == 2
    assert stats["total_spent"] == pytest.approx(20.00)


def test_summary_stats_scoped_to_user(app):
    before = get_summary_stats(demo_id())
    other_id = new_user(email="other@example.com")
    add_expense(other_id, 5000.00, "Shopping", 1, "Not the demo user's")

    assert get_summary_stats(demo_id()) == before
    assert get_summary_stats(other_id)["total_spent"] == pytest.approx(5000.00)


# ------------------------------------------------------------------ #
# get_recent_transactions                                             #
# ------------------------------------------------------------------ #

def test_recent_transactions_ordered_newest_first(app):
    rows = get_recent_transactions(demo_id())

    expected = [
        {
            "date": seed_date(day),
            "description": description,
            "category": category,
            "amount": amount,
        }
        for day, amount, category, description in sorted(
            SEED_EXPENSES, key=lambda e: e[0], reverse=True
        )
    ]
    assert rows == expected
    assert rows[0]["category"] == "Other"
    assert rows[0]["description"] is None


def test_recent_transactions_respects_limit(app):
    rows = get_recent_transactions(demo_id(), limit=3)
    assert [r["date"] for r in rows] == [seed_date(25), seed_date(20), seed_date(15)]


def test_recent_transactions_empty_user(app):
    assert get_recent_transactions(new_user()) == []


def test_recent_transactions_scoped_to_user(app):
    other_id = new_user(email="other@example.com")
    add_expense(other_id, 42.00, "Food", 28, "Other user's lunch")

    assert len(get_recent_transactions(demo_id())) == 8
    assert get_recent_transactions(other_id) == [
        {
            "date": seed_date(28),
            "description": "Other user's lunch",
            "category": "Food",
            "amount": 42.00,
        }
    ]


# ------------------------------------------------------------------ #
# get_category_breakdown                                              #
# ------------------------------------------------------------------ #

def test_category_breakdown_seeded(app):
    breakdown = get_category_breakdown(demo_id())

    assert [(r["name"], r["pct"]) for r in breakdown] == [
        ("Bills", 81),
        ("Shopping", 6),
        ("Food", 4),
        ("Health", 4),
        ("Transport", 2),
        ("Entertainment", 2),
        ("Other", 1),
    ]
    amounts = [r["amount"] for r in breakdown]
    assert amounts == sorted(amounts, reverse=True)
    assert all(isinstance(r["pct"], int) for r in breakdown)
    assert sum(r["pct"] for r in breakdown) == 100
    food = next(r for r in breakdown if r["name"] == "Food")
    assert food["amount"] == pytest.approx(64.25)


def test_category_breakdown_largest_row_absorbs_remainder(app):
    user_id = new_user()
    add_expense(user_id, 10.00, "A", 1)
    add_expense(user_id, 10.00, "B", 2)
    add_expense(user_id, 10.00, "C", 3)

    breakdown = get_category_breakdown(user_id)
    assert [r["name"] for r in breakdown] == ["A", "B", "C"]
    assert [r["pct"] for r in breakdown] == [34, 33, 33]


def test_category_breakdown_empty_user(app):
    assert get_category_breakdown(new_user()) == []


# ------------------------------------------------------------------ #
# GET /profile                                                        #
# ------------------------------------------------------------------ #

def test_profile_unauthenticated_redirects(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_profile_seed_user(client):
    client.post("/login", data=DEMO)
    resp = client.get("/profile")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "Demo User" in html
    assert "demo@spendly.com" in html
    assert "₹" in html
    assert '<span class="profile-stat-value">₹1,484.24</span>' in html
    assert '<span class="profile-stat-value">8</span>' in html
    assert '<span class="profile-stat-value">Bills</span>' in html
    assert html.count('class="profile-row"') == 8
    assert html.count('class="profile-bar-row"') == 7

    days = sorted((e[0] for e in SEED_EXPENSES), reverse=True)
    positions = [html.index(seed_date(d)) for d in days]
    assert positions == sorted(positions)


def test_profile_new_user_empty_state(client, app):
    user_id = new_user()
    log_in_as(client, user_id, "Empty User")

    resp = client.get("/profile")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "Empty User" in html
    assert '<span class="profile-stat-value">₹0.00</span>' in html
    assert '<span class="profile-stat-value">0</span>' in html
    assert '<span class="profile-stat-value">—</span>' in html
    assert html.count("No expenses yet.") == 2
    assert 'class="profile-bar-row"' not in html


def test_profile_shows_only_own_expenses(client, app):
    other_id = new_user(email="other@example.com", name="Other User")
    add_expense(other_id, 777.00, "Travel", 2, "Weekend trip")

    log_in_as(client, demo_id())
    demo_html = client.get("/profile").get_data(as_text=True)
    assert "Weekend trip" not in demo_html
    assert "₹1,484.24" in demo_html

    log_in_as(client, other_id, "Other User")
    other_html = client.get("/profile").get_data(as_text=True)
    assert "Weekend trip" in other_html
    assert "Monthly rent" not in other_html
    assert '<span class="profile-stat-value">₹777.00</span>' in other_html


def test_profile_limits_table_to_ten_rows(client, app):
    user_id = new_user()
    for day in range(1, 13):
        add_expense(user_id, 10.00, "Food", day, f"Item {day}")
    log_in_as(client, user_id, "Empty User")

    html = client.get("/profile").get_data(as_text=True)
    assert html.count('class="profile-row"') == 10
    assert '<span class="profile-stat-value">12</span>' in html
    assert '<span class="profile-stat-value">₹120.00</span>' in html


def test_profile_stale_session(client):
    log_in_as(client, 99999, "Ghost")
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    with client.session_transaction() as sess:
        assert "user_id" not in sess

    page = client.get(resp.headers["Location"])
    assert "Please sign in to view your profile." in page.get_data(as_text=True)
