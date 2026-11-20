import pytest

from database.db import authenticate_user, get_db, get_user_by_email

DEMO = {"email": "demo@spendly.com", "password": "demo123"}
NEW_USER = {"name": "Asha Rao", "email": "asha@example.com", "password": "s3cretpass"}


def post_login(client, **overrides):
    return client.post("/login", data={**DEMO, **overrides})


def log_in(client):
    """Put the demo user in the session without going through POST /login."""
    user = get_user_by_email(DEMO["email"])
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["name"]


def session_keys(client):
    with client.session_transaction() as sess:
        return set(sess.keys())


def count_users():
    conn = get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# authenticate_user                                                   #
# ------------------------------------------------------------------ #

def test_authenticate_user_success(app):
    user = authenticate_user(DEMO["email"], DEMO["password"])
    assert user is not None
    assert user["email"] == DEMO["email"]


def test_authenticate_user_wrong_password_returns_none(app):
    assert authenticate_user(DEMO["email"], "wrong-password") is None


def test_authenticate_user_unknown_email_returns_none(app):
    assert authenticate_user("nobody@example.com", DEMO["password"]) is None


# ------------------------------------------------------------------ #
# GET /login                                                          #
# ------------------------------------------------------------------ #

def test_get_login_renders_form_when_logged_out(client):
    resp = client.get("/login")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'action="/login"' in html
    assert "Sign out" not in html


# ------------------------------------------------------------------ #
# POST /login — success                                               #
# ------------------------------------------------------------------ #

def test_login_success_sets_session_and_redirects(client):
    resp = post_login(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    demo = get_user_by_email(DEMO["email"])
    with client.session_transaction() as sess:
        assert sess["user_id"] == demo["id"]
        assert sess["user_name"] == "Demo User"
        assert set(sess.keys()) == {"user_id", "user_name"}


@pytest.mark.parametrize("email", ["DEMO@Spendly.com", "  demo@spendly.com  "])
def test_login_email_case_and_whitespace_insensitive(client, email):
    resp = post_login(client, email=email)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")


def test_login_clears_existing_session(client):
    with client.session_transaction() as sess:
        sess["stale"] = "x"
    post_login(client)
    assert "stale" not in session_keys(client)


def test_newly_registered_user_can_log_in(client):
    client.post("/register", data=NEW_USER)
    resp = post_login(client, email=NEW_USER["email"], password=NEW_USER["password"])
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    with client.session_transaction() as sess:
        assert sess["user_name"] == NEW_USER["name"]


def test_logged_in_post_login_switches_user(client):
    client.post("/register", data=NEW_USER)
    log_in(client)
    post_login(client, email=NEW_USER["email"], password=NEW_USER["password"])
    new_user = get_user_by_email(NEW_USER["email"])
    with client.session_transaction() as sess:
        assert sess["user_id"] == new_user["id"]


# ------------------------------------------------------------------ #
# POST /login — failure                                               #
# ------------------------------------------------------------------ #

def test_wrong_password_rejected(client):
    resp = post_login(client, password="not-the-password")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 401
    assert "Invalid email or password." in html
    assert 'value="demo@spendly.com"' in html
    assert "not-the-password" not in html
    assert "user_id" not in session_keys(client)


def test_unknown_email_rejected_with_same_message(client):
    resp = post_login(client, email="nobody@example.com")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 401
    assert "Invalid email or password." in html
    assert 'value="nobody@example.com"' in html
    assert "user_id" not in session_keys(client)


def test_password_not_stripped(client):
    resp = post_login(client, password="demo123 ")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [{"email": ""}, {"password": ""}, {"email": "   "}],
)
def test_missing_fields_rejected(client, overrides):
    resp = post_login(client, **overrides)
    assert resp.status_code == 400
    assert "All fields are required." in resp.get_data(as_text=True)
    assert "user_id" not in session_keys(client)


def test_failed_login_does_not_echo_password(client):
    secret = "Unique-Pa55word-xyz"
    resp = post_login(client, email="ghost@example.com", password=secret)
    html = resp.get_data(as_text=True)
    assert secret not in html
    assert 'value="ghost@example.com"' in html


# ------------------------------------------------------------------ #
# Logout                                                              #
# ------------------------------------------------------------------ #

def test_logout_clears_session_and_flashes(client):
    log_in(client)
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert "user_id" not in session_keys(client)
    assert "user_name" not in session_keys(client)

    page = client.get(resp.headers["Location"])
    html = page.get_data(as_text=True)
    assert 'class="auth-success"' in html
    assert "You have been signed out." in html


def test_logout_when_logged_out_redirects(client):
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


# ------------------------------------------------------------------ #
# Logged-in redirects                                                 #
# ------------------------------------------------------------------ #

def test_logged_in_get_login_redirects_to_profile(client):
    log_in(client)
    resp = client.get("/login")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")


def test_logged_in_get_register_redirects_to_profile(client):
    log_in(client)
    resp = client.get("/register")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")


def test_logged_in_post_register_redirects_without_creating_user(client):
    log_in(client)
    before = count_users()
    resp = client.post("/register", data=NEW_USER)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    assert count_users() == before


# ------------------------------------------------------------------ #
# Navbar                                                              #
# ------------------------------------------------------------------ #

def test_navbar_logged_out(client):
    html = client.get("/terms").get_data(as_text=True)
    assert ">Sign in</a>" in html
    assert ">Get started</a>" in html
    assert "Sign out" not in html
    assert "nav-user" not in html


def test_navbar_logged_in(client):
    log_in(client)
    html = client.get("/terms").get_data(as_text=True)
    assert "Hi, Demo User" in html
    assert '<a href="/logout" class="nav-cta">Sign out</a>' in html
    assert ">Sign in</a>" not in html
    assert ">Get started</a>" not in html


def test_navbar_escapes_user_name(client):
    client.post("/register", data={**NEW_USER, "name": "<b>x</b>"})
    post_login(client, email=NEW_USER["email"], password=NEW_USER["password"])
    html = client.get("/terms").get_data(as_text=True)
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html


# ------------------------------------------------------------------ #
# Config                                                              #
# ------------------------------------------------------------------ #

def test_session_cookie_samesite_lax(app):
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_profile_requires_login(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
