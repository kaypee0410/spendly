import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from database.db import create_expense, create_user, get_db, get_user_by_email

ROOT = Path(__file__).resolve().parent.parent
DEMO_EMAIL = "demo@spendly.com"
ADD_URL = "/expenses/add"
PROFILE_URL = "/profile"
LOGIN_URL = "/login"

CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]

MSG_LOGIN = "Please sign in to add an expense."
MSG_ADDED = "Expense added."
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


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def log_in(client, email=DEMO_EMAIL):
    user = get_user_by_email(email)
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["name"]
    return user


def count_expenses():
    conn = get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    finally:
        conn.close()


def last_expense():
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()


def iso(d):
    return d.isoformat()


def valid_form(**overrides):
    form = {
        "amount": "500",
        "category": "Food",
        "date": iso(date.today()),
        "description": "Team dinner",
    }
    form.update(overrides)
    return form


def flash_present(html, message):
    return re.search(r'class="auth-success"[^>]*>[^<]*' + re.escape(message), html) is not None


def error_present(html, message):
    return re.search(r'class="auth-error"[^>]*>\s*' + re.escape(message), html) is not None


def post_expense(client, **overrides):
    return client.post(ADD_URL, data=valid_form(**overrides))


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

def test_get_logged_out_redirects_to_login_with_flash(client):
    resp = client.get(ADD_URL)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    html = client.get(LOGIN_URL).get_data(as_text=True)
    assert flash_present(html, MSG_LOGIN), "Expected sign-in flash on login page"


def test_post_logged_out_redirects_and_inserts_nothing(client):
    before = count_expenses()
    resp = post_expense(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    assert count_expenses() == before, "Logged-out POST must not insert"


@pytest.mark.parametrize("method", ["get", "post"])
def test_stale_session_redirects_to_login_and_clears_session(client, method):
    with client.session_transaction() as sess:
        sess["user_id"] = 999999
        sess["user_name"] = "Ghost"
    before = count_expenses()
    resp = getattr(client, method)(ADD_URL, **({"data": valid_form()} if method == "post" else {}))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LOGIN_URL)
    assert count_expenses() == before
    with client.session_transaction() as sess:
        assert "user_id" not in sess, "Stale session should be cleared"


# ------------------------------------------------------------------ #
# Profile link and form page                                          #
# ------------------------------------------------------------------ #

def test_profile_has_add_expense_link(client):
    log_in(client)
    html = client.get(PROFILE_URL).get_data(as_text=True)
    assert re.search(r'<a\s[^>]*href="/expenses/add"[^>]*>\s*Add expense', html), \
        "Expected 'Add expense' link to /expenses/add on profile"


def test_add_link_opens_form(client):
    log_in(client)
    resp = client.get(ADD_URL)
    assert resp.status_code == 200
    assert "Add expense" in resp.get_data(as_text=True)


class TestAddForm:
    @pytest.fixture
    def html(self, client):
        log_in(client)
        return client.get(ADD_URL).get_data(as_text=True)

    def test_form_posts_to_add_url(self, html):
        assert re.search(r'<form[^>]*method="post"[^>]*action="/expenses/add"', html), \
            "Expected POST form targeting /expenses/add"

    @pytest.mark.parametrize("name", ["amount", "category", "date", "description"])
    def test_form_has_field(self, html, name):
        assert f'name="{name}"' in html, f"Missing field {name}"

    def test_amount_input_attributes(self, html):
        tag = re.search(r'<input[^>]*name="amount"[^>]*>', html).group(0)
        assert 'type="number"' in tag
        assert 'step="0.01"' in tag
        assert 'min="0.01"' in tag
        assert "required" in tag

    def test_date_prefilled_with_today_and_max(self, html):
        tag = re.search(r'<input[^>]*name="date"[^>]*>', html).group(0)
        assert 'type="date"' in tag
        assert f'value="{iso(date.today())}"' in tag, "Date should default to today"
        assert f'max="{iso(date.today())}"' in tag, "Date max should be today"

    def test_description_is_optional_with_maxlength(self, html):
        tag = re.search(r'<input[^>]*name="description"[^>]*>', html).group(0)
        assert 'maxlength="200"' in tag
        assert "required" not in tag
        assert "(optional)" in html

    def test_category_placeholder_and_seven_options(self, html):
        select = re.search(r'<select[^>]*name="category"[^>]*>(.*?)</select>', html, re.S)
        assert select, "Expected category select"
        body = select.group(1)
        assert "Choose a category" in body
        assert re.search(r"<option[^>]*disabled[^>]*>\s*Choose a category", body)
        for cat in CATEGORIES:
            assert f'value="{cat}"' in body, f"Missing category option {cat}"
        # placeholder + 7 categories
        assert len(re.findall(r"<option\b", body)) == 8
        assert not re.search(r'<option[^>]*value="(?:Food|Other)"[^>]*selected', body), \
            "No category should be preselected"

    def test_save_button_and_cancel_link(self, html):
        assert re.search(r'<button[^>]*type="submit"[^>]*>\s*Save expense', html)
        assert re.search(r'<a\s[^>]*href="/profile"[^>]*>\s*Cancel', html), \
            "Cancel should link to /profile"

    def test_no_error_shown_on_get(self, html):
        assert 'class="auth-error"' not in html

    def test_links_expenses_stylesheet(self, html):
        assert "/static/css/expenses.css" in html


