import hmac
import os
import secrets
import warnings
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from database.db import (
    authenticate_user,
    create_expense,
    create_user,
    get_category_breakdown,
    get_db,
    get_expense_by_id,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
    update_expense,
)

DEV_SECRET_KEY = "dev-secret-change-me"


def debug_enabled(environ):
    """Debug (and the Werkzeug debugger) only when FLASK_DEBUG=1 is set."""
    return environ.get("FLASK_DEBUG") == "1"


def load_secret_key(environ):
    """SECRET_KEY from the environment, else a safe fallback.

    The well-known dev key is used only in debug mode, so sessions survive
    the reloader. Otherwise a random per-process key is used: sessions reset
    on restart, but nobody can forge a cookie with a key they can guess.
    """
    key = environ.get("SECRET_KEY")
    if key:
        return key
    if debug_enabled(environ):
        return DEV_SECRET_KEY
    warnings.warn("SECRET_KEY is not set; using a random key for this process.")
    return secrets.token_hex(32)


app = Flask(__name__)
app.secret_key = load_secret_key(os.environ)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Every POST must carry the session's CSRF token; tests may switch this off.
app.config["CSRF_ENABLED"] = True
# Our largest form is a few hundred bytes; refuse anything far bigger (413).
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

DUPLICATE_EMAIL_ERROR = "An account with that email already exists."
LOGIN_REQUIRED_ERROR = "All fields are required."
INVALID_LOGIN_ERROR = "Invalid email or password."
PROFILE_LOGIN_REQUIRED = "Please sign in to view your profile."
ANALYTICS_LOGIN_REQUIRED = "Please sign in to view analytics."
INVALID_DATE_ERROR = "Please enter valid dates."
DATE_ORDER_ERROR = "Start date must be on or before end date."

# ---- Expense forms: add (Step 7), edit (Step 8) ------------------ #

ADD_EXPENSE_LOGIN_REQUIRED = "Please sign in to add an expense."
EDIT_EXPENSE_LOGIN_REQUIRED = "Please sign in to edit an expense."
EXPENSE_ADDED = "Expense added."
EXPENSE_UPDATED = "Expense updated."
AMOUNT_REQUIRED_ERROR = "Please enter an amount."
AMOUNT_INVALID_ERROR = "Please enter a valid amount."
AMOUNT_NOT_POSITIVE_ERROR = "Amount must be greater than zero."
AMOUNT_PRECISION_ERROR = "Amount can have at most 2 decimal places."
AMOUNT_TOO_LARGE_ERROR = "Amount is too large."
CATEGORY_INVALID_ERROR = "Please choose a category."
EXPENSE_DATE_INVALID_ERROR = "Please enter a valid date."
EXPENSE_DATE_FUTURE_ERROR = "Date cannot be in the future."
DESCRIPTION_TOO_LONG_ERROR = "Description must be 200 characters or fewer."

EXPENSE_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]
EXPENSE_FIELDS = ("amount", "category", "date", "description")
MAX_EXPENSE_AMOUNT = Decimal("10000000")
MAX_AMOUNT_LENGTH = 20  # longer strings are rejected before Decimal parsing
MAX_DESCRIPTION_LENGTH = 200


@app.template_filter("inr")
def format_inr(value):
    """Format a number as rupees, e.g. 21020 -> '₹21,020.00'."""
    return f"₹{value:,.2f}"


@app.template_filter("short_date")
def format_short_date(value):
    """Format an ISO date as '1 Nov 2026' (no platform-specific %-d)."""
    d = date.fromisoformat(value)
    return f"{d.day} {d.strftime('%b %Y')}"


def _parse_iso_date(value):
    """Parse a strict YYYY-MM-DD string; raise ValueError for anything else."""
    parsed = date.fromisoformat(value)
    # Python 3.11+ also accepts e.g. '20261101' or '2026-W47-4' — reject those.
    if parsed.isoformat() != value:
        raise ValueError(value)
    return parsed


def parse_date_filter(args):
    """Return (start_iso, end_iso, error) from query args.

    Blank values mean "not provided". On error both dates are None.
    """
    raw_start = args.get("start_date", "").strip()
    raw_end = args.get("end_date", "").strip()
    try:
        start = _parse_iso_date(raw_start) if raw_start else None
        end = _parse_iso_date(raw_end) if raw_end else None
    except ValueError:
        return None, None, INVALID_DATE_ERROR
    if start and end and start > end:
        return None, None, DATE_ORDER_ERROR
    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
        None,
    )


