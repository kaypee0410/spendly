# Spec: Add Expense

## Overview
Step 7 lets a logged-in user record a new expense. So far the only expenses
in the app come from `seed_db()`, and `/expenses/add` is a stub that returns
a plain string. This step turns `/expenses/add` into a real form page with
amount, category, date and an optional description. It validates the input
server-side and inserts a row into the existing `expenses` table for the
current user. On success it redirects to `/profile` with a confirmation
flash, so the new expense shows up right away in the summary stats, recent
transactions and category breakdown. This is the first write path for
expense data. Edit (Step 8) and delete (Step 9) build on the form,
validation and styles introduced here.

## Depends on
- Step 1: Database setup (`expenses` table, `get_db()` with FK enforcement)
- Step 3: Login / Logout (`session["user_id"]` is set on login)
- Step 4: Profile page design (`templates/profile.html`, `static/css/profile.css`)
- Step 5: Backend routes for profile page (profile reads live expense data)
- Step 6: Date filter for profile page (`_parse_iso_date` helper in `app.py`)

## Routes
The existing stub `/expenses/add` (endpoint `add_expense`) is replaced. It
now accepts both methods:
- `GET /expenses/add`: renders the add-expense form. The date is pre-filled
  with today and the category is left unselected. Access: logged-in only.
- `POST /expenses/add`: validates the form. If it is valid, it inserts the
  expense for `session["user_id"]`, flashes "Expense added.", and redirects
  (302) to `/profile`. If it is invalid, it re-renders the form with status
  400, an inline error, and the submitted values preserved. Access:
  logged-in only.

Auth handling for both methods follows the `/analytics` pattern. If there is
no `user_id` in the session, or the session's user no longer exists, the
route clears the session, flashes "Please sign in to add an expense.", and
redirects to `/login`. A logged-out POST must never insert a row.

## Database changes
No schema changes. The existing `expenses` table already has every column
needed: `user_id`, `amount`, `category`, `date`, `description` and
`created_at` (defaulted).

New helper in `database/db.py`:
- `create_expense(user_id, amount, category, date, description=None)` inserts
  one row with a parameterised `INSERT`, commits, and returns the new
  `lastrowid`. It uses the `get_db()` / `try` / `finally: conn.close()`
  pattern like the other helpers. It does not validate: the route-side helper
  validates first. If `user_id` does not exist, the FK constraint raises
  `sqlite3.IntegrityError`. The route never reaches this case, because it
  checks the user first.

## Templates
- **Create:** `templates/add_expense.html`
  - Extends `base.html`. Loads `static/css/expenses.css` via
    `{% block head %}`.
  - A card with the heading "Add expense" and a
    `<form method="post" action="{{ url_for('add_expense') }}">` containing:
    - Amount: `<input type="number" name="amount" step="0.01" min="0.01" required>`
      with a visible `<label>` and a ₹ prefix.
    - Category: a `<select name="category" required>` with a disabled
      "Choose a category" placeholder option, then one option per allowed
      category (passed in from the route, never hardcoded in the template).
    - Date: `<input type="date" name="date" required>`, pre-filled with today
      on GET and with the submitted value on error. `max` is set to today.
    - Description: `<input type="text" name="description" maxlength="200">`,
      marked "(optional)" in its label.
    - A "Save expense" submit button (`btn-primary`) and a "Cancel" link to
      `url_for('profile')` (`btn-ghost`).
  - When `error` is set, show it above the form using the existing
    `.auth-error` styling with `role="alert"`.
  - Reuse existing `.form-group` / `.form-input` classes from `style.css`
    where they fit.
- **Modify:** `templates/profile.html`
  - Add an "Add expense" button-style link (`url_for('add_expense')`) in the
    profile header area so it is visible without scrolling.
  - Render flashed messages (`get_flashed_messages()`) near the top of the
    page using the existing `.auth-success` styling, so "Expense added." is
    visible after the redirect.

## Files to change
- `app.py`
  - Add a module constant `EXPENSE_CATEGORIES = ["Food", "Transport", "Bills",
    "Health", "Entertainment", "Shopping", "Other"]`. It matches the seed
    data, and Step 8 will reuse it.
  - Add message constants: `ADD_EXPENSE_LOGIN_REQUIRED`, `EXPENSE_ADDED`, and
    one per validation error (see "Validation rules" below).
  - Add a helper `validate_expense(form, today)`. It returns
    `(clean, error)`, where `clean` is a dict
    `{amount, category, date, description}` ready for `create_expense`, or
    `None` on error. `today` is passed in so the helper is testable. Parse
    the amount with `decimal.Decimal` (standard library).
  - Replace the `add_expense` stub with
    `@app.route("/expenses/add", methods=["GET", "POST"])`. The route body
    stays thin: auth check, then render (GET), or validate → create →
    flash → redirect (POST).
- `database/db.py`: add `create_expense` as described above.
- `templates/profile.html`: "Add expense" link and flash message display.
- `tests/test_auth.py`: remove only the `("/expenses/add", ...)` case from
  `test_expense_stubs_unchanged`. The Step 8 and Step 9 stub cases stay.
