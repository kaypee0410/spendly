# Spec: Delete Expenses

## Overview
Step 9 lets a logged-in user remove an expense they recorded by mistake.
Steps 7 and 8 added creating and editing expenses, but the only way to remove
one today is to edit the database by hand, and `/expenses/<id>/delete` is
still a stub that returns a plain string. This step replaces that stub with a
two-step delete. `GET /expenses/<id>/delete` shows a confirmation page with the
expense's details. `POST /expenses/<id>/delete` (with a CSRF token) deletes the
row and redirects to `/profile` with a confirmation flash. The delete itself
never happens on GET, so a link preview, prefetch, crawler or cross-site
`<img>` tag cannot destroy data. Each row in the profile's Recent transactions
table gets a "Delete" link next to the existing "Edit" link. Ownership is
enforced in SQL, exactly as in Step 8: a user can only see or delete their own
expenses, and any other id returns 404. This completes the expense CRUD set.

## Depends on
- Step 1: Database setup (`expenses` table, `get_db()` with FK enforcement)
- Step 3: Login / Logout (`session["user_id"]` is set on login)
- Step 5: Backend routes for profile page (`get_recent_transactions`,
  summary and category breakdown)
- Step 7: Add expense (`static/css/expenses.css`, `_current_user`,
  `_login_redirect`, the `inr` and `short_date` filters)
- Step 8: Edit expenses (`get_expense_by_id`, the profile Actions column,
  `.profile-edit-link`, CSRF protection via `check_csrf()` / `csrf_token()`)

## Routes
The existing stub `/expenses/<int:id>/delete` (endpoint `delete_expense`) is
replaced. It now accepts both methods:
- `GET /expenses/<int:id>/delete`: renders a confirmation page showing the
  expense's date, description (or "—" if `NULL`), category and amount, with a
  "Delete expense" submit button and a "Cancel" link. It changes nothing.
  Access: logged-in, owner only.
- `POST /expenses/<int:id>/delete`: deletes the expense, flashes
  "Expense deleted.", and redirects (302) to `/profile`. The form body carries
  only `csrf_token`; any other field is ignored. Access: logged-in, owner only.

Access handling for both methods, in this order:
1. **CSRF (POST only).** The existing `check_csrf()` before-request hook
   rejects a POST without a valid token with 400 before the route runs. No
   change is needed to the hook; the confirmation form must include the
   hidden `csrf_token` field.
2. **Auth.** Follow the `/expenses/<id>/edit` pattern. If there is no
   `user_id` in the session, or the session's user no longer exists, flash
   "Please sign in to delete an expense." and redirect to `/login`. This
   happens before any lookup or delete, so a logged-out visitor cannot probe
   whether an id exists, and a logged-out POST never deletes a row.
