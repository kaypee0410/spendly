"""Step 8: edit an expense at /expenses/<id>/edit."""
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

import app as app_module
from app import _expense_form_values, validate_expense
from database.db import (
    create_expense,
    create_user,
    get_category_breakdown,
    get_db,
    get_expense_by_id,
    get_recent_transactions,
    get_user_by_email,
    update_expense,
)

ROOT = Path(__file__).resolve().parent.parent
DEMO_EMAIL = "demo@spendly.com"
PROFILE_URL = "/profile"
LOGIN_URL = "/login"

CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]

MSG_LOGIN = "Please sign in to edit an expense."
MSG_UPDATED = "Expense updated."
MSG_AMOUNT_REQUIRED = "Please enter an amount."
MSG_AMOUNT_INVALID = "Please enter a valid amount."
MSG_AMOUNT_ZERO = "Amount must be greater than zero."
MSG_AMOUNT_DECIMALS = "Amount can have at most 2 decimal places."
MSG_AMOUNT_LARGE = "Amount is too large."
MSG_CATEGORY = "Please choose a category."
MSG_DATE_INVALID = "Please enter a valid date."
MSG_DATE_FUTURE = "Date cannot be in the future."
MSG_DESC_LONG = "Description must be 200 characters or fewer."

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
TODAY = date.today()


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


def iso(d):
    return d.isoformat()


def edit_url(expense_id):
    return f"/expenses/{expense_id}/edit"


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


def own_expense(date_iso, amount=10.0, category="Food", description="Mine", user_id=None):
    """Insert directly (no validation) so tests control the stored date."""
    return create_expense(user_id or demo_id(), amount, category, date_iso, description)


def other_user_expense():
    other_id = create_user("Other Person", "other@example.com", "otherpass1")
    return other_id, create_expense(other_id, 42.0, "Food", iso(TODAY), "Other lunch")


def form_from(row, **overrides):
    form = {
        "amount": f"{row['amount']:.2f}",
        "category": row["category"],
        "date": row["date"],
        "description": row["description"] or "",
    }
    form.update(overrides)
    return form


def flash_present(html, message):
    return re.search(r'class="auth-success"[^>]*>[^<]*' + re.escape(message), html) is not None


def error_present(html, message):
    return re.search(r'class="auth-error"[^>]*>\s*' + re.escape(message), html) is not None


def input_tag(html, name):
    match = re.search(r'<input[^>]*\bname="' + name + r'"[^>]*>', html)
    assert match, f"no input named {name}"
    return match.group(0)


def selected_options(html):
    return re.findall(r'<option value="([^"]*)"[^>]*\bselected\b', html)


@pytest.fixture
def groceries(app):
    return demo_expense_id("Groceries")


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

def test_get_logged_out_redirects_to_login_with_flash(client, groceries):
    resp = client.get(edit_url(groceries))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    html = client.get(LOGIN_URL).get_data(as_text=True)
    assert flash_present(html, MSG_LOGIN)


def test_post_logged_out_redirects_and_changes_nothing(client, groceries):
    before = expense_row(groceries)
    resp = client.post(edit_url(groceries), data=form_from(before, amount="1.00"))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    assert expense_row(groceries) == before


@pytest.mark.parametrize("method", ["get", "post"])
def test_logged_out_missing_id_redirects_not_404(client, method):
    resp = getattr(client, method)(edit_url(999999))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)


@pytest.mark.parametrize("method", ["get", "post"])
def test_stale_session_redirects_and_clears_session(client, groceries, method):
    with client.session_transaction() as sess:
        sess["user_id"] = 999999
        sess["user_name"] = "Ghost"
    before = expense_row(groceries)
    kwargs = {"data": form_from(before, amount="1.00")} if method == "post" else {}
    resp = getattr(client, method)(edit_url(groceries), **kwargs)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    assert expense_row(groceries) == before
    with client.session_transaction() as sess:
        assert "user_id" not in sess


# ------------------------------------------------------------------ #
# Profile table Edit links                                            #
# ------------------------------------------------------------------ #

