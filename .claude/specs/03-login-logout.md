# Spec: Login and Logout

## Overview
Let registered users sign in and out. Today `GET /login` renders `login.html`,
but its form posts to a route that only accepts `GET` (405), and `/logout` is a
stub that returns a plain string. This step adds a `POST /login` handler that
checks the submitted email and password against the werkzeug hash stored in
`users`, starts a Flask session for the user, and redirects them to their
profile. It also implements `GET /logout`, which clears the session and sends
the user back to the sign-in page. The shared navbar changes with login state.
Login comes right after registration (Step 2) because every later feature —
profile (Step 4) and all expense CRUD (Steps 7–9) — needs to know who the
current user is.

## Depends on
- **Step 1 — Database setup** (`.claude/specs/01-database-setup.md`): the
  `users` table, `get_db()` with `PRAGMA foreign_keys = ON`, and the seeded
  demo user (`demo@spendly.com` / `demo123`).
- **Step 2 — Registration** (`.claude/specs/02-registration.md`):
  `get_user_by_email()`, werkzeug-hashed passwords, `app.secret_key`, and the
  flashed-message block plus `.auth-success` style already on `login.html`.

## Routes
- `POST /login` — validate the form, verify the credentials, store the user in
  the session, and redirect to `url_for('profile')`. On failure, re-render
  `login.html` with an error and the email the user entered — public
- `GET /login` — already implemented; extend the existing `login()` view to
  `methods=["GET", "POST"]` rather than adding a second function. If the user
  is already logged in, redirect to `url_for('profile')` — public
- `GET /logout` — replace the stub: clear the session, flash
  "You have been signed out.", and redirect to `url_for('login')`. Safe to call
  when nobody is logged in (it still redirects) — public
- `GET /register` — no new route; if the user is already logged in, redirect
  to `url_for('profile')` instead of showing the form — public

`/profile` stays a stub (Step 4). Redirecting to it after login is expected; do
not implement it here. `/expenses/...` stubs must be left untouched.

## Database changes
No database changes. The `users` table already has `id`, `name`, `email`, and
`password_hash`.

Add one helper to `database/db.py` (no schema change):