3. **Ownership.**
   - GET: load the expense with `get_expense_by_id(id, session["user_id"])`.
     If it returns `None` (missing id or another user's expense), call
     `abort(404)`.
   - POST: call `delete_expense(id, session["user_id"])` directly; it is
     scoped to the owner in SQL. If it returns `False` (missing id, another
     user's expense, or already deleted), call `abort(404)`. Deleting the same
     id twice therefore returns 404 the second time.

Both "missing" and "someone else's" return the same 404, so a user cannot
learn which ids exist.

## Database changes
No schema changes. The `expenses` table already has every column needed, and
no other table references `expenses`, so there is nothing to cascade.

New helper in `database/db.py`, using the same
`get_db()` / `try` / `finally: conn.close()` pattern as the others:
- **New** `delete_expense(expense_id, user_id)` runs the parameterised
  `DELETE FROM expenses WHERE id = ? AND user_id = ?`, commits, and returns
  `True` if exactly one row was deleted (`cur.rowcount == 1`), otherwise
  `False`. Like `get_expense_by_id`, it catches `OverflowError` (an id beyond
  SQLite's 64-bit INTEGER) and returns `False`. It must never delete more
  than the one row.

No other helper changes. `get_recent_transactions` already returns `id`
(Step 8).

## Templates
- **Create:** `templates/delete_expense.html`
  - Extends `base.html`. Loads `static/css/expenses.css` via
    `{% block head %}` and reuses the Step 7/8 card classes
    (`.expense-section`, `.expense-card`, `.expense-header`,
    `.expense-title`, `.expense-subtitle`, `.expense-actions`,
    `.expense-action`).
  - Page title "Delete expense — Spendly". Card heading "Delete expense" with
    the subtitle "This permanently removes the expense. This can't be undone."
  - A read-only summary of the expense as a definition list (`<dl>`):
    Date (via the `short_date` filter), Description (or "—" if blank),
    Category, Amount (via the `inr` filter). Values are auto-escaped by
    Jinja; never mark the description `|safe`.
  - `<form method="post" action="{{ url_for('delete_expense', id=expense.id) }}">`
    containing only
    `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`,
    a "Delete expense" submit button styled as a destructive action, and a
    "Cancel" link to `url_for('profile')` (`btn-ghost`).
  - The page works with JavaScript disabled; no `confirm()` dialog and no
    new JS.
- **Modify:** `templates/profile.html`
  - In each Recent transactions row's `.profile-actions` cell, add a
    "Delete" link to `url_for('delete_expense', id=tx.id)` after the existing
    Edit link. Give it an `aria-label` built the same way as the Edit link,
    e.g. "Delete Groceries on 2026-11-03" (description, or category if the
    description is blank, plus the date).
  - Header, column count and empty-state `colspan` (5) stay as they are.

## Files to change
- `app.py`
  - Import `delete_expense` from `database.db`. Because the route function
    is also named `delete_expense` (its endpoint name is used by
    `url_for('delete_expense', ...)` and must stay unchanged), import the
    helper under an alias, e.g. `from database.db import delete_expense as
    db_delete_expense`, so the route does not shadow it.
  - Add the message constants
    `DELETE_EXPENSE_LOGIN_REQUIRED = "Please sign in to delete an expense."`
    and `EXPENSE_DELETED = "Expense deleted."` next to the other expense
    messages, and update the section comment to cover Step 9.
  - Replace the stub with
    `@app.route("/expenses/<int:id>/delete", methods=["GET", "POST"])`.
    The route body stays thin: auth check → GET: ownership lookup (404) →
    render confirmation; POST: delete (404 if nothing deleted) → flash →
    redirect.
  - Remove the now-empty "Placeholder routes" section header.
- `database/db.py`: add `delete_expense` under "Expense writes", as
  described above.
- `templates/profile.html`: per-row Delete link.
- `static/css/profile.css`: style the Delete link as a small, quiet text
  action matching `.profile-edit-link` (same size and padding), with a
  destructive hover/focus state using `var(--danger)` and
  `var(--danger-light)`. Keep a small gap between the two links, and keep the
  Actions column from widening the table on mobile (no horizontal page scroll
  below 640px).
- `static/css/expenses.css`: styles for the confirmation summary (`<dl>`
  layout) and a destructive submit button variant (e.g. `.expense-danger`)
  using `var(--danger)` / `var(--danger-light)` and existing tokens only.
- `tests/test_auth.py`: remove only the `("/expenses/1/delete", ...)` case
  from `test_expense_stubs_unchanged` (delete the test if it becomes empty).
- `tests/test_add_expense.py`: remove only the `("/expenses/1/delete", ...)`
  case from `test_later_stubs_unchanged` (delete the test if it becomes
  empty).
- `tests/test_edit_expense.py`: remove `test_no_delete_links_yet` and
  `test_delete_stub_unchanged`, which assert Step 8's "not yet" state.
- `CLAUDE.md`
  - Change the `GET /expenses/<id>/delete` route-table row to "Implemented"
    and add a `POST /expenses/<id>/delete` row, describing the confirmation
    page, the POST delete + flash + redirect, the 404 and the auth behaviour,
    as with the Step 8 rows.
  - Add `delete_expense` to the list of existing `database/db.py` helpers in
    "Warnings and things to avoid".

## Files to create
- `templates/delete_expense.html`
- `tests/test_delete_expense.py`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs. Use raw `sqlite3` via `get_db()` only.
- Parameterised queries only. `id` and `user_id` go through `?`
  placeholders. Never use f-strings or `%` formatting in SQL.
- Passwords hashed with werkzeug. Auth is untouched in this step.
- Use CSS variables and never hardcode hex values (use `--danger` /
  `--danger-light` from `style.css` for destructive styling). No inline
  `style=` attributes or `<style>` tags.
- All templates extend `base.html`.
- Use `url_for()` for every link and form action, including
  `url_for('delete_expense', id=...)`. Never hardcode URLs.
- DB logic lives only in `database/db.py`. The route calls
  `get_expense_by_id` and `delete_expense` and never runs SQL inline.
- GET never modifies data. The delete happens only on a POST that passed
  `check_csrf()`. Do not add a "delete on GET" shortcut or a `?confirm=1`
  query parameter.
- Ownership is enforced in SQL (`WHERE id = ? AND user_id = ?`) for both the
  lookup and the delete. `user_id` always comes from the session, never from
  form data, query args or the URL. Ignore any `user_id` field a client
  submits.
- A missing expense or one owned by someone else → `abort(404)`, never a
  raw string return, and never a 403 that would confirm the id exists.
- Use Post/Redirect/Get: a successful POST always redirects to `/profile`.
- Hard delete only — no soft-delete column, no undo, no bulk delete.
- Vanilla HTML only. Both pages work with JavaScript disabled, and no new JS
  is required.
- Do not edit or weaken existing tests, except for the test-file changes
  listed in "Files to change".

## Definition of done
- [ ] Logged out, `GET /expenses/1/delete` redirects to `/login` and shows "Please sign in to delete an expense."
- [ ] Logged out, `POST /expenses/1/delete` redirects to `/login` and deletes no row
- [ ] Logged out, `GET /expenses/999999/delete` also redirects to `/login`, not 404
- [ ] Logged in as demo@spendly.com / demo123, every row in Recent transactions on `/profile` has both an "Edit" and a "Delete" link; the Delete link points to that expense's `/expenses/<id>/delete`
- [ ] Clicking Delete on "Groceries" shows a confirmation page with its date, description "Groceries", category "Food" and amount ₹45.50, plus "Delete expense" and "Cancel"
- [ ] The confirmation page for the seed expense with no description shows "—", not "None"
- [ ] Visiting the confirmation page alone (GET) leaves the row in the database
- [ ] Cancel returns to `/profile` and the expense is still listed
- [ ] Confirming the Groceries delete redirects to `/profile`, shows "Expense deleted.", the row is gone, the total changes from ₹1,484.24 to ₹1,438.74 and the transaction count changes from 8 to 7
- [ ] Deleting the only expense in a category removes that category from "Spending by category", and the remaining percentages still sum to 100
- [ ] Deleting every expense shows "No expenses yet." and a total of ₹0.00
- [ ] `POST /expenses/<id>/delete` for an id that was already deleted returns 404
- [ ] `GET` and `POST /expenses/<id>/delete` for a non-existent id return 404 when logged in
- [ ] `GET` and `POST /expenses/<id>/delete` for another user's expense return 404, and that expense still exists afterwards
- [ ] A `user_id` field added to the POST body is ignored; only the session user's expense can be deleted
- [ ] With CSRF enabled, `POST /expenses/<id>/delete` without a token, or with a wrong one, returns 400 and deletes nothing
- [ ] Refreshing `/profile` after the redirect does not resubmit the delete
- [ ] Below 640px the confirmation page is single-column and the profile table with Edit and Delete links causes no horizontal page scroll
- [ ] `pytest` passes, including all existing Step 1–8 tests (with only the listed adjustments) and the new `tests/test_delete_expense.py`