class TestProfileEditLinks:
    def test_every_row_has_edit_link_to_its_id(self, client):
        log_in(client)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        hrefs = re.findall(r'<a href="(/expenses/\d+/edit)" class="profile-edit-link"', html)
        ids = [r["id"] for r in get_recent_transactions(demo_id())]
        assert len(hrefs) == 8
        assert set(hrefs) == {edit_url(i) for i in ids}

    def test_aria_labels_use_description_or_category(self, client):
        log_in(client)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        groceries = expense_row(demo_expense_id("Groceries"))
        no_desc = expense_row(demo_expense_id(None))
        assert f'aria-label="Edit Groceries on {groceries["date"]}"' in html
        assert f'aria-label="Edit Other on {no_desc["date"]}"' in html

    def test_actions_header_is_visually_hidden(self, client):
        log_in(client)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert '<span class="visually-hidden">Actions</span>' in html

    def test_rows_keep_exact_profile_row_class(self, client):
        log_in(client)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert html.count('class="profile-row"') == 8

    def test_empty_state_spans_five_columns(self, client, app):
        create_user("New Person", "new@example.com", "newpass123")
        log_in(client, "new@example.com")
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert 'colspan="5"' in html
        assert 'colspan="4"' not in html

    def test_filtered_empty_state_spans_five_columns(self, client):
        log_in(client)
        html = client.get(PROFILE_URL + "?start_date=1999-01-01&end_date=1999-01-02").get_data(as_text=True)
        assert 'colspan="5"' in html
        assert "No expenses in this period." in html


# ------------------------------------------------------------------ #
# GET form                                                            #
# ------------------------------------------------------------------ #

class TestEditForm:
    def test_groceries_form_prefilled(self, client, groceries):
        log_in(client)
        resp = client.get(edit_url(groceries))
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        row = expense_row(groceries)
        assert "Edit expense" in html
        assert "Update the details of this expense." in html
        assert re.search(r'<form method="post" action="' + re.escape(edit_url(groceries)) + '"', html)
        assert 'value="45.50"' in input_tag(html, "amount")
        assert selected_options(html) == ["Food"]
        assert f'value="{row["date"]}"' in input_tag(html, "date")
        assert 'value="Groceries"' in input_tag(html, "description")
        assert "Save changes" in html
        assert re.search(r'<a href="/profile"[^>]*>\s*Cancel', html)
        assert "css/expenses.css" in html
        assert "auth-error" not in html

    def test_category_select_has_seven_options_no_placeholder(self, client, groceries):
        log_in(client)
        html = client.get(edit_url(groceries)).get_data(as_text=True)
        assert re.findall(r'<option value="([^"]+)"', html) == CATEGORIES
        assert "Choose a category" not in html

    def test_null_description_renders_empty(self, client):
        log_in(client)
        html = client.get(edit_url(demo_expense_id(None))).get_data(as_text=True)
        tag = input_tag(html, "description")
        assert 'value=""' in tag
        assert "None" not in tag

    def test_whole_amount_shows_two_decimals(self, client):
        log_in(client)
        html = client.get(edit_url(demo_expense_id("Monthly rent"))).get_data(as_text=True)
        assert 'value="1200.00"' in input_tag(html, "amount")

    def test_description_maxlength(self, client, groceries):
        log_in(client)
        html = client.get(edit_url(groceries)).get_data(as_text=True)
        assert 'maxlength="200"' in input_tag(html, "description")

    def test_date_max_is_today_for_past_expense(self, client):
        log_in(client)
        eid = own_expense(iso(TODAY - timedelta(days=3)))
        html = client.get(edit_url(eid)).get_data(as_text=True)
        assert f'max="{iso(TODAY)}"' in input_tag(html, "date")

    def test_date_max_is_stored_date_for_future_expense(self, client):
        log_in(client)
        future = iso(TODAY + timedelta(days=5))
        eid = own_expense(future)
        html = client.get(edit_url(eid)).get_data(as_text=True)
        assert f'max="{future}"' in input_tag(html, "date")

    def test_legacy_category_shows_selected_placeholder(self, client):
        log_in(client)
        eid = own_expense(iso(TODAY), category="Misc")
        html = client.get(edit_url(eid)).get_data(as_text=True)
        assert re.search(r'<option value="" disabled selected>Choose a category</option>', html)
        assert selected_options(html) == [""]

    def test_no_inline_styles(self, client, groceries):
        log_in(client)
        html = client.get(edit_url(groceries)).get_data(as_text=True)
        assert 'style="' not in html


# ------------------------------------------------------------------ #
# Successful edit                                                     #
# ------------------------------------------------------------------ #