def build_date_presets(today):
    """Return quick-filter ranges relative to today, as ISO strings."""
    return [
        {
            "label": "This month",
            "start_date": today.replace(day=1).isoformat(),
            "end_date": today.isoformat(),
        },
        {
            "label": "Last 30 days",
            "start_date": (today - timedelta(days=29)).isoformat(),
            "end_date": today.isoformat(),
        },
    ]


def validate_registration(name, email, password):
    """Return the first validation error message, or None if the input is valid."""
    if not name or not email or not password:
        return "All fields are required."
    local, at, domain = email.rpartition("@")
    if not at or not local or "." not in domain:
        return "Please enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    return None


def _render_register_error(error, name, email):
    return render_template("register.html", error=error, name=name, email=email), 400


def _render_login_error(error, email, status):
    return render_template("login.html", error=error, email=email), status


def _decimal_places(value):
    """Exact count of significant decimal places: '12.50' -> 1, '12.340' -> 2.

    Works on the digit tuple, so no context precision or rounding is involved.
    """
    _, digits, exponent = value.as_tuple()
    while exponent < 0 and digits and digits[-1] == 0:  # ignore trailing zeros
        digits = digits[:-1]
        exponent += 1
    return max(0, -exponent)


def _validate_amount(raw):
    """Return (Decimal, None) or (None, error) for a submitted amount string."""
    if not raw:
        return None, AMOUNT_REQUIRED_ERROR
    if len(raw) > MAX_AMOUNT_LENGTH:
        return None, AMOUNT_INVALID_ERROR
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None, AMOUNT_INVALID_ERROR
    if not amount.is_finite():  # nan, snan, inf — check before comparing
        return None, AMOUNT_INVALID_ERROR
    if amount <= 0:
        return None, AMOUNT_NOT_POSITIVE_ERROR
    if _decimal_places(amount) > 2:
        return None, AMOUNT_PRECISION_ERROR
    if amount > MAX_EXPENSE_AMOUNT:
        return None, AMOUNT_TOO_LARGE_ERROR
    return amount, None


def validate_expense(form, today, allowed_date: str | None = None):
    """Return (clean, error) for an expense form; the first error wins.

    clean is {amount, category, date, description} ready for create_expense
    or update_expense, or None when error is set. allowed_date (ISO string)
    is an expense's stored date: keeping it unchanged is accepted even if it
    is later than today.
    """
    amount, error = _validate_amount(form.get("amount", "").strip())
    if error:
        return None, error

    category = form.get("category", "")
    if category not in EXPENSE_CATEGORIES:
        return None, CATEGORY_INVALID_ERROR

    try:
        expense_date = _parse_iso_date(form.get("date", "").strip())
    except ValueError:  # blank values raise too
        return None, EXPENSE_DATE_INVALID_ERROR
    if expense_date > today and expense_date.isoformat() != allowed_date:
        return None, EXPENSE_DATE_FUTURE_ERROR

    description = form.get("description", "").strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return None, DESCRIPTION_TOO_LONG_ERROR

    return {
        "amount": float(amount),
        "category": category,
        "date": expense_date.isoformat(),
        "description": description or None,
    }, None


def _blank_expense_values(today):
    """Initial form values for a new expense: everything empty, date = today."""
    values = dict.fromkeys(EXPENSE_FIELDS, "")
    values["date"] = today.isoformat()
    return values


def _render_add_expense(values, today, error=None, status=200):
    html = render_template(
        "add_expense.html",
        categories=EXPENSE_CATEGORIES,
        values=values,
        error=error,
        today=today.isoformat(),
        max_description=MAX_DESCRIPTION_LENGTH,
    )
    return html, status


def _latest_allowed_date(today, stored_date):
    """The date input's max: today, or the stored date if that is later.

    Mirrors validate_expense(..., allowed_date=stored_date), which accepts a
    future date only when it equals the stored one. Both are ISO strings, so
    string comparison orders them by date.
    """
    return max(today.isoformat(), stored_date)


def _expense_form_values(expense):
    """Form values for a stored expense: amount to 2 places, NULL description -> ''."""
    return {
        "amount": f"{expense['amount']:.2f}",
        "category": expense["category"],
        "date": expense["date"],
        "description": expense["description"] or "",
    }