- `authenticate_user(email, password)` — call `get_user_by_email(email)`. If a
  row is found and `werkzeug.security.check_password_hash(row["password_hash"],
  password)` is true, return the row. Otherwise return `None`. Hashing stays in
  `db.py` next to `create_user()`, so `app.py` never handles password hashes.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html`
    - Change `action="/login"` to `action="{{ url_for('login') }}"`, because
      CLAUDE.md forbids hardcoded URLs.
    - Fill the email back in after a failed submit:
      `value="{{ email or '' }}"`. Never fill the password field back in.
    - Leave the existing flash block and `{% if error %}` block as they are.
  - `templates/base.html`: make the navbar depend on login state, using the
    Jinja `session` global.
    - Logged in (`session.get('user_id')`): show a greeting
      `<span class="nav-user">Hi, {{ session.get('user_name') }}</span>` and a
      "Sign out" link to `url_for('logout')` with class `nav-cta`. It needs
      `nav-cta` so it stays visible on mobile, where `.nav-links
      a:not(.nav-cta)` is hidden.
    - Logged out: keep the current "Sign in" and "Get started" links unchanged.

## Files to change
- `app.py`
  - Import `session` from `flask` and `authenticate_user` from `database.db`.
  - Set `app.config["SESSION_COOKIE_SAMESITE"] = "Lax"` next to
    `app.secret_key`. Flask already sets `SESSION_COOKIE_HTTPONLY` to `True`
    by default.
  - Change `@app.route("/login")` to
    `@app.route("/login", methods=["GET", "POST"])` and implement the POST
    branch (see below).
  - Add the "already logged in → redirect to profile" check to the GET path of
    `login()` and `register()`.
  - Replace the `logout()` stub body (see below).
- `database/db.py`: add `authenticate_user()` and import
  `check_password_hash`.
- `templates/login.html`: see Templates.
- `templates/base.html`: see Templates.
- `static/css/style.css`: add a `.nav-user` class (muted text, for example
  `color: var(--ink-muted)`) using only CSS variables.
- `CLAUDE.md`: update the "Implemented vs stub routes" table to list
  `POST /login` and `GET /logout` as implemented.

### POST /login behaviour
1. Read `email` and `password` from `request.form`. Strip and lowercase the
   email; do not strip the password.
2. If either field is empty, re-render `login.html` with
   `error="All fields are required."`, `email=email`, and HTTP 400.
3. Call `authenticate_user(email, password)`. If it returns `None`, re-render
   `login.html` with `error="Invalid email or password."`, `email=email`, and
   HTTP 401. Use this same generic message for an unknown email and for a
   wrong password, so the page never reveals which emails are registered.
4. On success, call `session.clear()` first (this prevents session fixation),
   then set `session["user_id"] = user["id"]` and
   `session["user_name"] = user["name"]`.
5. `redirect(url_for("profile"))`.

### GET /logout behaviour
1. `session.clear()`
2. `flash("You have been signed out.")`
3. `redirect(url_for("login"))`. The login page already renders flashed
   messages.

## Files to create
- `tests/test_auth.py`: tests covering the Definition of done. Reuse the
  existing `app` and `client` fixtures from `tests/conftest.py` (temporary
  DB, seeded demo user). Cover successful login (session set, redirect to
  `/profile`), wrong password, unknown email, missing fields, email
  case-insensitivity, logout clearing the session, logout while logged out,
  logged-in users being redirected away from `/login` and `/register`, and the
  navbar rendering for each state.

## New dependencies
No new dependencies. Flask sessions, `werkzeug.security.check_password_hash`,
and `pytest` / `pytest-flask` are already available through
`requirements.txt`.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders), never f-strings or `%` in SQL
- Passwords hashed with werkzeug: check them with `check_password_hash`, and
  never store, log, flash, or re-render the plaintext password
- Use CSS variables and never hardcode hex values
- All templates extend `base.html`
- All DB access and password-hash checking live in `database/db.py`;
  `app.py` only calls helpers
- Use `url_for()` for every internal link, form action, and redirect
- Store only `user_id` and `user_name` in the session, never the password
  hash or the whole row
- Call `session.clear()` before setting the session on login
- Use one generic error for bad credentials ("Invalid email or password.")
- No `next=` redirect parameter in this step, so there is no open-redirect
  surface
- Do not implement `/profile` or any `/expenses/...` stub route
- Keep the app on port 5001
- PEP 8, snake_case

## Definition of done
- [ ] `python app.py` starts on port 5001 with no errors
- [ ] `GET /login` still renders the sign-in form when logged out
- [ ] Signing in as `demo@spendly.com` / `demo123` redirects to `/profile`
      and the session contains `user_id` and `user_name`
- [ ] Signing in as `DEMO@Spendly.com` / `demo123` also works
- [ ] A wrong password re-renders the form with "Invalid email or password."
      (HTTP 401), keeps the email filled in, leaves the password field empty,
      and sets no session
- [ ] An unknown email shows the same "Invalid email or password." message
- [ ] Submitting with a blank field (bypassing browser validation) shows
      "All fields are required." (HTTP 400)
- [ ] A user who just registered can sign in with their new credentials
- [ ] When logged in, the navbar shows "Hi, <name>" and a "Sign out" link, and
      hides "Sign in" / "Get started"
- [ ] When logged out, the navbar shows "Sign in" / "Get started" as before
- [ ] Visiting `/login` or `/register` while logged in redirects to `/profile`
- [ ] Clicking "Sign out" clears the session, redirects to `/login`, and shows
      "You have been signed out."
- [ ] Visiting `/logout` while logged out still redirects to `/login` without
      an error
- [ ] The login form's action uses `url_for('login')`, with no hardcoded URLs
- [ ] `.nav-user` uses only CSS variables
- [ ] `/profile` and the `/expenses/...` stubs are unchanged
- [ ] `pytest` passes (including the existing registration tests), and the
      tests do not modify `expense_tracker.db`
