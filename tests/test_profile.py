import re
from datetime import date, datetime
from pathlib import Path

from app import format_inr
from database.db import SEED_EXPENSES, get_user_by_email

ROOT = Path(__file__).resolve().parent.parent
DEMO = {"email": "demo@spendly.com", "password": "demo123"}

# Seed data per category, largest first, with rounded share of 1484.24.
SEED_BREAKDOWN = [
    ("Bills", 81),
    ("Shopping", 6),
    ("Food", 4),
    ("Health", 4),
    ("Transport", 2),
    ("Entertainment", 2),
    ("Other", 1),
]


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
# Rendered content (seed data)                                        #
# ------------------------------------------------------------------ #

def test_profile_user_card(client):
    html = get_profile_html(client)
    user = get_user_by_email(DEMO["email"])
    member_since = datetime.strptime(
        user["created_at"], "%Y-%m-%d %H:%M:%S"
    ).strftime("%B %Y")

    assert "Demo User" in html
    assert "demo@spendly.com" in html
    assert f"Member since {member_since}" in html
    assert '<div class="profile-avatar" aria-hidden="true">DU</div>' in html


def test_profile_summary_stats(client):
    html = get_profile_html(client)
    assert html.count('class="profile-card profile-stat"') == 3
    for label in ("Total spent", "Transactions", "Top category"):
        assert label in html
    assert '<span class="profile-stat-value">₹1,484.24</span>' in html
    assert '<span class="profile-stat-value">8</span>' in html
    assert '<span class="profile-stat-value">Bills</span>' in html


def test_profile_transaction_table(client):
    html = get_profile_html(client)
    assert html.count('class="profile-row"') == len(SEED_EXPENSES)
    today = date.today()
    for day, amount, _category, description in SEED_EXPENSES:
        assert today.replace(day=day).isoformat() in html
        assert format_inr(amount) in html
        if description:
            assert description in html
    assert '<span class="profile-empty">—</span>' in html
    assert '<span class="profile-badge">Food</span>' in html


def test_profile_category_breakdown(client):
    html = get_profile_html(client)
    assert html.count('class="profile-bar-row"') == len(SEED_BREAKDOWN)
    for name, pct in SEED_BREAKDOWN:
        assert f'<span class="profile-bar-name">{name}</span>' in html
        assert f'<rect class="profile-bar" width="{pct}%"' in html


def test_no_sample_data_pill(client):
    html = get_profile_html(client)
    assert "Sample data" not in html
    assert "profile-pill" not in html


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
# Static files                                                        #
# ------------------------------------------------------------------ #

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
