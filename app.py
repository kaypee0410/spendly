import os
from datetime import date, timedelta

from flask import Flask, flash, redirect, render_template, request, session, url_for

from database.db import (
    authenticate_user,
    create_user,
    get_category_breakdown,
    get_db,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

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
    user_id = session.get("user_id")
    if not user_id:
        flash(PROFILE_LOGIN_REQUIRED)
        return redirect(url_for("login"))

    user = get_user_by_id(user_id)
    if user is None:  # stale session — the user row no longer exists
        session.clear()  # clear before flash(), or the flash is wiped too
        flash(PROFILE_LOGIN_REQUIRED)
        return redirect(url_for("login"))

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
    user_id = session.get("user_id")
    if not user_id or get_user_by_id(user_id) is None:
        session.clear()  # drop any stale session; clear before flash()
        flash(ANALYTICS_LOGIN_REQUIRED)
        return redirect(url_for("login"))
    return render_template("analytics.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
