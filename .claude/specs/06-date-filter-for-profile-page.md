# Spec: Date Filter for Profile Page

## Overview
Step 6 lets a logged-in user narrow the profile page to a date range. Today
`/profile` always summarises every expense the user has ever recorded. This
step adds a small filter bar above the summary stats. It has a start date, an
end date, Apply and Clear actions, and a few one-click presets (This month,
Last 30 days, All time). The summary stats, recent transactions and category
breakdown are all recalculated for the chosen range. The filter is plain query
parameters on the existing `GET /profile` route, so a filtered view can be
bookmarked and needs no new routes or tables. Expense add, edit and delete
(Steps 7–9) will make the data grow, and this step gives users a way to read
their spending period by period first.

## Depends on
- Step 1: Database setup (`expenses.date` stored as ISO `YYYY-MM-DD` text)
- Step 3: Login / Logout (`session["user_id"]` is set on login)
- Step 4: Profile page design (`templates/profile.html`, `static/css/profile.css`)
- Step 5: Backend routes for profile page (`get_summary_stats`,
  `get_recent_transactions`, `get_category_breakdown` in `database/db.py`)

## Routes
No new routes. The existing route is extended:
- `GET /profile?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`: renders the
  profile with stats, transactions and categories limited to expenses whose
  `date` falls within the range, both ends inclusive. Access: logged-in only.
  The current redirect-to-login behaviour is unchanged.
  - Both parameters are optional. If only `start_date` is given, the range is
    open-ended (that date onward). If only `end_date` is given, the range is
    everything up to and including that date. If neither is given, there is no
    filter and the page behaves exactly as it does in Step 5.
  - Empty strings (e.g. `?start_date=&end_date=` from submitting a blank form)
    are treated as "not provided".
  - A value that is not a valid `YYYY-MM-DD` date returns status 400. The
    page still renders, with unfiltered data and the inline error
    "Please enter valid dates."
  - If `start_date` is after `end_date`, the route returns status 400. The
    page still renders, with unfiltered data and the inline error
    "Start date must be on or before end date."

## Database changes
No database changes. `expenses.date` is already stored as ISO `YYYY-MM-DD`
text, so inclusive string comparison (`date >= ?`, `date <= ?`) gives correct
date ordering.

Changes to existing helper signatures in `database/db.py`. They stay backward
compatible, so the Step 5 tests must keep passing unchanged:
- `get_summary_stats(user_id, start_date=None, end_date=None)`
- `get_recent_transactions(user_id, limit=10, start_date=None, end_date=None)`
- `get_category_breakdown(user_id, start_date=None, end_date=None)`

Add one private helper:
- `_date_range_clause(start_date, end_date)` returns `(sql_fragment, params)`.
  For example, `(" AND date >= ? AND date <= ?", [start, end])`, or `("", [])`
  when both bounds are `None`. The fragment is built only from constant
  strings and never contains user values. All three query helpers use it,
  including the top-category subquery in `get_summary_stats`.

## Templates
- **Create:** none
- **Modify:** `templates/profile.html`
  - Add a filter bar (`<form method="get" action="{{ url_for('profile') }}">`)
    between the user card and the summary stats. It contains:
    - `<input type="date" name="start_date">` and
      `<input type="date" name="end_date">`, each with a visible `<label>`.
      Both are pre-filled with the currently applied values.
    - An "Apply" submit button.
    - A "Clear" link to `url_for('profile')` (no query params).
    - Preset links built with
      `url_for('profile', start_date=..., end_date=...)`. "All time" links to
      `url_for('profile')`.
  - When a filter is active, show a short caption naming the range, e.g.
    "Showing 1 Nov 2026 – 10 Nov 2026", "Showing from 1 Nov 2026" or
    "Showing up to 10 Nov 2026".
  - When `error` is set, show it inline above the stats using the existing
    error/alert styling from `style.css`.
  - Empty-state text changes when a filter is active. It shows "No expenses in
    this period." instead of "No expenses yet." in both the transactions table
    and the category breakdown.

