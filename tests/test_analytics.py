import re
from pathlib import Path

import pytest

from database.db import get_user_by_email

ROOT = Path(__file__).resolve().parent.parent
DEMO = {"email": "demo@spendly.com", "password": "demo123"}
FLASH = "Please sign in to view analytics."
ANALYTICS_LINK_RE = re.compile(r'<a\s[^>]*href="/analytics"[^>]*>')


def log_in(client):
    """Put the demo user in the session without going through POST /login."""
    user = get_user_by_email(DEMO["email"])
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["name"]


def get_analytics_html(client):
    log_in(client)
    resp = client.get("/analytics")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def analytics_link_tag(html):
    match = ANALYTICS_LINK_RE.search(html)
    assert match, "Expected an Analytics link in the navbar"
    return match.group(0)


# ------------------------------------------------------------------ #
# Page content                                                        #
# ------------------------------------------------------------------ #

def test_analytics_logged_in_returns_200(client):
    log_in(client)
    resp = client.get("/analytics")
    assert resp.status_code == 200


def test_analytics_has_title(client):
    html = get_analytics_html(client)
    assert "<title>Analytics — Spendly</title>" in html


def test_analytics_shows_coming_soon(client):
    html = get_analytics_html(client)
    assert "Coming soon" in html


def test_analytics_links_stylesheet(client):
    html = get_analytics_html(client)
    assert "/static/css/analytics.css" in html


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_analytics_logged_out_redirects_to_login(client):
    resp = client.get("/analytics")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_analytics_logged_out_flash_shown_after_redirect(client):
    resp = client.get("/analytics")
    page = client.get(resp.headers["Location"])
    html = page.get_data(as_text=True)
    assert re.search(r'class="auth-success"[^>]*>[^<]*' + re.escape(FLASH), html), (
        "Expected flash inside an auth-success element"
    )


def test_analytics_stale_session_redirects_with_flash(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999999
        sess["user_name"] = "Ghost"
    resp = client.get("/analytics")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    page = client.get(resp.headers["Location"])
    assert FLASH in page.get_data(as_text=True)


def test_analytics_stale_session_is_cleared(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999999
        sess["user_name"] = "Ghost"
    client.get("/analytics")
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "user_name" not in sess


# ------------------------------------------------------------------ #
# Navbar                                                              #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("path", ["/", "/profile", "/analytics"])
def test_navbar_logged_in_shows_analytics_link(client, path):
    log_in(client)
    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert ANALYTICS_LINK_RE.search(html), f"Analytics link missing on {path}"
    assert ">Analytics</a>" in html


@pytest.mark.parametrize("path", ["/", "/login", "/register"])
def test_navbar_logged_out_hides_analytics_link(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert not ANALYTICS_LINK_RE.search(html)
    assert ">Analytics</a>" not in html


def test_navbar_analytics_link_active_on_analytics_page(client):
    tag = analytics_link_tag(get_analytics_html(client))
    assert "is-active" in tag
    assert 'aria-current="page"' in tag


def test_navbar_analytics_link_not_active_on_profile(client):
    log_in(client)
    html = client.get("/profile").get_data(as_text=True)
    tag = analytics_link_tag(html)
    assert "is-active" not in tag
    assert "aria-current" not in tag


def test_navbar_logged_in_keeps_sign_out_link(client):
    html = get_analytics_html(client)
    assert '<a href="/logout" class="nav-cta">Sign out</a>' in html


@pytest.mark.parametrize("path", ["/", "/login", "/register"])
def test_navbar_logged_out_keeps_sign_in_and_get_started(client, path):
    html = client.get(path).get_data(as_text=True)
    assert ">Sign in</a>" in html
    assert ">Get started</a>" in html


# ------------------------------------------------------------------ #
# Quality constraints                                                 #
# ------------------------------------------------------------------ #

def test_analytics_no_inline_styles_or_style_tags(client):
    html = get_analytics_html(client)
    assert 'style="' not in html
    assert "<style" not in html


def test_analytics_no_hex_colours_in_css_or_template():
    hex_re = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    css = (ROOT / "static" / "css" / "analytics.css").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "analytics.html").read_text(encoding="utf-8")
    assert not hex_re.search(css), "Hex colour found in analytics.css"
    assert not hex_re.search(template), "Hex colour found in analytics.html"
    assert "<style" not in template