# ------------------------------------------------------------------ #
# Happy path                                                          #
# ------------------------------------------------------------------ #

class TestHappyPath:
    def test_valid_post_redirects_to_profile(self, client):
        log_in(client)
        resp = post_expense(client)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(PROFILE_URL)

    def test_flash_shown_and_totals_updated(self, client):
        log_in(client)
        before = client.get(PROFILE_URL).get_data(as_text=True)
        assert "₹1,484.24" in before
        resp = client.post(ADD_URL, data=valid_form(), follow_redirects=True)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert flash_present(html, MSG_ADDED), "Expected 'Expense added.' flash"
        assert "₹1,984.24" in html
        assert re.search(r'profile-stat-value">\s*9\s*<', html), "Expected 9 transactions"

    def test_new_expense_in_recent_transactions(self, client):
        log_in(client)
        html = client.post(ADD_URL, data=valid_form(), follow_redirects=True).get_data(as_text=True)
        assert "Team dinner" in html
        assert "₹500.00" in html
        assert "Food" in html

    def test_db_row_has_expected_values(self, client):
        user = log_in(client)
        before = count_expenses()
        post_expense(client)
        assert count_expenses() == before + 1
        row = last_expense()
        assert row["user_id"] == user["id"]
        assert row["amount"] == pytest.approx(500.0)
        assert row["category"] == "Food"
        assert row["date"] == iso(date.today())
        assert row["description"] == "Team dinner"
        assert row["created_at"] is not None

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_description_stored_as_null(self, client, blank):
        log_in(client)
        resp = post_expense(client, description=blank)
        assert resp.status_code == 302
        assert last_expense()["description"] is None

    def test_description_is_stripped(self, client):
        log_in(client)
        post_expense(client, description="  Lunch  ")
        assert last_expense()["description"] == "Lunch"

    def test_missing_description_field_saves(self, client):
        log_in(client)
        form = valid_form()
        del form["description"]
        resp = client.post(ADD_URL, data=form)
        assert resp.status_code == 302
        assert last_expense()["description"] is None

    def test_refresh_profile_does_not_duplicate(self, client):
        log_in(client)
        client.post(ADD_URL, data=valid_form(), follow_redirects=True)
        after_first = count_expenses()
        client.get(PROFILE_URL)
        client.get(PROFILE_URL)
        assert count_expenses() == after_first

    def test_flash_not_shown_twice(self, client):
        log_in(client)
        client.post(ADD_URL, data=valid_form(), follow_redirects=True)
        html = client.get(PROFILE_URL).get_data(as_text=True)
        assert not flash_present(html, MSG_ADDED)


# ------------------------------------------------------------------ #
# Validation errors                                                   #
# ------------------------------------------------------------------ #

