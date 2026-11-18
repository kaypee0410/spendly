# Spec: Registration

## Overview
Make the existing sign-up form actually create accounts. Today `GET /register`
renders `register.html`, but the form posts to a route that does not accept
`POST`, so submitting it fails with 405. This step adds a `POST /register`
handler that validates the submitted name, email and password, stores a new
row in the `users` table with a werkzeug-hashed password, and redirects the
new user to the sign-in page with a success message. Registration comes right
after the database setup (Step 1) because every later feature — login/logout,
profile, and all expense CRUD — needs real user accounts to exist. Logging the
user in (sessions) is explicitly **not** part of this step; that belongs to the
login/logout step.

## Depends on
- **Step 1 — Database setup** (`.claude/specs/01-database-setup.md`): the
  `users` table (with `email UNIQUE NOT NULL`), `get_db()` with
  `PRAGMA foreign_keys = ON`, and `init_db()` running on app startup.

## Routes
- `POST /register` — validate the form, create the user, redirect to
  `url_for('login')` with a flashed success message; on validation failure,
  re-render `register.html` with an error and the user's previously entered
  name/email — public
- `GET /register` — already implemented; the existing `register()` view is
  extended to `methods=["GET", "POST"]` rather than adding a second function —
  public

No other routes change. Stub routes (`/logout`, `/profile`, `/expenses/...`)
must be left untouched.

## Database changes
No database changes. The `users` table in `database/db.py` already has
everything needed: `id`, `name TEXT NOT NULL`, `email TEXT UNIQUE NOT NULL`,
`password_hash TEXT NOT NULL`, `created_at`.

New helper functions are added to `database/db.py` (no schema change):

- `get_user_by_email(email)` — returns the matching `users` row
  (`sqlite3.Row`) or `None`. Single parameterised `SELECT ... WHERE email = ?`.
- `create_user(name, email, password)` — hashes `password` with
  `werkzeug.security.generate_password_hash`, inserts the row with a
  parameterised `INSERT`, commits, and returns the new user's `id`. If the
  insert raises `sqlite3.IntegrityError` (duplicate email race), return `None`
  so the route can show the "already registered" error instead of a 500.

Both helpers open their own connection via `get_db()` and close it in a
`finally` block, matching the style of `init_db()` / `seed_db()`.

## Templates
- **Create:** none
- **Modify:**
  - `templates/register.html`
    - Change `action="/register"` to `action="{{ url_for('register') }}"`
      (CLAUDE.md forbids hardcoded URLs).
    - Re-populate inputs after a failed submit:
      `value="{{ name or '' }}"` and `value="{{ email or '' }}"`.
      Never re-populate the password field.
    - Add `minlength="8"` to the password input to match the placeholder and
      server-side rule.
  - `templates/login.html`
    - Render flashed messages above the form, e.g.
      `{% with messages = get_flashed_messages() %}` → each in a
      `<div class="auth-success">`. No other changes to the login page in this
      step (its form action is the login step's concern).

## Files to change
- `app.py`
  - Import `request`, `redirect`, `url_for`, `flash` from `flask` and `os`.
  - Set `app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")`
    (required for `flash`).
  - Import `create_user`, `get_user_by_email` from `database.db`.
  - Change `@app.route("/register")` to
    `@app.route("/register", methods=["GET", "POST"])` and implement the POST
    branch described below.
- `database/db.py` — add `get_user_by_email()` and `create_user()`.
- `templates/register.html` — see Templates.
- `templates/login.html` — see Templates.
- `static/css/style.css` — add an `.auth-success` class next to the existing
  `.auth-error`, using only CSS variables (`--accent`, `--accent-light`,
  `--radius-sm`, etc.).
- `CLAUDE.md` — update the "Implemented vs stub routes" table to list
  `POST /register` as implemented.

### POST /register behaviour
1. Read `name`, `email`, `password` from `request.form`; `.strip()` name and
   email; lowercase email.
2. Validate, stopping at the first failure and re-rendering `register.html`
   with `error=...`, `name=...`, `email=...` and HTTP status 400:
   - any field empty → "All fields are required."
   - email missing `@` or `.` after it → "Please enter a valid email address."
   - password shorter than 8 characters → "Password must be at least 8 characters."
   - `get_user_by_email(email)` returns a row → "An account with that email already exists."
3. Call `create_user(name, email, password)`. If it returns `None`, re-render
   with the "already exists" error (400).
4. On success: `flash("Account created — please sign in.")` and
   `redirect(url_for("login"))`.

## Files to create
- `tests/conftest.py` — pytest fixtures: monkeypatch `database.db.DB_PATH` to
  a `tmp_path` file, call `init_db()`, and yield `app.test_client()` so tests
  never touch the real `expense_tracker.db`.
- `tests/test_registration.py` — tests covering the Definition of done
  (successful registration, duplicate email, short password, missing fields,
  invalid email, password stored hashed, email normalised to lowercase).

## New dependencies
No new dependencies. `werkzeug` (hashing) and `pytest` / `pytest-flask`
(tests) are already in `requirements.txt`.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings or `%` in SQL
- Passwords hashed with werkzeug (`generate_password_hash`); never store,
  log, flash or re-render the plaintext password
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- All DB access lives in `database/db.py`; `app.py` calls helpers only
- Use `url_for()` for every internal link and form action
- Do not log the user in or touch `session` — that is the login/logout step
- Do not implement or modify any stub route (`/logout`, `/profile`,
  `/expenses/...`)
- Keep the app on port 5001
- PEP 8, snake_case

## Definition of done
- [ ] `python app.py` starts on port 5001 with no errors
- [ ] `GET /register` still renders the form
- [ ] Submitting valid name/email/password creates a row in `users` and
      redirects to `/login`, which shows "Account created — please sign in."
- [ ] The stored `password_hash` is a werkzeug hash (e.g. starts with
      `scrypt:` or `pbkdf2:`), never the plaintext password
- [ ] Registering `Foo@Example.com` stores `foo@example.com`
- [ ] Registering with an email that already exists (e.g. `demo@spendly.com`)
      re-renders the form with "An account with that email already exists."
      and no new row is created
- [ ] A password under 8 characters re-renders the form with the length error
- [ ] Submitting with any field blank (bypassing browser validation) shows
      "All fields are required."
- [ ] After any validation error, name and email are still filled in and the
      password field is empty
- [ ] The register form's action uses `url_for('register')` — no hardcoded URLs
- [ ] The success message is styled via `.auth-success` using only CSS variables
- [ ] `/logout`, `/profile` and `/expenses/...` stubs are unchanged
- [ ] `pytest` passes, and the tests do not modify `expense_tracker.db`