def _render_edit_expense(expense_id, values, date_max, error=None, status=200):
    html = render_template(
        "edit_expense.html",
        expense_id=expense_id,
        categories=EXPENSE_CATEGORIES,
        values=values,
        error=error,
        date_max=date_max,
        max_description=MAX_DESCRIPTION_LENGTH,
    )
    return html, status


def _current_user():
    """Return the logged-in user's profile dict, or None if not logged in.

    A session whose user row no longer exists is cleared.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = get_user_by_id(user_id)
    if user is None:
        session.clear()
    return user


CSRF_FIELD = "csrf_token"


def csrf_token():
    """Return this session's CSRF token, creating it on first use.

    Exposed to templates as csrf_token(); every POST form includes it as a
    hidden field named CSRF_FIELD.
    """
    token = session.get(CSRF_FIELD)
    if token is None:
        token = secrets.token_urlsafe(32)
        session[CSRF_FIELD] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def check_csrf():
    """Reject any POST whose form token doesn't match the session's (400)."""
    if request.method != "POST" or not app.config["CSRF_ENABLED"]:
        return
    expected = session.get(CSRF_FIELD)
    submitted = request.form.get(CSRF_FIELD, "")
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
    if not expected or not hmac.compare_digest(
        expected.encode(), submitted.encode()
    ):
        abort(400)


def _login_redirect(message):
    """Flash message and send the visitor to the login page."""
    flash(message)  # after any session.clear(), or the flash is wiped too
    return redirect(url_for("login"))


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    error = validate_registration(name, email, password)
    if error is None and get_user_by_email(email) is not None:
        error = DUPLICATE_EMAIL_ERROR
    if error is None and create_user(name, email, password) is None:
        error = DUPLICATE_EMAIL_ERROR
    if error is not None:
        return _render_register_error(error, name, email)

    flash("Account created — please sign in.")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("profile"))
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        return _render_login_error(LOGIN_REQUIRED_ERROR, email, 400)

    user = authenticate_user(email, password)
    if user is None:
        return _render_login_error(INVALID_LOGIN_ERROR, email, 401)

    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.")
    return redirect(url_for("login"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/profile")
def profile():
    user = _current_user()
    if user is None:
        return _login_redirect(PROFILE_LOGIN_REQUIRED)
    user_id = session["user_id"]

    # On error, parse_date_filter returns None dates -> unfiltered fallback.
    start_date, end_date, error = parse_date_filter(request.args)
    html = render_template(
        "profile.html",
        user=user,
        summary=get_summary_stats(user_id, start_date, end_date),
        transactions=get_recent_transactions(
            user_id, start_date=start_date, end_date=end_date
        ),
        categories=get_category_breakdown(user_id, start_date, end_date),
        start_date=start_date,
        end_date=end_date,
        error=error,
        presets=build_date_presets(date.today()),
        filter_active=start_date is not None or end_date is not None,
    )
    return html, 400 if error else 200


@app.route("/analytics")
def analytics():
    if _current_user() is None:
        return _login_redirect(ANALYTICS_LOGIN_REQUIRED)
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if _current_user() is None:
        return _login_redirect(ADD_EXPENSE_LOGIN_REQUIRED)

    today = date.today()
    if request.method == "GET":
        return _render_add_expense(_blank_expense_values(today), today)

    clean, error = validate_expense(request.form, today)
    if error is not None:
        # Echo back only the known fields; any submitted user_id is ignored.
        values = {key: request.form.get(key, "") for key in EXPENSE_FIELDS}
        return _render_add_expense(values, today, error=error, status=400)

    # user_id comes from the session only, never from the form
    create_expense(session["user_id"], **clean)
    flash(EXPENSE_ADDED)
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if _current_user() is None:
        return _login_redirect(EDIT_EXPENSE_LOGIN_REQUIRED)

    # user_id comes from the session only; a missing or foreign id is a 404
    user_id = session["user_id"]
    expense = get_expense_by_id(id, user_id)
    if expense is None:
        abort(404)

    today = date.today()
    date_max = _latest_allowed_date(today, expense["date"])
    if request.method == "GET":
        return _render_edit_expense(id, _expense_form_values(expense), date_max)

    clean, error = validate_expense(
        request.form, today, allowed_date=expense["date"]
    )
    if error is not None:
        values = {key: request.form.get(key, "") for key in EXPENSE_FIELDS}
        return _render_edit_expense(id, values, date_max, error=error, status=400)

    if not update_expense(id, user_id, **clean):  # deleted since the lookup
        abort(404)
    flash(EXPENSE_UPDATED)
    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=debug_enabled(os.environ), port=5001)