## Files to change
- `app.py`
  - Add a helper `parse_date_filter(args)`. It returns
    `(start_date, end_date, error)`, where the dates are ISO strings or `None`.
    It uses `date.fromisoformat` for validation.
  - Add a helper `build_date_presets(today)`. It returns a list of
    `{label, start_date, end_date}` dicts for "This month" (1st of the current
    month to today) and "Last 30 days" (today minus 29 days to today).
    `today` is passed in so the helper is testable.
  - `profile()`: read the filter from `request.args`. On error, fall back to
    unfiltered queries and return status 400. Otherwise pass the range to the
    three DB helpers. Pass `start_date`, `end_date`, `error`, `presets` and
    `filter_active` to the template. Route logic stays thin: parse, fetch,
    render.
- `database/db.py`: add `_date_range_clause` and extend the three query
  helpers as described above.
- `templates/profile.html`: filter bar, range caption, error message,
  filter-aware empty states.
- `static/css/profile.css`: filter bar layout. Inputs and buttons sit inline
  on desktop and stack under 640px. Presets are pill-style links.
- `CLAUDE.md`: update the `GET /profile` row in the route table to mention the
  optional `start_date` / `end_date` filter.

## Files to create
- `tests/test_date_filter.py`

## New dependencies
No new dependencies. `datetime` is in the standard library.

## Rules for implementation
- No SQLAlchemy or ORMs. Use raw `sqlite3` via `get_db()` only.
- Parameterised queries only. Date values always go through `?`
  placeholders. The SQL fragment from `_date_range_clause` is concatenated
  from constant strings. Never use f-strings or `%` formatting in SQL.
- Passwords hashed with werkzeug. Auth is untouched in this step.
- Use CSS variables and never hardcode hex values. New styles go in
  `static/css/profile.css`, with no inline `style=` attributes or `<style>`
  tags.
- All templates extend `base.html`.
- Use `url_for()` for every link, including presets and Clear. Never
  hand-build query strings.
- Vanilla HTML only. The filter must work with JavaScript disabled, as a plain
  GET form submit. No new JS is required.
- Date bounds are inclusive on both ends.
- Existing helper calls without date arguments must behave exactly as in
  Step 5. Do not edit or weaken existing tests, with one approved exception.
  The newest-first ordering assertion in
  `tests/test_backend_connection.py::test_profile_seed_user` is scoped to the
  transactions `<tbody>`, because preset links above the table also contain
  ISO dates.
- Validation lives in a helper, not in the route body. Invalid input is user
  feedback, not an `abort()`: render the page with an inline error and status
  400.
- Currency still renders via the `inr` filter (₹).
- Do not implement the Step 7–9 stub routes.

## Definition of done
- [ ] Logged in as demo@spendly.com / demo123, `/profile` with no query string shows the same numbers as before: ₹1,484.24 total, 8 transactions, top category "Bills"
- [ ] The filter bar is visible above the summary stats, with start date and end date inputs, an Apply button, a Clear link and presets
- [ ] Setting start = 1st and end = 10th of the seed month and clicking Apply shows ₹1,335.50 total, 4 transactions, top category "Bills", and 4 categories (Bills, Food, Transport, Health) whose percentages sum to 100
- [ ] After applying a filter, the URL contains `start_date` and `end_date`, the inputs stay pre-filled, and a "Showing …" caption names the range
- [ ] Reloading or bookmarking the filtered URL reproduces the same filtered view
- [ ] Setting only a start date of the 20th of the seed month shows 2 transactions (Food ₹18.75 and Other ₹15.00), total ₹33.75
- [ ] A range with no expenses (e.g. 2000-01-01 to 2000-01-31) shows ₹0.00, 0 transactions, "—" as top category, and "No expenses in this period." in both lists, with no errors
- [ ] `/profile?start_date=2026-11-30&end_date=2026-11-01` returns 400 and shows "Start date must be on or before end date." with unfiltered data
- [ ] `/profile?start_date=not-a-date` returns 400 and shows "Please enter valid dates."
- [ ] Clicking Clear or "All time" returns to the unfiltered `/profile` URL and full totals
- [ ] "This month" and "Last 30 days" presets apply the expected ranges relative to today
- [ ] Logged out, `/profile?start_date=2026-11-01` still redirects to `/login`
- [ ] Below 640px the filter bar stacks vertically with no horizontal page scroll
- [ ] `pytest` passes, including all existing Step 1–5 tests and the new `tests/test_date_filter.py`
