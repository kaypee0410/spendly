import os

from flask import Flask, flash, redirect, render_template, request, session, url_for

from database.db import (
    authenticate_user,
    create_user,
    get_db,
    get_user_by_email,
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

# Placeholder profile data — replaced with DB queries in a later step.
# Invariants: total_spent == sum(transactions) == sum(categories);
# transaction_count == len(transactions); top_category == categories[0]["name"]
PROFILE_USER = {
    "name": "Demo User",
    "email": "demo@spendly.com",
    "member_since": "March 2026",
}

PROFILE_SUMMARY = {
    "total_spent": 21020.00,
    "transaction_count": 8,
    "top_category": "Bills",
}

PROFILE_TRANSACTIONS = [  # newest first
    {"date": "2026-11-18", "description": "Monthly rent", "category": "Bills", "amount": 12000.00},
    {"date": "2026-11-16", "description": "Groceries", "category": "Food", "amount": 2340.00},
    {"date": "2026-11-14", "description": "Metro card top-up", "category": "Transport", "amount": 500.00},
    {"date": "2026-11-12", "description": "Pharmacy", "category": "Health", "amount": 860.00},
    {"date": "2026-11-09", "description": "Movie tickets", "category": "Entertainment", "amount": 640.00},
    {"date": "2026-11-06", "description": "Running shoes", "category": "Shopping", "amount": 3200.00},
    {"date": "2026-11-04", "description": "Lunch with friends", "category": "Food", "amount": 1180.00},
    {"date": "2026-11-02", "description": None, "category": "Other", "amount": 300.00},
]

PROFILE_CATEGORIES = [  # amount desc; percent = round(amount / total * 100)
    {"name": "Bills", "amount": 12000.00, "percent": 57},
    {"name": "Food", "amount": 3520.00, "percent": 17},
    {"name": "Shopping", "amount": 3200.00, "percent": 15},
    {"name": "Health", "amount": 860.00, "percent": 4},
    {"name": "Entertainment", "amount": 640.00, "percent": 3},
    {"name": "Transport", "amount": 500.00, "percent": 2},
    {"name": "Other", "amount": 300.00, "percent": 1},
]


@app.template_filter("inr")
def format_inr(value):
    """Format a number as rupees, e.g. 21020 -> '₹21,020.00'."""
    return f"₹{value:,.2f}"


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
    if not session.get("user_id"):
        flash("Please sign in to view your profile.")
        return redirect(url_for("login"))
    return render_template(
        "profile.html",
        user=PROFILE_USER,
        summary=PROFILE_SUMMARY,
        transactions=PROFILE_TRANSACTIONS,
        categories=PROFILE_CATEGORIES,
    )


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
