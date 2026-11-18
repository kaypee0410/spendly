import pytest
from werkzeug.security import check_password_hash

from database.db import create_user, get_db, get_user_by_email

VALID = {"name": "Jane Doe", "email": "jane@example.com", "password": "supersecret"}


def count_users():
    conn = get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def post_register(client, **overrides):
    return client.post("/register", data={**VALID, **overrides})


def test_get_register_renders_form(client):
    resp = client.get("/register")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "<form" in html
    assert 'action="/register"' in html


def test_valid_registration_creates_user_and_redirects(client):
    before = count_users()
    resp = post_register(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert count_users() == before + 1

    login = client.get(resp.headers["Location"])
    html = login.get_data(as_text=True)
    assert 'class="auth-success"' in html
    assert "Account created — please sign in." in html


def test_password_is_hashed(client):
    post_register(client)
    user = get_user_by_email(VALID["email"])
    assert user is not None
    assert user["password_hash"] != VALID["password"]
    assert user["password_hash"].startswith(("scrypt:", "pbkdf2:"))
    assert check_password_hash(user["password_hash"], VALID["password"])


def test_email_is_normalised_to_lowercase(client):
    post_register(client, email="  Foo@Example.com ")
    assert get_user_by_email("foo@example.com") is not None
    assert get_user_by_email("Foo@Example.com") is None


@pytest.mark.parametrize("email", ["demo@spendly.com", "DEMO@spendly.com"])
def test_duplicate_email_rejected(client, email):
    before = count_users()
    resp = post_register(client, email=email)
    assert resp.status_code == 400
    assert "An account with that email already exists." in resp.get_data(as_text=True)
    assert count_users() == before


def test_short_password_rejected(client):
    before = count_users()
    resp = post_register(client, password="1234567")
    assert resp.status_code == 400
    assert "Password must be at least 8 characters." in resp.get_data(as_text=True)
    assert count_users() == before


@pytest.mark.parametrize(
    "overrides",
    [{"name": ""}, {"email": ""}, {"password": ""}, {"name": "   "}],
)
def test_missing_fields_rejected(client, overrides):
    before = count_users()
    resp = post_register(client, **overrides)
    assert resp.status_code == 400
    assert "All fields are required." in resp.get_data(as_text=True)
    assert count_users() == before


@pytest.mark.parametrize("email", ["foo", "foo@bar", "foo.bar@", "@example.com"])
def test_invalid_email_rejected(client, email):
    before = count_users()
    resp = post_register(client, email=email)
    assert resp.status_code == 400
    assert "Please enter a valid email address." in resp.get_data(as_text=True)
    assert count_users() == before


def test_form_repopulated_without_password_after_error(client):
    password = "Unique-Secret-Value-123"
    resp = post_register(client, name="Jane", email="demo@spendly.com", password=password)
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400
    assert 'value="Jane"' in html
    assert 'value="demo@spendly.com"' in html
    assert password not in html


def test_create_user_returns_none_for_existing_email(app):
    assert create_user("Someone", "demo@spendly.com", "password123") is None
