import re
from collections import defaultdict
from pathlib import Path

from app import (
    PROFILE_CATEGORIES,
    PROFILE_SUMMARY,
    PROFILE_TRANSACTIONS,
    PROFILE_USER,
    format_inr,
)
from database.db import get_user_by_email

ROOT = Path(__file__).resolve().parent.parent
DEMO = {"email": "demo@spendly.com", "password": "demo123"}


def log_in(client):
    """Put the demo user in the session without going through POST /login."""
    user = get_user_by_email(DEMO["email"])
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["name"]


def get_profile_html(client):
    log_in(client)
    resp = client.get("/profile")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_profile_logged_out_redirects_with_flash(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    page = client.get(resp.headers["Location"])
    html = page.get_data(as_text=True)
    assert 'class="auth-success"' in html
    assert "Please sign in to view your profile." in html


def test_login_then_profile_renders(client):
    resp = client.post("/login", data=DEMO)
    assert resp.headers["Location"].endswith("/profile")

    page = client.get("/profile")
    assert page.status_code == 200
    assert "profile-user" in page.get_data(as_text=True)


# ------------------------------------------------------------------ #
# Rendered content                                                    #
# ------------------------------------------------------------------ #

def test_profile_user_card(client):
    html = get_profile_html(client)
    assert PROFILE_USER["name"] in html
    assert PROFILE_USER["email"] in html
    assert f"Member since {PROFILE_USER['member_since']}" in html
    assert '<div class="profile-avatar" aria-hidden="true">DU</div>' in html


def test_profile_summary_stats(client):
    html = get_profile_html(client)
    assert html.count('class="profile-card profile-stat"') == 3
    for label in ("Total spent", "Transactions", "Top category"):
        assert label in html
    assert '<span class="profile-stat-value">₹21,020.00</span>' in html
    assert '<span class="profile-stat-value">8</span>' in html
    assert '<span class="profile-stat-value">Bills</span>' in html


def test_profile_transaction_table(client):
    html = get_profile_html(client)
    assert html.count('class="profile-row"') == len(PROFILE_TRANSACTIONS)
    for tx in PROFILE_TRANSACTIONS:
        assert tx["date"] in html
        assert format_inr(tx["amount"]) in html
        if tx["description"]:
            assert tx["description"] in html
    assert '<span class="profile-empty">—</span>' in html
    assert '<span class="profile-badge">Food</span>' in html


def test_profile_category_breakdown(client):
    html = get_profile_html(client)
    assert html.count('class="profile-bar-row"') == len(PROFILE_CATEGORIES)
    for c in PROFILE_CATEGORIES:
        assert f'<span class="profile-bar-name">{c["name"]}</span>' in html
        assert f'<rect class="profile-bar" width="{c["percent"]}%"' in html


def test_profile_navbar_logged_in(client):
    html = get_profile_html(client)
    assert "Hi, Demo User" in html
    assert "Sign out" in html


def test_profile_loads_assets(client):
    html = get_profile_html(client)
    assert "/static/css/profile.css" in html
    assert "lucide@0.460.0" in html
    assert "lucide@latest" not in html
    assert html.index("lucide@0.460.0") < html.index("/static/js/main.js")
    assert 'data-lucide="wallet"' in html


def test_no_inline_styles(client):
    html = get_profile_html(client)
    assert 'style="' not in html


# ------------------------------------------------------------------ #
# Placeholder data and static files                                   #
# ------------------------------------------------------------------ #

def test_placeholder_data_consistent():
    total = PROFILE_SUMMARY["total_spent"]
    assert sum(tx["amount"] for tx in PROFILE_TRANSACTIONS) == total
    assert sum(c["amount"] for c in PROFILE_CATEGORIES) == total
    assert PROFILE_SUMMARY["transaction_count"] == len(PROFILE_TRANSACTIONS)
    assert PROFILE_SUMMARY["top_category"] == PROFILE_CATEGORIES[0]["name"]

    amounts = [c["amount"] for c in PROFILE_CATEGORIES]
    assert amounts == sorted(amounts, reverse=True)
    for c in PROFILE_CATEGORIES:
        assert c["percent"] == round(c["amount"] / total * 100)
    assert abs(sum(c["percent"] for c in PROFILE_CATEGORIES) - 100) <= 1

    by_category = defaultdict(float)
    for tx in PROFILE_TRANSACTIONS:
        by_category[tx["category"]] += tx["amount"]
    assert by_category == {c["name"]: c["amount"] for c in PROFILE_CATEGORIES}

    dates = [tx["date"] for tx in PROFILE_TRANSACTIONS]
    assert dates == sorted(dates, reverse=True)
    assert any(tx["description"] is None for tx in PROFILE_TRANSACTIONS)


def test_no_hex_or_style_tags():
    hex_re = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    css = (ROOT / "static" / "css" / "profile.css").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "profile.html").read_text(encoding="utf-8")
    assert not hex_re.search(css)
    assert not hex_re.search(template)
    assert "<style" not in template


def test_inr_filter():
    assert format_inr(21020) == "₹21,020.00"
    assert format_inr(500) == "₹500.00"
