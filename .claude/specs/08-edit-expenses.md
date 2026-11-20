# Spec: Edit Expenses

## Overview
Step 8 lets a logged-in user correct an expense they have already recorded.
Step 7 added the first write path (`/expenses/add`), but a mistake can only be
fixed today by editing the database directly, and `/expenses/<id>/edit` is
still a stub that returns a plain string. This step turns that stub into a
real edit form. The form is pre-filled with the expense's stored values and
uses the same validation rules as the add form. On success it updates the row
and redirects to `/profile` with a confirmation flash. Each row in the
profile's Recent transactions table gets an "Edit" link. Ownership is enforced
in the database query: a user can only load or update their own expenses, and
any other id returns 404. Delete (Step 9) will reuse the per-row action column
and the ownership-scoped lookup added here.

## Depends on
- Step 1: Database setup (`expenses` table, `get_db()` with FK enforcement)
- Step 3: Login / Logout (`session["user_id"]` is set on login)
- Step 5: Backend routes for profile page (`get_recent_transactions`)
- Step 6: Date filter for profile page (`_parse_iso_date` helper)
- Step 7: Add expense (`validate_expense`, `EXPENSE_CATEGORIES`,
  `EXPENSE_FIELDS`, `static/css/expenses.css`, `_current_user`,
  `_login_redirect`)

## Routes
The existing stub `/expenses/<int:id>/edit` (endpoint `edit_expense`) is
replaced. It now accepts both methods:
- `GET /expenses/<int:id>/edit`: renders the edit form pre-filled with the
  stored amount (formatted to 2 decimal places), category, date and
  description (blank if `NULL`). Access: logged-in, owner only.
- `POST /expenses/<int:id>/edit`: validates the form with `validate_expense`.
  If it is valid, it updates the expense, flashes "Expense updated.", and
  redirects (302) to `/profile`. If it is invalid, it re-renders the form with
  status 400, an inline error, and the submitted values preserved. Access:
  logged-in, owner only.

Access handling for both methods, in this order:
1. **Auth.** Follow the `/expenses/add` pattern. If there is no `user_id` in
   the session, or the session's user no longer exists, the route flashes
   "Please sign in to edit an expense." and redirects to `/login`. This
   happens before any lookup, so a logged-out visitor cannot probe whether an
   id exists. A logged-out POST must never update a row.
2. **Ownership.** Load the expense with
   `get_expense_by_id(id, session["user_id"])`. If it returns `None`, because
   the id does not exist or it belongs to another user, call `abort(404)`.
   Both cases return the same 404 so a user cannot learn which ids exist.
3. On POST, if `update_expense` reports that no row changed (the row was
   deleted between the lookup and the update), also `abort(404)`.

## Database changes
No schema changes. The existing `expenses` table already has every column
needed.

New and changed helpers in `database/db.py`. Each new helper uses the
`get_db()` / `try` / `finally: conn.close()` pattern like the others:
- **New** `get_expense_by_id(expense_id, user_id)` returns
  `{id, amount, category, date, description}` as a plain dict, or `None`.
  The query is `... WHERE id = ? AND user_id = ?`, so ownership is enforced in
  SQL and not in Python.
- **New** `update_expense(expense_id, user_id, amount, category, date,
  description=None)` runs a parameterised
  `UPDATE expenses SET amount = ?, category = ?, date = ?, description = ?
  WHERE id = ? AND user_id = ?`, commits, and returns `True` if exactly one row
  was updated (`cur.rowcount == 1`), otherwise `False`. It does not validate,
  because callers validate first. It never changes `user_id` or `created_at`.
- **Changed** `get_recent_transactions` also selects `id`, so each returned
  dict is `{id, date, description, category, amount}`. The profile template
  needs the id to build edit links. Ordering, limit and date-filter behaviour
  stay the same.