- `CLAUDE.md`
  - Change the `GET /expenses/add` route-table row to "Implemented" and
    describe GET/POST behaviour.
  - Add `create_expense` to the list of existing `database/db.py` helpers in
    "Warnings and things to avoid".

## Files to create
- `templates/add_expense.html`
- `static/css/expenses.css`: form card layout, the ₹ amount prefix, and the
  button row. It is named for expenses in general so Step 8's edit form can
  reuse it.
- `tests/test_add_expense.py`

## New dependencies
No new dependencies. `decimal` and `datetime` are in the standard library.

## Validation rules
Apply these in `validate_expense`, in this order, returning the first error:
1. **Amount** is required, so `"Please enter an amount."` if it is blank.
   It must parse as a finite `Decimal`, rejecting `nan`, `inf` and
   non-numeric text with `"Please enter a valid amount."`. It must be
   `> 0` (`"Amount must be greater than zero."`), have at most 2 decimal
   places (`"Amount can have at most 2 decimal places."`), and be
   `<= 10,000,000` (`"Amount is too large."`). Store it as `float`.
   Amount strings longer than 20 characters are rejected with
   `"Please enter a valid amount."` before parsing, and request bodies over
   16 KB are refused with 413 (`MAX_CONTENT_LENGTH`), added after code review.
2. **Category** must be one of `EXPENSE_CATEGORIES`, matched exactly, or
   `"Please choose a category."`.
3. **Date** is required. It must be a strict `YYYY-MM-DD` value, reusing
   `_parse_iso_date`, and not later than `today`. Errors:
   `"Please enter a valid date."` and `"Date cannot be in the future."`.
4. **Description** is optional. It is stripped, and a blank value is stored
   as `NULL`. It may be at most 200 characters, or
   `"Description must be 200 characters or fewer."`.

## Rules for implementation
- No SQLAlchemy or ORMs. Use raw `sqlite3` via `get_db()` only.
- Parameterised queries only. All values go through `?` placeholders. Never
  use f-strings or `%` formatting in SQL.
- Passwords hashed with werkzeug. Auth is untouched in this step.
- Use CSS variables and never hardcode hex values. New styles go in
  `static/css/expenses.css`, with no inline `style=` attributes or `<style>`
  tags.
- All templates extend `base.html`.
- Use `url_for()` for every link and form action. Never hardcode URLs.
- DB logic lives only in `database/db.py`. The route calls
  `create_expense` and never runs SQL inline.
- The expense's `user_id` always comes from the session, never from form
  data. Ignore any `user_id` field a client submits.
- Server-side validation is authoritative. HTML attributes (`required`,
  `min`, `max`, `maxlength`) are a convenience only.
- Invalid input is user feedback, not `abort()`. Re-render the form with
  status 400, an inline error and the submitted values.
- Use Post/Redirect/Get: a successful POST always redirects, so a browser
  refresh does not create a duplicate expense.
- Vanilla HTML only. The form must work with JavaScript disabled, and no new
  JS is required.
- Currency still renders via the `inr` filter (₹) on the profile page.
- Do not implement the Step 8 (`/expenses/<id>/edit`) or Step 9
  (`/expenses/<id>/delete`) stub routes.
- Do not edit or weaken existing tests, except to remove the single
  `/expenses/add` stub case from `tests/test_auth.py`.

## Definition of done
- [ ] Logged out, `GET /expenses/add` redirects to `/login` and shows "Please sign in to add an expense."
- [ ] Logged out, `POST /expenses/add` with valid data redirects to `/login` and inserts no row
- [ ] Logged in as demo@spendly.com / demo123, `/profile` shows an "Add expense" link that opens `/expenses/add`
- [ ] The add form shows Amount, Category (7 options plus a placeholder), Date (pre-filled with today) and an optional Description, plus Save and Cancel
- [ ] Submitting ₹500.00 / Food / today / "Team dinner" redirects to `/profile`, shows "Expense added.", and the totals change from ₹1,484.24 / 8 transactions to ₹1,984.24 / 9 transactions
- [ ] The new expense appears in Recent transactions with its description, the "Food" badge and ₹500.00, above every seed expense dated today or earlier (seed rows dated later this month legitimately sort above it)
- [ ] Submitting with no description saves successfully and the row stores `NULL` for description
- [ ] Refreshing `/profile` after the redirect does not add a second expense
- [ ] Amounts `0`, `-5`, `abc`, `nan`, `12.345` and `20000000` each return 400 with the matching inline error, keep the other fields filled in, and insert nothing
- [ ] A category outside the allowed list (e.g. submitted with dev tools) returns 400 with "Please choose a category."
- [ ] A missing, malformed (`2026-13-01`) or future date returns 400 with the matching error
- [ ] A 201-character description returns 400 with "Description must be 200 characters or fewer."
- [ ] An expense added by one user never appears on another user's profile
- [ ] Cancel returns to `/profile` without saving
- [ ] Below 640px the form is single-column with no horizontal page scroll
- [ ] `/expenses/1/edit` and `/expenses/1/delete` still return their Step 8 and Step 9 stub strings
- [ ] `pytest` passes, including all existing Step 1–6 tests and the new `tests/test_add_expense.py`