AMOUNT_ERRORS = [
    ("", MSG_AMOUNT_REQUIRED),
    ("abc", MSG_AMOUNT_INVALID),
    ("nan", MSG_AMOUNT_INVALID),
    ("inf", MSG_AMOUNT_INVALID),
    ("-inf", MSG_AMOUNT_INVALID),
    ("1" * 21, MSG_AMOUNT_INVALID),  # longer than MAX_AMOUNT_LENGTH
    ("0", MSG_AMOUNT_ZERO),
    ("-5", MSG_AMOUNT_ZERO),
    ("12.345", MSG_AMOUNT_DECIMALS),
    ("20000000", MSG_AMOUNT_LARGE),
    ("10000000.01", MSG_AMOUNT_LARGE),
]


@pytest.mark.parametrize("amount,message", AMOUNT_ERRORS)
def test_invalid_amount_returns_400_with_error(client, amount, message):
    log_in(client)
    before = count_expenses()
    resp = post_expense(client, amount=amount)
    assert resp.status_code == 400
    assert error_present(resp.get_data(as_text=True), message), f"Expected {message!r}"
    assert count_expenses() == before


@pytest.mark.parametrize("amount,message", AMOUNT_ERRORS)
def test_invalid_amount_preserves_other_fields(client, amount, message):
    log_in(client)
    html = post_expense(client, amount=amount, description="Keep me").get_data(as_text=True)
    assert 'value="Keep me"' in html, "Description should be preserved"
    assert f'value="{iso(date.today())}"' in html, "Date should be preserved"
    assert re.search(
        r'<option[^>]*value="Food"[^>]*selected|<option[^>]*selected[^>]*value="Food"', html
    ), "Category should stay selected"


def test_invalid_amount_value_is_echoed_back(client):
    log_in(client)
    html = post_expense(client, amount="12.345").get_data(as_text=True)
    assert 'value="12.345"' in html


@pytest.mark.parametrize(
    "category",
    ["Hacking", "food", "FOOD", "", " Food", "Food ", "'; DROP TABLE expenses;--"],
)
def test_invalid_category_returns_400(client, category):
    log_in(client)
    before = count_expenses()
    resp = post_expense(client, category=category)
    assert resp.status_code == 400
    assert error_present(resp.get_data(as_text=True), MSG_CATEGORY)
    assert count_expenses() == before


def test_missing_category_field_returns_400(client):
    log_in(client)
    form = valid_form()
    del form["category"]
    before = count_expenses()
    resp = client.post(ADD_URL, data=form)
    assert resp.status_code == 400
    assert error_present(resp.get_data(as_text=True), MSG_CATEGORY)
    assert count_expenses() == before


def _tomorrow():
    return iso(date.today() + timedelta(days=1))


@pytest.mark.parametrize("bad_date,message", [
    ("", MSG_DATE_INVALID),
    ("2026-13-01", MSG_DATE_INVALID),
    ("2026-02-30", MSG_DATE_INVALID),
    ("not-a-date", MSG_DATE_INVALID),
    ("20/11/2026", MSG_DATE_INVALID),
    ("2026-1-1", MSG_DATE_INVALID),
    (_tomorrow(), MSG_DATE_FUTURE),
    ("2999-01-01", MSG_DATE_FUTURE),
])
def test_invalid_date_returns_400(client, bad_date, message):
    log_in(client)
    before = count_expenses()
    resp = post_expense(client, date=bad_date)
    assert resp.status_code == 400
    assert error_present(resp.get_data(as_text=True), message), f"Expected {message!r}"
    assert count_expenses() == before


def test_missing_date_field_returns_400(client):
    log_in(client)
    form = valid_form()
    del form["date"]
    before = count_expenses()
    resp = client.post(ADD_URL, data=form)
    assert resp.status_code == 400
    assert error_present(resp.get_data(as_text=True), MSG_DATE_INVALID)
    assert count_expenses() == before


def test_invalid_date_preserves_other_fields(client):
    log_in(client)
    html = post_expense(client, date="2026-13-01", amount="42.50").get_data(as_text=True)
    assert 'value="42.50"' in html
    assert 'value="Team dinner"' in html


def test_description_201_chars_returns_400(client):
    log_in(client)
    before = count_expenses()
    resp = post_expense(client, description="x" * 201)
    assert resp.status_code == 400
    assert error_present(resp.get_data(as_text=True), MSG_DESC_LONG)
    assert count_expenses() == before