class TestSuccessfulEdit:
    def test_redirects_flashes_and_updates_totals(self, client, groceries):
        log_in(client)
        resp = client.post(edit_url(groceries), data=form_from(expense_row(groceries), amount="50.00"))
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(PROFILE_URL)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert flash_present(html, MSG_UPDATED)
        assert "₹1,488.74" in html
        assert "₹1,484.24" not in html
        assert html.count('class="profile-row"') == 8
        assert "₹50.00" in html

    def test_row_updated_identity_fields_unchanged(self, client, groceries):
        log_in(client)
        before = expense_row(groceries)
        count = count_expenses()
        client.post(edit_url(groceries), data=form_from(before, amount="50.00"))
        after = expense_row(groceries)
        assert after["amount"] == pytest.approx(50.0)
        for key in ("id", "user_id", "created_at", "category", "date", "description"):
            assert after[key] == before[key]
        assert count_expenses() == count

    def test_category_change_moves_breakdown(self, client, groceries):
        log_in(client)
        client.post(edit_url(groceries), data=form_from(expense_row(groceries), category="Health"))
        amounts = {c["name"]: c["amount"] for c in get_category_breakdown(demo_id())}
        assert amounts["Food"] == pytest.approx(18.75)
        assert amounts["Health"] == pytest.approx(105.50)

    def test_date_change_moves_order(self, client, groceries):
        log_in(client)
        old = iso(TODAY - timedelta(days=400))
        resp = client.post(edit_url(groceries), data=form_from(expense_row(groceries), date=old))
        assert resp.status_code == 302
        rows = get_recent_transactions(demo_id())
        assert rows[-1]["id"] == groceries
        assert rows[-1]["date"] == old

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_description_stored_as_null(self, client, groceries, blank):
        log_in(client)
        resp = client.post(edit_url(groceries), data=form_from(expense_row(groceries), description=blank))
        assert resp.status_code == 302
        assert expense_row(groceries)["description"] is None

    def test_missing_description_field_stores_null(self, client, groceries):
        log_in(client)
        form = form_from(expense_row(groceries))
        del form["description"]
        assert client.post(edit_url(groceries), data=form).status_code == 302
        assert expense_row(groceries)["description"] is None

    def test_description_is_stripped(self, client, groceries):
        log_in(client)
        client.post(edit_url(groceries), data=form_from(expense_row(groceries), description="  Veg  "))
        assert expense_row(groceries)["description"] == "Veg"

    def test_sql_injection_in_description_stored_literally(self, client, groceries):
        log_in(client)
        payload = "x'); DROP TABLE expenses;--"
        count = count_expenses()
        resp = client.post(edit_url(groceries), data=form_from(expense_row(groceries), description=payload))
        assert resp.status_code == 302
        assert expense_row(groceries)["description"] == payload
        assert count_expenses() == count

    @pytest.mark.parametrize("field, value", [
        ("description", "x" * 200),  # max length is inclusive
        ("amount", "10000000"),      # max amount is inclusive
        ("date", iso(TODAY)),        # today is not "the future"
    ])
    def test_boundary_values_accepted(self, client, groceries, field, value):
        log_in(client)
        resp = client.post(edit_url(groceries), data=form_from(expense_row(groceries), **{field: value}))
        assert resp.status_code == 302

    def test_unchanged_resubmit_succeeds(self, client, groceries):
        log_in(client)
        before = expense_row(groceries)
        resp = client.post(edit_url(groceries), data=form_from(before))
        assert resp.status_code == 302
        assert expense_row(groceries) == before

    def test_refresh_profile_does_not_resubmit(self, client, groceries):
        log_in(client)
        client.post(edit_url(groceries), data=form_from(expense_row(groceries), amount="50.00"))
        client.get(PROFILE_URL)
        after = expense_row(groceries)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert expense_row(groceries) == after
        assert not flash_present(html, MSG_UPDATED)


# ------------------------------------------------------------------ #
# Validation                                                          #
# ------------------------------------------------------------------ #

AMOUNT_ERRORS = [
    ("", MSG_AMOUNT_REQUIRED),
    ("0", MSG_AMOUNT_ZERO),
    ("-5", MSG_AMOUNT_ZERO),
    ("abc", MSG_AMOUNT_INVALID),
    ("nan", MSG_AMOUNT_INVALID),
    ("12.345", MSG_AMOUNT_DECIMALS),
    ("20000000", MSG_AMOUNT_LARGE),
]


