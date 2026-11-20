"""Hardening: CSRF tokens on every POST, SECRET_KEY fallback, debug flag."""
import re
from datetime import date
from pathlib import Path

import pytest

from app import DEV_SECRET_KEY, debug_enabled, load_secret_key
from database.db import get_db, get_user_by_email

ROOT = Path(__file__).resolve().parent.parent
DEMO_EMAIL = "demo@spendly.com"
TOKEN_RE = re.compile(r'<input type="hidden" name="csrf_token" value="([^"]+)">')
POST_PAGES = ["/login", "/register", "/expenses/add"]


@pytest.fixture
def csrf_app(app, monkeypatch):
    monkeypatch.setitem(app.config, "CSRF_ENABLED", True)
    return app


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


def log_in(client):
    user = get_user_by_email(DEMO_EMAIL)
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["name"]


def token_from(client, url):
    html = client.get(url).get_data(as_text=True)
    match = TOKEN_RE.search(html)
    assert match, f"no CSRF field on {url}"
    return match.group(1)


def count_expenses():
    conn = get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    finally:
        conn.close()


def groceries_id():
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id FROM expenses WHERE description = 'Groceries'"
        ).fetchone()["id"]
    finally:
        conn.close()


def expense_form(**extra):
    form = {"amount": "500", "category": "Food",
            "date": date.today().isoformat(), "description": "Team dinner"}
    form.update(extra)
    return form