## Templates
- **Create:** `templates/edit_expense.html`
  - Extends `base.html`. Loads `static/css/expenses.css` via
    `{% block head %}`, reusing the Step 7 classes (`.expense-section`,
    `.expense-card`, `.expense-fields`, `.expense-amount`, `.expense-actions`
    and so on).
  - Page title "Edit expense — Spendly". Card heading "Edit expense" with the
    subtitle "Update the details of this expense."
  - `<form method="post" action="{{ url_for('edit_expense', id=expense_id) }}">`
    with the same four fields as the add form: amount with a ₹ prefix,
    category select with options from the route, date, and an optional
    description with `maxlength`. Every field is pre-filled from `values`.
  - The category select has no disabled placeholder selected, because the
    stored category is always pre-selected. If a stored category is not in
    `EXPENSE_CATEGORIES` (legacy data), render a disabled "Choose a category"
    placeholder as selected, so the user must pick a valid one.
  - The date input's `max` is `date_max` from the route (see the date rule
    under "Validation rules").
  - A "Save changes" submit button (`btn-primary`) and a "Cancel" link to
    `url_for('profile')` (`btn-ghost`).
  - When `error` is set, show it above the form using the existing
    `.auth-error` styling with `role="alert"`.
- **Modify:** `templates/profile.html`
  - Add a fifth column to the Recent transactions table: header
    `<th scope="col"><span class="visually-hidden">Actions</span></th>`, or an
    equivalent accessible label using existing utility styles. Add a cell per
    row with an "Edit" link to `url_for('edit_expense', id=tx.id)`. The link
    has an `aria-label` such as "Edit Groceries on 2026-11-03", built from the
    description (or category if the description is blank) and the date.
  - Change the empty-state row's `colspan` from 4 to 5.
  - Style the link in `static/css/profile.css` as a small, quiet text or ghost
    action that does not widen the table on mobile, using CSS variables only.

## Files to change
- `app.py`
  - Import `abort` from flask, and `get_expense_by_id` and `update_expense`
    from `database.db`.
  - Add the message constants `EDIT_EXPENSE_LOGIN_REQUIRED = "Please sign in
    to edit an expense."` and `EXPENSE_UPDATED = "Expense updated."`.
  - Extend `validate_expense(form, today, allowed_date=None)`. When
    `allowed_date` (an ISO string) is given and the submitted date equals it
    exactly, skip the "future date" check. All other rules and their order are
    unchanged, and the add route keeps calling it without `allowed_date`.
  - Add a helper `_expense_form_values(expense)` that turns a stored expense
    into form values: amount as `f"{amount:.2f}"`, description `None` → `""`.
  - Add a helper `_render_edit_expense(expense_id, values, date_max,
    error=None, status=200)` that mirrors `_render_add_expense`.
  - Replace the `edit_expense` stub with
    `@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])`. The
    route body stays thin: auth check → ownership lookup (404) → render (GET),
    or validate → update → flash → redirect (POST).
- `database/db.py`: add `get_expense_by_id` and `update_expense`, and add
  `id` to `get_recent_transactions`, as described above.
- `templates/profile.html`: Actions column with per-row Edit links, and
  `colspan` 5.
- `static/css/profile.css`: styles for the Edit link and Actions column.
- `tests/test_auth.py`: remove only the `("/expenses/1/edit", ...)` case from
  `test_expense_stubs_unchanged`. The Step 9 delete case stays.
- `tests/test_add_expense.py`: remove only the `("/expenses/1/edit", ...)`
  case from `test_later_stubs_unchanged`. The Step 9 delete case stays.
- `tests/test_backend_connection.py`: in
  `test_recent_transactions_ordered_newest_first` and
  `test_recent_transactions_scoped_to_user`, add the `id` key to the expected
  dicts (or compare with `id` stripped). This is the only change to those
  tests, and it reflects the deliberate contract change to
  `get_recent_transactions`.
- `CLAUDE.md`
  - Change the `GET /expenses/<id>/edit` route-table row to "Implemented" and
    describe the GET/POST, 404 and auth behaviour, as with the Step 7 rows.
  - Add `get_expense_by_id` and `update_expense` to the list of existing
    `database/db.py` helpers in "Warnings and things to avoid".

## Files to create
- `templates/edit_expense.html`
- `tests/test_edit_expense.py`

## New dependencies
No new dependencies.

## Validation rules
Reuse `validate_expense` from Step 7 with the same rules, the same order, and
the same error messages: amount, then category, then date, then description.
The only difference is the date rule:
- **Date** must still be a strict `YYYY-MM-DD` value. It must not be later
  than `today`, **unless it is unchanged** from the expense's stored date.
  The route passes `allowed_date=expense["date"]`. This lets a user edit the
  amount or description of an expense that already has a future date (for
  example, seed rows later in the current month) without being forced to
  change its date. Moving an expense *to* a new future date is still rejected
  with "Date cannot be in the future."