class TestValidation:
    @pytest.mark.parametrize("amount, message", AMOUNT_ERRORS)
    def test_bad_amount_400_keeps_values_row_unchanged(self, client, groceries, amount, message):
        log_in(client)
        before = expense_row(groceries)
        form = form_from(before, amount=amount, description="Keep me")
        resp = client.post(edit_url(groceries), data=form)
        assert resp.status_code == 400
        html = resp.get_data(as_text=True)
        assert error_present(html, message)
        assert f'value="{amount}"' in input_tag(html, "amount")
        assert 'value="Keep me"' in input_tag(html, "description")
        assert selected_options(html) == ["Food"]
        assert expense_row(groceries) == before

    @pytest.mark.parametrize("category", ["Misc", "food", ""])
    def test_bad_category(self, client, groceries, category):
        log_in(client)
        before = expense_row(groceries)
        resp = client.post(edit_url(groceries), data=form_from(before, category=category))
        assert resp.status_code == 400
        assert error_present(resp.get_data(as_text=True), MSG_CATEGORY)
        assert expense_row(groceries) == before

    def test_missing_category_field(self, client, groceries):
        log_in(client)
        before = expense_row(groceries)
        form = form_from(before)
        del form["category"]
        resp = client.post(edit_url(groceries), data=form)
        assert resp.status_code == 400
        assert error_present(resp.get_data(as_text=True), MSG_CATEGORY)

    @pytest.mark.parametrize("bad_date", ["2026-13-01", "", "20261101", "2026-1-1", "yesterday"])
    def test_malformed_date(self, client, groceries, bad_date):
        log_in(client)
        before = expense_row(groceries)
        resp = client.post(edit_url(groceries), data=form_from(before, date=bad_date))
        assert resp.status_code == 400
        assert error_present(resp.get_data(as_text=True), MSG_DATE_INVALID)
        assert expense_row(groceries) == before

    @pytest.mark.parametrize("new_date", [iso(TODAY + timedelta(days=1)), "2999-01-01"])
    def test_move_to_new_future_date_rejected(self, client, new_date):
        log_in(client)
        eid = own_expense(iso(TODAY - timedelta(days=1)))
        before = expense_row(eid)
        resp = client.post(edit_url(eid), data=form_from(before, date=new_date))
        assert resp.status_code == 400
        assert error_present(resp.get_data(as_text=True), MSG_DATE_FUTURE)
        assert expense_row(eid) == before

    def test_description_too_long(self, client, groceries):
        log_in(client)
        before = expense_row(groceries)
        resp = client.post(edit_url(groceries), data=form_from(before, description="x" * 201))
        assert resp.status_code == 400
        assert error_present(resp.get_data(as_text=True), MSG_DESC_LONG)
        assert expense_row(groceries) == before

    @pytest.mark.parametrize("overrides, shown, hidden", [
        ({"amount": "abc", "category": "Nope", "date": "bad"}, MSG_AMOUNT_INVALID, MSG_CATEGORY),
        ({"category": "Nope", "date": "bad"}, MSG_CATEGORY, MSG_DATE_INVALID),
    ])
    def test_first_error_wins(self, client, groceries, overrides, shown, hidden):
        log_in(client)
        resp = client.post(edit_url(groceries), data=form_from(expense_row(groceries), **overrides))
        html = resp.get_data(as_text=True)
        assert resp.status_code == 400
        assert error_present(html, shown)
        assert hidden not in html

    def test_error_page_shape(self, client, groceries):
        log_in(client)
        resp = client.post(edit_url(groceries), data=form_from(expense_row(groceries), amount="0"))
        html = resp.get_data(as_text=True)
        assert 'style="' not in html
        assert "auth-success" not in html
        assert f'max="{iso(TODAY)}"' in input_tag(html, "date")


class TestStoredFutureDate:
    def test_unchanged_future_date_saves(self, client):
        log_in(client)
        future = iso(TODAY + timedelta(days=5))
        eid = own_expense(future)
        resp = client.post(edit_url(eid), data=form_from(expense_row(eid), amount="99.00"))
        assert resp.status_code == 302
        row = expense_row(eid)
        assert row["amount"] == pytest.approx(99.0)
        assert row["date"] == future

    def test_different_future_date_rejected(self, client):
        log_in(client)
        eid = own_expense(iso(TODAY + timedelta(days=5)))
        before = expense_row(eid)
        resp = client.post(edit_url(eid), data=form_from(before, date=iso(TODAY + timedelta(days=6))))
        assert resp.status_code == 400
        assert error_present(resp.get_data(as_text=True), MSG_DATE_FUTURE)
        assert expense_row(eid) == before

    def test_allowance_is_per_expense(self, client):
        """One expense's stored future date doesn't unlock it for another."""
        log_in(client)
        future = iso(TODAY + timedelta(days=5))
        own_expense(future)
        past_id = own_expense(iso(TODAY - timedelta(days=3)))
        before = expense_row(past_id)
        resp = client.post(edit_url(past_id), data=form_from(before, date=future))
        assert resp.status_code == 400
        assert expense_row(past_id) == before

    def test_future_moved_to_past_saves(self, client):
        log_in(client)
        eid = own_expense(iso(TODAY + timedelta(days=5)))
        past = iso(TODAY - timedelta(days=2))
        resp = client.post(edit_url(eid), data=form_from(expense_row(eid), date=past))
        assert resp.status_code == 302
        assert expense_row(eid)["date"] == past