# ------------------------------------------------------------------ #
# Every POST form carries the token                                   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("name", ["login", "register", "add_expense", "edit_expense", "delete_expense"])
def test_every_post_form_template_has_csrf_field(name):
    source = (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
    forms = re.findall(r"<form[^>]*method=\"post\"[^>]*>(.*?)</form>", source, re.I | re.S)
    assert forms, f"{name}.html has no POST form"
    for body in forms:
        assert 'name="csrf_token" value="{{ csrf_token() }}"' in body


@pytest.mark.parametrize("url", POST_PAGES)
def test_rendered_forms_include_session_token(csrf_client, url):
    if url == "/expenses/add":
        log_in(csrf_client)
    token = token_from(csrf_client, url)
    with csrf_client.session_transaction() as sess:
        assert sess["csrf_token"] == token


def test_token_is_stable_within_a_session(csrf_client):
    assert token_from(csrf_client, "/login") == token_from(csrf_client, "/register")


def test_tokens_differ_between_sessions(csrf_app):
    assert token_from(csrf_app.test_client(), "/login") != token_from(
        csrf_app.test_client(), "/login"
    )


# ------------------------------------------------------------------ #
# POSTs without a valid token are rejected                            #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("bad", [None, "", "wrong-token", "tökén"])
def test_login_without_valid_token_is_400(csrf_client, bad):
    token_from(csrf_client, "/login")  # session has a real token
    data = {"email": DEMO_EMAIL, "password": "demo123"}
    if bad is not None:
        data["csrf_token"] = bad
    resp = csrf_client.post("/login", data=data)
    assert resp.status_code == 400
    with csrf_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_post_with_no_session_token_is_400(csrf_client):
    resp = csrf_client.post("/login", data={"email": DEMO_EMAIL, "password": "demo123",
                                            "csrf_token": "anything"})
    assert resp.status_code == 400


def test_register_without_token_creates_no_user(csrf_client):
    token_from(csrf_client, "/register")
    resp = csrf_client.post("/register", data={"name": "X", "email": "x@example.com",
                                               "password": "password123"})
    assert resp.status_code == 400
    assert get_user_by_email("x@example.com") is None


def test_add_expense_without_token_inserts_nothing(csrf_client):
    log_in(csrf_client)
    token_from(csrf_client, "/expenses/add")
    before = count_expenses()
    resp = csrf_client.post("/expenses/add", data=expense_form())
    assert resp.status_code == 400
    assert count_expenses() == before


def test_edit_expense_without_token_changes_nothing(csrf_client):
    log_in(csrf_client)
    eid = groceries_id()
    token_from(csrf_client, f"/expenses/{eid}/edit")
    resp = csrf_client.post(f"/expenses/{eid}/edit", data=expense_form(amount="1.00"))
    assert resp.status_code == 400
    conn = get_db()
    try:
        amount = conn.execute("SELECT amount FROM expenses WHERE id = ?", (eid,)).fetchone()[0]
    finally:
        conn.close()
    assert amount == pytest.approx(45.5)


def test_get_requests_need_no_token(csrf_client):
    log_in(csrf_client)
    assert csrf_client.get("/profile").status_code == 200
    assert csrf_client.get("/profile?start_date=2026-01-01").status_code == 200


# ------------------------------------------------------------------ #
# POSTs with the token work end to end                                #
# ------------------------------------------------------------------ #

def test_login_with_token_succeeds(csrf_client):
    token = token_from(csrf_client, "/login")
    resp = csrf_client.post("/login", data={"email": DEMO_EMAIL, "password": "demo123",
                                            "csrf_token": token})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")


def test_register_with_token_succeeds(csrf_client):
    token = token_from(csrf_client, "/register")
    resp = csrf_client.post("/register", data={"name": "New", "email": "new@example.com",
                                               "password": "password123",
                                               "csrf_token": token})
    assert resp.status_code == 302
    assert get_user_by_email("new@example.com") is not None


def test_add_expense_with_token_succeeds(csrf_client):
    log_in(csrf_client)
    token = token_from(csrf_client, "/expenses/add")
    before = count_expenses()
    resp = csrf_client.post("/expenses/add", data=expense_form(csrf_token=token))
    assert resp.status_code == 302
    assert count_expenses() == before + 1


def test_edit_expense_with_token_succeeds(csrf_client):
    log_in(csrf_client)
    eid = groceries_id()
    url = f"/expenses/{eid}/edit"
    token = token_from(csrf_client, url)
    conn = get_db()
    try:
        stored_date = conn.execute("SELECT date FROM expenses WHERE id = ?", (eid,)).fetchone()[0]
    finally:
        conn.close()
    resp = csrf_client.post(url, data=expense_form(amount="50.00", date=stored_date,
                                                   csrf_token=token))
    assert resp.status_code == 302


def test_validation_error_page_still_has_token(csrf_client):
    log_in(csrf_client)
    token = token_from(csrf_client, "/expenses/add")
    resp = csrf_client.post("/expenses/add", data=expense_form(amount="0", csrf_token=token))
    assert resp.status_code == 400
    assert TOKEN_RE.search(resp.get_data(as_text=True)).group(1) == token


def test_csrf_enabled_by_default():
    from app import app as flask_app
    # conftest switches it off per test via monkeypatch; outside a test
    # fixture the app's own default must be on. Check the source of truth.
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'app.config["CSRF_ENABLED"] = True' in source
    assert "CSRF_ENABLED" in flask_app.config


# ------------------------------------------------------------------ #
# SECRET_KEY and debug                                                #
# ------------------------------------------------------------------ #

def test_secret_key_from_environment():
    assert load_secret_key({"SECRET_KEY": "from-env"}) == "from-env"


def test_dev_key_only_in_debug():
    assert load_secret_key({"FLASK_DEBUG": "1"}) == DEV_SECRET_KEY


def test_no_key_outside_debug_is_random_and_warns():
    with pytest.warns(UserWarning, match="SECRET_KEY is not set"):
        first = load_secret_key({})
    with pytest.warns(UserWarning):
        second = load_secret_key({})
    assert first != DEV_SECRET_KEY
    assert first != second
    assert len(first) >= 32


@pytest.mark.parametrize("env, expected", [
    ({}, False),
    ({"FLASK_DEBUG": "0"}, False),
    ({"FLASK_DEBUG": "true"}, False),
    ({"FLASK_DEBUG": "1"}, True),
])
def test_debug_enabled_only_with_flag(env, expected):
    assert debug_enabled(env) is expected


def test_app_run_uses_debug_flag():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "debug=True" not in source
    assert "app.run(debug=debug_enabled(os.environ), port=5001)" in source