- The route passes the date input's `max` as `date_max = max(today, stored
  date)`, as ISO strings, so the browser does not block an unchanged future
  date either.

## Rules for implementation
- No SQLAlchemy or ORMs. Use raw `sqlite3` via `get_db()` only.
- Parameterised queries only. All values, including `id` and `user_id`, go
  through `?` placeholders. Never use f-strings or `%` formatting in SQL.
- Passwords hashed with werkzeug. Auth is untouched in this step.
- Use CSS variables and never hardcode hex values. New styles go in
  `static/css/profile.css` (Edit link) or `static/css/expenses.css` (only if
  the edit form needs something the add form doesn't). No inline `style=`
  attributes or `<style>` tags.
- All templates extend `base.html`.
- Use `url_for()` for every link and form action, including
  `url_for('edit_expense', id=...)`. Never hardcode URLs.
- DB logic lives only in `database/db.py`. The route calls
  `get_expense_by_id` and `update_expense` and never runs SQL inline.
- Ownership is enforced in SQL (`WHERE id = ? AND user_id = ?`) for both the
  lookup and the update. `user_id` always comes from the session, never from
  form data or the URL. Ignore any `user_id` or `id` field a client submits in
  the form body.
- A missing expense or one owned by someone else → `abort(404)`, never a raw
  string return, and never a 403 that would confirm the id exists.
- Server-side validation is authoritative. HTML attributes (`required`,
  `min`, `max`, `maxlength`) are a convenience only.
- Invalid input is user feedback, not `abort()`. Re-render the form with
  status 400, an inline error and the submitted values. The stored row must be
  unchanged.
- Use Post/Redirect/Get: a successful POST always redirects to `/profile`.
- Vanilla HTML only. The form must work with JavaScript disabled, and no new
  JS is required.
- Do not implement the Step 9 (`/expenses/<id>/delete`) stub route, and do not
  add Delete links to the profile table yet.
- Do not edit or weaken existing tests, except for the three test-file changes
  listed in "Files to change".

## Definition of done
- [ ] Logged out, `GET /expenses/1/edit` redirects to `/login` and shows "Please sign in to edit an expense."
- [ ] Logged out, `POST /expenses/1/edit` with valid data redirects to `/login` and changes no row
- [ ] Logged out, `GET /expenses/999999/edit` also redirects to `/login`, not 404
- [ ] Logged in as demo@spendly.com / demo123, every row in Recent transactions on `/profile` has an "Edit" link pointing to that expense's `/expenses/<id>/edit`
- [ ] The edit form for "Groceries" shows amount `45.50`, category "Food" selected, its stored date, and description "Groceries", plus Save changes and Cancel
- [ ] The edit form for the seed expense with no description shows an empty description field, not "None"
- [ ] Changing Groceries to ₹50.00 and saving redirects to `/profile`, shows "Expense updated.", and the total changes from ₹1,484.24 to ₹1,488.74 while the transaction count stays at 8
- [ ] The edited row shows the new amount, and its `created_at` and `user_id` are unchanged in the database
- [ ] Changing the category or date moves the expense in the category breakdown or date order as expected
- [ ] Clearing the description and saving stores `NULL`
- [ ] Amounts `0`, `-5`, `abc`, `nan`, `12.345` and `20000000` each return 400 with the matching inline error, keep the submitted values in the form, and leave the stored row unchanged
- [ ] A category outside the allowed list returns 400 with "Please choose a category."
- [ ] A malformed date (`2026-13-01`) returns 400 with "Please enter a valid date."
- [ ] Moving an expense to a new future date returns 400 with "Date cannot be in the future."
- [ ] Saving an expense whose stored date is already in the future, without changing that date, succeeds
- [ ] `GET` and `POST /expenses/<id>/edit` for a non-existent id return 404 when logged in
- [ ] `GET` and `POST /expenses/<id>/edit` for another user's expense return 404, and the POST does not modify that expense
- [ ] A `user_id` field added to the POST body is ignored, and the expense stays owned by the session user
- [ ] Refreshing `/profile` after the redirect does not resubmit the edit
- [ ] Cancel returns to `/profile` without saving
- [ ] Below 640px the edit form is single-column and the profile table with its Edit column causes no horizontal page scroll
- [ ] `/expenses/1/delete` still returns its Step 9 stub string
- [ ] `pytest` passes, including all existing Step 1–7 tests (with only the listed adjustments) and the new `tests/test_edit_expense.py`