# ------------------------------------------------------------------ #
# Ownership and ids                                                   #
# ------------------------------------------------------------------ #

class TestOwnership:
    @pytest.mark.parametrize("method", ["get", "post"])
    def test_missing_id_404(self, client, method):
        log_in(client)
        count = count_expenses()
        kwargs = {"data": {"amount": "1", "category": "Food", "date": iso(TODAY)}} if method == "post" else {}
        resp = getattr(client, method)(edit_url(999999), **kwargs)
        assert resp.status_code == 404
        assert count_expenses() == count

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_other_users_expense_404_and_unchanged(self, client, method):
        _, eid = other_user_expense()
        log_in(client)
        before = expense_row(eid)
        kwargs = {"data": form_from(before, amount="1.00")} if method == "post" else {}
        resp = getattr(client, method)(edit_url(eid), **kwargs)
        assert resp.status_code == 404
        assert expense_row(eid) == before

    def test_foreign_and_missing_ids_look_identical(self, client):
        _, eid = other_user_expense()
        log_in(client)
        foreign = client.get(edit_url(eid))
        missing = client.get(edit_url(999999))
        assert foreign.status_code == missing.status_code == 404
        assert foreign.data == missing.data

    def test_non_integer_id_404(self, client):
        log_in(client)
        assert client.get("/expenses/abc/edit").status_code == 404

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_huge_id_404_not_500(self, client, method):
        log_in(client)
        resp = getattr(client, method)(edit_url(99999999999999999999))
        assert resp.status_code == 404

    def test_forged_user_id_ignored(self, client, groceries):
        other_id, _ = other_user_expense()
        user = log_in(client)
        form = form_from(expense_row(groceries), amount="50.00", user_id=str(other_id))
        assert client.post(edit_url(groceries), data=form).status_code == 302
        assert expense_row(groceries)["user_id"] == user["id"]

    def test_forged_id_in_body_ignored(self, client, groceries):
        log_in(client)
        rent_id = demo_expense_id("Monthly rent")
        rent_before = expense_row(rent_id)
        form = form_from(expense_row(groceries), amount="50.00", id=str(rent_id))
        assert client.post(edit_url(groceries), data=form).status_code == 302
        assert expense_row(groceries)["amount"] == pytest.approx(50.0)
        assert expense_row(rent_id) == rent_before

    def test_row_vanishing_before_update_is_404(self, client, groceries, monkeypatch):
        log_in(client)
        monkeypatch.setattr(app_module, "update_expense", lambda *a, **k: False)
        resp = client.post(edit_url(groceries), data=form_from(expense_row(groceries)))
        assert resp.status_code == 404
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert not flash_present(html, MSG_UPDATED)


# ------------------------------------------------------------------ #
# Cancel, styling                                                     #
# ------------------------------------------------------------------ #

def test_cancel_returns_to_profile_without_saving(client, groceries):
    log_in(client)
    before = expense_row(groceries)
    html = client.get(edit_url(groceries)).get_data(as_text=True)
    href = re.search(r'<a\s[^>]*href="([^"]+)"[^>]*>\s*Cancel', html).group(1)
    assert href == PROFILE_URL
    assert client.get(href).status_code == 200
    assert expense_row(groceries) == before


def test_edit_template_has_no_hex_or_inline_styles():
    source = (ROOT / "templates" / "edit_expense.html").read_text(encoding="utf-8")
    assert not HEX_RE.search(source)
    assert "style=" not in source
    assert "<style" not in source
    assert '{% extends "base.html" %}' in source


def test_css_rules():
    css = (ROOT / "static" / "css" / "profile.css").read_text(encoding="utf-8")
    global_css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert not HEX_RE.search(css)
    assert ".visually-hidden" in global_css  # shared utility lives in style.css
    assert ".profile-edit-link" in css
    assert re.search(r"\.profile-table-wrap\s*\{[^}]*overflow-x:\s*auto", css)


