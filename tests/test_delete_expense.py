"""Step 9: delete an expense at /expenses/<id>/delete (confirm on GET, delete on POST)."""
import re
from datetime import date
from pathlib import Path

import pytest

from app import format_short_date
from database.db import (
    create_expense,
    create_user,
    delete_expense,
    get_category_breakdown,
    get_db,
    get_user_by_email,
)

ROOT = Path(__file__).resolve().parent.parent
DEMO_EMAIL = "demo@spendly.com"
PROFILE_URL = "/profile"
LOGIN_URL = "/login"

MSG_LOGIN = "Please sign in to delete an expense."
MSG_DELETED = "Expense deleted."
HUGE_ID = 99999999999999999999

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
TOKEN_RE = re.compile(r'<input type="hidden" name="csrf_token" value="([^"]+)">')


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def log_in(client, email=DEMO_EMAIL):
    user = get_user_by_email(email)
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["name"]
    return user


def demo_id():
    return get_user_by_email(DEMO_EMAIL)["id"]


def delete_url(expense_id):
    return f"/expenses/{expense_id}/delete"


def count_expenses():
    conn = get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    finally:
        conn.close()


def expense_row(expense_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def demo_expense_id(description):
    """id of a demo seed expense by description (None -> the NULL-description row)."""
    conn = get_db()
    try:
        if description is None:
            row = conn.execute(
                "SELECT id FROM expenses WHERE user_id = ? AND description IS NULL",
                (demo_id(),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM expenses WHERE user_id = ? AND description = ?",
                (demo_id(), description),
            ).fetchone()
        return row["id"]
    finally:
        conn.close()


def demo_expense_ids():
    conn = get_db()
    try:
        rows = conn.execute("SELECT id FROM expenses WHERE user_id = ?", (demo_id(),)).fetchall()
        return [r["id"] for r in rows]
    finally:
        conn.close()


def other_user_expense():
    other_id = create_user("Other Person", "other@example.com", "otherpass1")
    return other_id, create_expense(other_id, 42.0, "Food", date.today().isoformat(), "Other lunch")


def flash_present(html, message):
    return re.search(r'class="auth-success"[^>]*>[^<]*' + re.escape(message), html) is not None


def stat_count_present(html, n):
    return f'<span class="profile-stat-value">{n}</span>' in html


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

def test_get_logged_out_redirects_to_login_with_flash(client):
    resp = client.get(delete_url(1))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    page = client.get(LOGIN_URL).get_data(as_text=True)
    assert flash_present(page, MSG_LOGIN), "expected sign-in flash on the login page"


def test_post_logged_out_redirects_and_deletes_nothing(client):
    before = count_expenses()
    eid = demo_expense_id("Groceries")
    resp = client.post(delete_url(eid))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    assert count_expenses() == before
    assert expense_row(eid) is not None


@pytest.mark.parametrize("method", ["get", "post"])
def test_logged_out_nonexistent_id_redirects_not_404(client, method):
    resp = getattr(client, method)(delete_url(999999))
    assert resp.status_code == 302, "logged-out visitors must not learn which ids exist"
    assert resp.headers["Location"].endswith(LOGIN_URL)


@pytest.mark.parametrize("method", ["get", "post"])
def test_stale_session_user_redirects_to_login(client, method):
    with client.session_transaction() as sess:
        sess["user_id"] = 987654
        sess["user_name"] = "Ghost"
    before = count_expenses()
    resp = getattr(client, method)(delete_url(demo_expense_id("Groceries")))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    assert count_expenses() == before


# ------------------------------------------------------------------ #
# GET: confirmation page                                              #
# ------------------------------------------------------------------ #

class TestConfirmationPage:
    def test_renders_expense_details(self, client):
        log_in(client)
        eid = demo_expense_id("Groceries")
        row = expense_row(eid)
        resp = client.get(delete_url(eid))
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "<title>Delete expense — Spendly</title>" in html
        assert "Delete expense" in html
        assert "This permanently removes the expense. This can&#39;t be undone." in html or \
            "This permanently removes the expense. This can't be undone." in html
        assert '<dl class="expense-summary">' in html
        assert format_short_date(row["date"]) in html
        assert "Groceries" in html
        assert "Food" in html
        assert "₹45.50" in html

    def test_form_posts_to_same_url_with_csrf_and_danger_button(self, client):
        log_in(client)
        eid = demo_expense_id("Groceries")
        html = client.get(delete_url(eid)).get_data(as_text=True)
        assert re.search(r'<form[^>]*method="post"[^>]*action="' + re.escape(delete_url(eid)) + '"', html) \
            or re.search(r'<form[^>]*action="' + re.escape(delete_url(eid)) + r'"[^>]*method="post"', html)
        assert 'name="csrf_token"' in html
        button = re.search(r"<button[^>]*>\s*Delete expense\s*</button>", html)
        assert button, "expected a 'Delete expense' submit button"
        assert "expense-danger" in button.group(0)

    def test_cancel_link_points_to_profile(self, client):
        log_in(client)
        html = client.get(delete_url(demo_expense_id("Groceries"))).get_data(as_text=True)
        assert re.search(r'<a[^>]*href="' + re.escape(PROFILE_URL) + r'"[^>]*>\s*Cancel\s*</a>', html)

    def test_null_description_shows_dash_not_none(self, client):
        log_in(client)
        html = client.get(delete_url(demo_expense_id(None))).get_data(as_text=True)
        assert "—" in html
        assert "None" not in html

    def test_get_does_not_delete(self, client):
        log_in(client)
        eid = demo_expense_id("Groceries")
        before = count_expenses()
        client.get(delete_url(eid))
        assert count_expenses() == before
        assert expense_row(eid) is not None

    def test_cancel_returns_to_profile_and_expense_still_listed(self, client):
        log_in(client)
        client.get(delete_url(demo_expense_id("Groceries")))
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert "Groceries" in html

    def test_script_description_is_escaped(self, client):
        user = log_in(client)
        eid = create_expense(user["id"], 5.0, "Other", date.today().isoformat(),
                             "<script>alert(1)</script>")
        html = client.get(delete_url(eid)).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ------------------------------------------------------------------ #
# POST: delete                                                        #
# ------------------------------------------------------------------ #

class TestDelete:
    def test_post_deletes_flashes_and_redirects(self, client):
        log_in(client)
        eid = demo_expense_id("Groceries")
        before = count_expenses()
        resp = client.post(delete_url(eid))
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(PROFILE_URL)
        assert expense_row(eid) is None
        assert count_expenses() == before - 1
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert flash_present(html, MSG_DELETED)

    def test_profile_totals_update_after_delete(self, client):
        log_in(client)
        page = client.get(PROFILE_URL).get_data(as_text=True)
        assert "₹1,484.24" in page
        assert stat_count_present(page, 8)
        client.post(delete_url(demo_expense_id("Groceries")))
        page = client.get(PROFILE_URL).get_data(as_text=True)
        assert "₹1,438.74" in page
        assert "₹1,484.24" not in page
        assert stat_count_present(page, 7)

    def test_follow_redirect_then_refresh_does_not_resubmit(self, client):
        log_in(client)
        before = count_expenses()
        resp = client.post(delete_url(demo_expense_id("Groceries")), follow_redirects=True)
        assert resp.status_code == 200
        assert flash_present(resp.get_data(as_text=True), MSG_DELETED)
        refreshed = client.get(PROFILE_URL)
        assert refreshed.status_code == 200
        assert not flash_present(refreshed.get_data(as_text=True), MSG_DELETED)
        assert count_expenses() == before - 1

    def test_deleting_only_one_row(self, client):
        log_in(client)
        eid = demo_expense_id("Groceries")
        others = [i for i in demo_expense_ids() if i != eid]
        client.post(delete_url(eid))
        assert sorted(demo_expense_ids()) == sorted(others)

    def test_delete_all_shows_empty_state(self, client):
        log_in(client)
        for eid in demo_expense_ids():
            assert client.post(delete_url(eid)).status_code == 302
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert "No expenses yet." in html
        assert "₹0.00" in html

    def test_deleting_only_health_expense_removes_category(self, client):
        log_in(client)
        names = [c["name"] for c in get_category_breakdown(demo_id())]
        assert "Health" in names
        client.post(delete_url(demo_expense_id("Pharmacy")))
        breakdown = get_category_breakdown(demo_id())
        assert "Health" not in [c["name"] for c in breakdown]
        assert breakdown, "other categories should remain"
        assert sum(c["pct"] for c in breakdown) == 100

    def test_second_post_for_same_id_is_404(self, client):
        log_in(client)
        eid = demo_expense_id("Groceries")
        assert client.post(delete_url(eid)).status_code == 302
        assert client.post(delete_url(eid)).status_code == 404

    def test_forged_user_id_field_is_ignored(self, client):
        log_in(client)
        other_id, other_eid = other_user_expense()
        eid = demo_expense_id("Groceries")
        client.post(delete_url(eid), data={"user_id": str(other_id)})
        assert expense_row(eid) is None, "session user's own expense should be deleted"
        resp = client.post(delete_url(other_eid), data={"user_id": str(other_id)})
        assert resp.status_code == 404
        assert expense_row(other_eid) is not None


# ------------------------------------------------------------------ #
# 404 handling                                                        #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("bad_id", [999999, HUGE_ID])
def test_missing_or_huge_id_returns_404_and_deletes_nothing(client, method, bad_id):
    log_in(client)
    before = count_expenses()
    resp = getattr(client, method)(delete_url(bad_id))
    assert resp.status_code == 404
    assert count_expenses() == before


@pytest.mark.parametrize("method", ["get", "post"])
def test_other_users_expense_returns_404_and_survives(client, method):
    log_in(client)
    _, other_eid = other_user_expense()
    before = count_expenses()
    resp = getattr(client, method)(delete_url(other_eid))
    assert resp.status_code == 404
    assert expense_row(other_eid) is not None
    assert count_expenses() == before


# ------------------------------------------------------------------ #
# DB helper                                                           #
# ------------------------------------------------------------------ #

class TestDeleteHelper:
    def test_returns_true_and_removes_row(self, app):
        eid = demo_expense_id("Groceries")
        assert delete_expense(eid, demo_id()) is True
        assert expense_row(eid) is None

    def test_returns_false_for_wrong_user_and_keeps_row(self, app):
        other_id, other_eid = other_user_expense()
        assert delete_expense(other_eid, demo_id()) is False
        assert expense_row(other_eid) is not None

    def test_returns_false_for_missing_and_repeat(self, app):
        eid = demo_expense_id("Groceries")
        assert delete_expense(999999, demo_id()) is False
        assert delete_expense(eid, demo_id()) is True
        assert delete_expense(eid, demo_id()) is False

    def test_returns_false_for_huge_id(self, app):
        before = count_expenses()
        assert delete_expense(HUGE_ID, demo_id()) is False
        assert count_expenses() == before

    def test_deletes_exactly_one_row(self, app):
        before = count_expenses()
        delete_expense(demo_expense_id("Groceries"), demo_id())
        assert count_expenses() == before - 1


# ------------------------------------------------------------------ #
# Profile links                                                       #
# ------------------------------------------------------------------ #

class TestProfileLinks:
    def test_every_row_has_edit_and_delete_link(self, client):
        log_in(client)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        ids = demo_expense_ids()
        for eid in ids:
            assert f'href="/expenses/{eid}/edit"' in html, f"missing Edit link for {eid}"
            assert f'href="/expenses/{eid}/delete"' in html, f"missing Delete link for {eid}"
        assert html.count('class="profile-delete-link"') == len(ids)

    def test_delete_link_follows_edit_link_with_aria_label(self, client):
        log_in(client)
        eid = demo_expense_id("Groceries")
        row = expense_row(eid)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        label = f"Delete Groceries on {row['date']}"
        pattern = (
            r'href="/expenses/' + str(eid) + r'/edit"[^>]*>\s*Edit\s*</a>\s*'
            r'<a href="/expenses/' + str(eid) + r'/delete" class="profile-delete-link" '
            r'aria-label="' + re.escape(label) + r'">\s*Delete\s*</a>'
        )
        assert re.search(pattern, html), "Delete link should directly follow the Edit link"

    def test_aria_label_falls_back_to_category_when_no_description(self, client):
        log_in(client)
        eid = demo_expense_id(None)
        row = expense_row(eid)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert f'aria-label="Delete {row["category"]} on {row["date"]}"' in html


# ------------------------------------------------------------------ #
# CSRF                                                                #
# ------------------------------------------------------------------ #

@pytest.fixture
def csrf_app(app, monkeypatch):
    monkeypatch.setitem(app.config, "CSRF_ENABLED", True)
    return app


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


def token_from(client, url):
    html = client.get(url).get_data(as_text=True)
    match = TOKEN_RE.search(html)
    assert match, f"no CSRF field on {url}"
    return match.group(1)


class TestCsrf:
    def test_post_without_token_is_400_and_deletes_nothing(self, csrf_client):
        log_in(csrf_client)
        eid = demo_expense_id("Groceries")
        before = count_expenses()
        resp = csrf_client.post(delete_url(eid))
        assert resp.status_code == 400
        assert count_expenses() == before
        assert expense_row(eid) is not None

    def test_post_with_wrong_token_is_400_and_deletes_nothing(self, csrf_client):
        log_in(csrf_client)
        eid = demo_expense_id("Groceries")
        before = count_expenses()
        resp = csrf_client.post(delete_url(eid), data={"csrf_token": "not-the-token"})
        assert resp.status_code == 400
        assert count_expenses() == before

    def test_post_with_valid_token_deletes(self, csrf_client):
        log_in(csrf_client)
        eid = demo_expense_id("Groceries")
        token = token_from(csrf_client, delete_url(eid))
        resp = csrf_client.post(delete_url(eid), data={"csrf_token": token})
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(PROFILE_URL)
        assert expense_row(eid) is None


# ------------------------------------------------------------------ #
# Template and CSS hygiene                                            #
# ------------------------------------------------------------------ #

def test_template_extends_base_and_has_no_inline_styles_or_scripts():
    source = (ROOT / "templates" / "delete_expense.html").read_text(encoding="utf-8")
    assert '{% extends "base.html" %}' in source
    assert not HEX_RE.search(source)
    for forbidden in ("style=", "<style", "|safe", "<script"):
        assert forbidden not in source, f"template must not contain {forbidden!r}"


def test_expenses_css_defines_summary_and_danger_without_hex():
    css = (ROOT / "static" / "css" / "expenses.css").read_text(encoding="utf-8")
    assert ".expense-summary" in css
    assert ".expense-danger" in css
    assert "var(--danger)" in css
    assert not HEX_RE.search(css)


def test_profile_css_defines_delete_link_without_hex():
    css = (ROOT / "static" / "css" / "profile.css").read_text(encoding="utf-8")
    assert ".profile-delete-link" in css
    assert "var(--danger-light)" in css
    assert not HEX_RE.search(css)