def test_oversized_request_body_rejected(client):
    log_in(client)
    before = count_expenses()
    resp = post_expense(client, description="x" * (64 * 1024))
    assert resp.status_code == 413, "Bodies over MAX_CONTENT_LENGTH should be refused"
    assert count_expenses() == before


def test_invalid_input_flashes_no_success(client):
    log_in(client)
    html = post_expense(client, amount="0").get_data(as_text=True)
    assert MSG_ADDED not in html


# ------------------------------------------------------------------ #
# Boundaries and edge cases                                           #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("amount,expected", [
    ("10000000", 10000000.0),
    ("0.01", 0.01),
    ("12.340", 12.34),
    ("7", 7.0),
    ("7.5", 7.5),
    ("5.50", 5.5),
])
def test_boundary_amounts_accepted(client, amount, expected):
    log_in(client)
    before = count_expenses()
    resp = post_expense(client, amount=amount)
    assert resp.status_code == 302, f"{amount} should be accepted"
    assert count_expenses() == before + 1
    assert last_expense()["amount"] == pytest.approx(expected)


def test_description_exactly_200_chars_accepted(client):
    log_in(client)
    resp = post_expense(client, description="y" * 200)
    assert resp.status_code == 302
    assert last_expense()["description"] == "y" * 200


@pytest.mark.parametrize("delta", [0, -1])
def test_today_and_yesterday_accepted(client, delta):
    log_in(client)
    target = iso(date.today() + timedelta(days=delta))
    resp = post_expense(client, date=target)
    assert resp.status_code == 302
    assert last_expense()["date"] == target


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_allowed_category_accepted(client, category):
    log_in(client)
    resp = post_expense(client, category=category)
    assert resp.status_code == 302
    assert last_expense()["category"] == category


def test_sql_injection_description_stored_literally(client):
    log_in(client)
    payload = "x'); DROP TABLE expenses; --"
    resp = post_expense(client, description=payload)
    assert resp.status_code == 302
    assert last_expense()["description"] == payload
    assert count_expenses() == 9


def test_html_in_description_is_escaped_on_profile(client):
    log_in(client)
    post_expense(client, description="<script>alert(1)</script>")
    html = client.get(PROFILE_URL).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


def test_forged_user_id_field_is_ignored(client):
    other_id = create_user("Other Person", "other@example.com", "otherpass1")
    demo = log_in(client)
    resp = post_expense(client, user_id=str(other_id))
    assert resp.status_code == 302
    assert last_expense()["user_id"] == demo["id"]


# ------------------------------------------------------------------ #
# User isolation                                                      #
# ------------------------------------------------------------------ #