# ------------------------------------------------------------------ #
# Unit tests                                                          #
# ------------------------------------------------------------------ #

FIXED_TODAY = date(2026, 11, 20)


def _form(**overrides):
    form = {"amount": "10", "category": "Food", "date": "2026-11-20", "description": ""}
    form.update(overrides)
    return form


class TestValidateExpenseAllowedDate:
    def test_future_equal_to_allowed_passes(self):
        clean, error = validate_expense(_form(date="2026-11-25"), FIXED_TODAY, allowed_date="2026-11-25")
        assert error is None
        assert clean["date"] == "2026-11-25"

    def test_future_different_from_allowed_fails(self):
        _, error = validate_expense(_form(date="2026-11-26"), FIXED_TODAY, allowed_date="2026-11-25")
        assert error == MSG_DATE_FUTURE

    def test_future_without_allowed_fails(self):
        _, error = validate_expense(_form(date="2026-11-25"), FIXED_TODAY)
        assert error == MSG_DATE_FUTURE

    def test_past_with_allowed_passes(self):
        _, error = validate_expense(_form(date="2026-11-01"), FIXED_TODAY, allowed_date="2026-11-25")
        assert error is None

    def test_bad_date_still_invalid(self):
        _, error = validate_expense(_form(date="2026-13-01"), FIXED_TODAY, allowed_date="2026-13-01")
        assert error == MSG_DATE_INVALID

    def test_allowed_date_does_not_skip_earlier_errors(self):
        _, error = validate_expense(_form(amount="0", date="2026-11-25"), FIXED_TODAY, allowed_date="2026-11-25")
        assert error == MSG_AMOUNT_ZERO
        _, error = validate_expense(_form(category="Misc", date="2026-11-25"), FIXED_TODAY, allowed_date="2026-11-25")
        assert error == MSG_CATEGORY


class TestDbHelpers:
    def test_get_expense_by_id_shape(self, app):
        eid = demo_expense_id("Groceries")
        expense = get_expense_by_id(eid, demo_id())
        assert type(expense) is dict
        assert set(expense) == {"id", "amount", "category", "date", "description"}
        assert expense["id"] == eid
        assert expense["amount"] == pytest.approx(45.5)

    def test_get_expense_by_id_other_user_or_missing(self, app):
        _, eid = other_user_expense()
        assert get_expense_by_id(eid, demo_id()) is None
        assert get_expense_by_id(999999, demo_id()) is None
        assert get_expense_by_id(99999999999999999999, demo_id()) is None

    def test_update_expense_changes_row(self, app):
        eid = demo_expense_id("Groceries")
        before = expense_row(eid)
        assert update_expense(eid, demo_id(), 12.5, "Health", "2026-01-02", "Changed") is True
        after = expense_row(eid)
        assert (after["amount"], after["category"], after["date"], after["description"]) == (
            12.5, "Health", "2026-01-02", "Changed")
        assert after["user_id"] == before["user_id"]
        assert after["created_at"] == before["created_at"]

    def test_update_expense_description_defaults_to_null(self, app):
        eid = demo_expense_id("Groceries")
        assert update_expense(eid, demo_id(), 1.0, "Food", "2026-01-02") is True
        assert expense_row(eid)["description"] is None

    def test_update_expense_other_user_or_missing(self, app):
        _, eid = other_user_expense()
        before = expense_row(eid)
        assert update_expense(eid, demo_id(), 1.0, "Food", "2026-01-02") is False
        assert expense_row(eid) == before
        assert update_expense(999999, demo_id(), 1.0, "Food", "2026-01-02") is False

    def test_recent_transactions_ids_match_db(self, app):
        rows = get_recent_transactions(demo_id())
        assert set(rows[0]) == {"id", "date", "description", "category", "amount"}
        for row in rows:
            stored = expense_row(row["id"])
            assert stored["user_id"] == demo_id()
            assert stored["date"] == row["date"]
            assert stored["amount"] == pytest.approx(row["amount"])


@pytest.mark.parametrize("amount, description, expected_amount, expected_desc", [
    (1200.0, "Rent", "1200.00", "Rent"),
    (45.5, None, "45.50", ""),
    (0.1, "x", "0.10", "x"),
])
def test_expense_form_values(amount, description, expected_amount, expected_desc):
    values = _expense_form_values(
        {"id": 1, "amount": amount, "category": "Food", "date": "2026-11-01", "description": description}
    )
    assert values == {
        "amount": expected_amount,
        "category": "Food",
        "date": "2026-11-01",
        "description": expected_desc,
    }