def test_expense_not_visible_to_other_user(client):
    create_user("Other Person", "other@example.com", "otherpass1")
    log_in(client)
    post_expense(client, description="Private lunch")
    # Switch session to the second user.
    log_in(client, email="other@example.com")
    html = client.get(PROFILE_URL).get_data(as_text=True)
    assert "Private lunch" not in html
    assert "₹500.00" not in html
    conn = get_db()
    try:
        other = get_user_by_email("other@example.com")
        n = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (other["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# ------------------------------------------------------------------ #
# Cancel and stubs                                                    #
# ------------------------------------------------------------------ #

def test_cancel_link_goes_to_profile_without_saving(client):
    log_in(client)
    before = count_expenses()
    html = client.get(ADD_URL).get_data(as_text=True)
    href = re.search(r'<a\s[^>]*href="([^"]+)"[^>]*>\s*Cancel', html).group(1)
    assert href == PROFILE_URL
    resp = client.get(href)
    assert resp.status_code == 200
    assert count_expenses() == before


@pytest.mark.parametrize("url,text", [
    ("/expenses/1/edit", "Edit expense — coming in Step 8"),
    ("/expenses/1/delete", "Delete expense — coming in Step 9"),
])
def test_later_stubs_unchanged(client, url, text):
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == text


# ------------------------------------------------------------------ #
# Styling rules                                                       #
# ------------------------------------------------------------------ #

def test_template_has_no_hex_colours_or_inline_styles():
    source = (ROOT / "templates" / "add_expense.html").read_text(encoding="utf-8")
    assert not HEX_RE.search(source), "Template must not hardcode hex colours"
    assert "style=" not in source
    assert "<style" not in source


def test_css_has_no_hex_colours():
    css = (ROOT / "static" / "css" / "expenses.css").read_text(encoding="utf-8")
    assert not HEX_RE.search(css), "expenses.css must use CSS variables, not hex"


def test_css_has_mobile_breakpoint():
    css = (ROOT / "static" / "css" / "expenses.css").read_text(encoding="utf-8")
    assert re.search(r"@media\s*\(\s*max-width:\s*640px\s*\)", css)


def test_rendered_add_page_has_no_inline_style(client):
    log_in(client)
    html = client.get(ADD_URL).get_data(as_text=True)
    assert 'style="' not in html
    error_html = post_expense(client, amount="0").get_data(as_text=True)
    assert 'style="' not in error_html


# ------------------------------------------------------------------ #
# Unit tests: validate_expense                                        #
# ------------------------------------------------------------------ #

class TestValidateExpense:
    TODAY = date(2026, 11, 20)

    def run(self, **overrides):
        from app import validate_expense
        form = {"amount": "12.34", "category": "Food", "date": "2026-11-20", "description": "Tea"}
        form.update(overrides)
        return validate_expense(form, self.TODAY)

    def test_valid_returns_clean_and_no_error(self):
        clean, error = self.run()
        assert error is None
        assert clean["amount"] == pytest.approx(12.34)
        assert isinstance(clean["amount"], float)
        assert clean["category"] == "Food"
        assert str(clean["date"]) == "2026-11-20"
        assert clean["description"] == "Tea"

    def test_trailing_zero_amount_is_valid(self):
        clean, error = self.run(amount="12.340")
        assert error is None
        assert clean["amount"] == pytest.approx(12.34)

    def test_blank_description_becomes_none(self):
        clean, error = self.run(description="   ")
        assert error is None
        assert clean["description"] is None

    @pytest.mark.parametrize("overrides,message", [
        ({"amount": ""}, MSG_AMOUNT_REQUIRED),
        ({"amount": "abc"}, MSG_AMOUNT_INVALID),
        ({"amount": "0"}, MSG_AMOUNT_ZERO),
        ({"amount": "1.234"}, MSG_AMOUNT_DECIMALS),
        ({"amount": "10000001"}, MSG_AMOUNT_LARGE),
        ({"category": "Nope"}, MSG_CATEGORY),
        ({"date": "2026-13-01"}, MSG_DATE_INVALID),
        ({"date": "2026-11-21"}, MSG_DATE_FUTURE),
        ({"description": "z" * 201}, MSG_DESC_LONG),
    ])
    def test_errors_return_none_and_message(self, overrides, message):
        clean, error = self.run(**overrides)
        assert clean is None
        assert error == message

    def test_today_is_not_future(self):
        clean, error = self.run(date="2026-11-20")
        assert error is None and clean is not None

    def test_first_error_wins_amount_before_category(self):
        clean, error = self.run(amount="0", category="Nope", date="bad")
        assert clean is None
        assert error == MSG_AMOUNT_ZERO

    def test_first_error_wins_category_before_date(self):
        clean, error = self.run(category="Nope", date="bad")
        assert clean is None
        assert error == MSG_CATEGORY


# ------------------------------------------------------------------ #
# Unit tests: create_expense                                          #
# ------------------------------------------------------------------ #

def test_create_expense_returns_int_id_and_inserts_row(client):
    user = get_user_by_email(DEMO_EMAIL)
    before = count_expenses()
    new_id = create_expense(user["id"], 9.99, "Other", iso(date.today()), "Direct")
    assert isinstance(new_id, int)
    assert count_expenses() == before + 1
    assert last_expense()["id"] == new_id


def test_create_expense_description_defaults_to_null(client):
    user = get_user_by_email(DEMO_EMAIL)
    create_expense(user["id"], 3.0, "Bills", iso(date.today()))
    assert last_expense()["description"] is None


def test_create_expense_unknown_user_raises_integrity_error(client):
    before = count_expenses()
    with pytest.raises(sqlite3.IntegrityError):
        create_expense(999999, 5.0, "Food", iso(date.today()), "Orphan")
    assert count_expenses() == before
