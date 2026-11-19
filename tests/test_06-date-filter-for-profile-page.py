"""Tests for Step 6: Date Filter for Profile Page.

Expected values come from .claude/specs/06-date-filter-for-profile-page.md.
"""
import re
import sqlite3
from datetime import date, timedelta

import pytest

import database.db as db_module

DEMO_EMAIL = "demo@spendly.com"
DEMO_PASSWORD = "demo123"

FULL_TOTAL = "₹1,484.24"
INVALID_MSG = "Please enter valid dates."
ORDER_MSG = "Start date must be on or before end date."
EMPTY_MSG = "No expenses in this period."

# day -> (amount, description) for the seed expenses (current month)
SEED = {
    1: (1200.00, "Monthly rent"),
    3: (45.50, "Groceries"),
    5: (30.00, "Metro card top-up"),
    8: (60.00, "Pharmacy"),
    12: (25.00, "Movie tickets"),
    15: (89.99, "New shoes"),
    20: (18.75, "Lunch with friends"),
    25: (15.00, None),
}
DESCRIPTIONS = [desc for _, desc in SEED.values() if desc]


# ---------------------------------------------------------------- helpers
def month_day(day):
    return date.today().replace(day=day).isoformat()


def fmt(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


@pytest.fixture
def auth_client(client):
    resp = client.post(
        "/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert resp.status_code == 302, "Demo login should redirect"
    return client


def get_profile(client, **params):
    return client.get("/profile", query_string=params)


def html(resp):
    return resp.get_data(as_text=True)


def stat_values(text):
    return [
        s.strip()
        for s in re.findall(
            r'<span class="profile-stat-value">(.*?)</span>', text, re.S
        )
    ]


def row_count(text):
    return len(re.findall(r'class="profile-row[ "]', text))


def category_row_count(text):
    return len(re.findall(r'class="profile-bar-row[ "]', text))


def expense_rows():
    conn = sqlite3.connect(db_module.DB_PATH)
    try:
        return conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def present_descriptions(text):
    return {desc for desc in DESCRIPTIONS if desc in text}


# ------------------------------------------------------------ auth guard
class TestAuthGuard:
    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"start_date": "2026-11-01"},
            {"start_date": "2026-11-01", "end_date": "2026-11-10"},
            {"start_date": "not-a-date"},
        ],
    )
    def test_profile_logged_out_redirects_to_login(self, client, params):
        resp = get_profile(client, **params)
        assert resp.status_code == 302, "Logged out should redirect"
        assert "/login" in resp.headers["Location"]


# --------------------------------------------------------- no filter
class TestUnfiltered:
    def test_no_query_string_shows_full_totals(self, auth_client):
        resp = get_profile(auth_client)
        text = html(resp)
        assert resp.status_code == 200
        values = stat_values(text)
        assert FULL_TOTAL in values, f"Expected full total in {values}"
        assert "8" in values, f"Expected 8 transactions in {values}"
        assert "Bills" in values, f"Expected top category Bills in {values}"
        assert row_count(text) == 8

    def test_no_query_string_shows_no_caption_or_error(self, auth_client):
        text = html(get_profile(auth_client))
        assert "Showing" not in text
        assert INVALID_MSG not in text
        assert ORDER_MSG not in text
        assert EMPTY_MSG not in text

    def test_empty_string_params_treated_as_not_provided(self, auth_client):
        resp = get_profile(auth_client, start_date="", end_date="")
        text = html(resp)
        assert resp.status_code == 200
        assert FULL_TOTAL in stat_values(text)
        assert row_count(text) == 8
        assert "Showing" not in text


# -------------------------------------------------------- filter bar UI
class TestFilterBar:
    def test_filter_bar_has_date_inputs_apply_clear_and_presets(
        self, auth_client
    ):
        text = html(get_profile(auth_client))
        assert re.search(r'<input[^>]*type="date"[^>]*name="start_date"', text) \
            or re.search(r'<input[^>]*name="start_date"[^>]*type="date"', text)
        assert re.search(r'<input[^>]*type="date"[^>]*name="end_date"', text) \
            or re.search(r'<input[^>]*name="end_date"[^>]*type="date"', text)
        assert "<label" in text
        assert "Apply" in text
        assert "Clear" in text
        for label in ("This month", "Last 30 days", "All time"):
            assert label in text, f"Missing preset {label}"

    def test_filter_form_uses_get_method(self, auth_client):
        text = html(get_profile(auth_client))
        form = re.search(r'<form[^>]*method="get"[^>]*>', text, re.I)
        assert form, "Expected a GET filter form"
        assert "/profile" in form.group(0)

    def test_filter_bar_is_above_summary_stats(self, auth_client):
        text = html(get_profile(auth_client))
        assert text.index('name="start_date"') < text.index(
            "profile-stat-value"
        ), "Filter bar must precede the summary stats"

    def test_this_month_and_last_30_days_presets_link_to_expected_ranges(
        self, auth_client
    ):
        text = html(get_profile(auth_client))
        today = date.today()
        first = today.replace(day=1).isoformat()
        back30 = (today - timedelta(days=29)).isoformat()
        assert f"start_date={first}" in text
        assert f"start_date={back30}" in text
        assert f"end_date={today.isoformat()}" in text

    def test_clear_and_all_time_links_point_to_plain_profile(
        self, auth_client
    ):
        text = html(get_profile(auth_client, start_date=month_day(1)))
        for label in ("Clear", "All time"):
            link = re.search(
                r'<a[^>]*href="([^"]*)"[^>]*>\s*' + label + r"\s*</a>", text
            )
            assert link, f"Missing {label} link"
            assert link.group(1) == "/profile", (
                f"{label} should link to /profile with no query params, "
                f"got {link.group(1)}"
            )


# ---------------------------------------------------- filtered happy paths
class TestFilteredRange:
    def test_first_to_tenth_shows_expected_stats(self, auth_client):
        resp = get_profile(
            auth_client, start_date=month_day(1), end_date=month_day(10)
        )
        text = html(resp)
        assert resp.status_code == 200
        values = stat_values(text)
        assert "₹1,335.50" in values, f"Got {values}"
        assert "4" in values, f"Expected 4 transactions in {values}"
        assert "Bills" in values
        assert row_count(text) == 4
        assert category_row_count(text) == 4

    def test_first_to_tenth_includes_and_excludes_correct_rows(
        self, auth_client
    ):
        text = html(
            get_profile(
                auth_client, start_date=month_day(1), end_date=month_day(10)
            )
        )
        assert present_descriptions(text) == {
            "Monthly rent",
            "Groceries",
            "Metro card top-up",
            "Pharmacy",
        }

    def test_first_to_tenth_categories_and_percentages_sum_to_100(
        self, auth_client
    ):
        text = html(
            get_profile(
                auth_client, start_date=month_day(1), end_date=month_day(10)
            )
        )
        start = text.index("profile-bar-row")
        section = text[start:]
        for cat in ("Bills", "Food", "Transport", "Health"):
            assert cat in section, f"Missing category {cat}"
        for cat in ("Shopping", "Entertainment", "Other"):
            assert cat not in section, f"Unexpected category {cat}"
        pcts = [
            float(p)
            # Only the visible labels — the SVG bars also carry width/height "%".
            for p in re.findall(
                r'<span class="profile-bar-pct">(\d+(?:\.\d+)?)%</span>', section
            )
        ]
        assert len(pcts) == 4, "Expected one percentage per category"
        assert sum(pcts) == pytest.approx(100, abs=1.0)

    def test_bounds_are_inclusive_on_both_ends(self, auth_client):
        # Exactly day 3 .. day 3 must include the day-3 expense only.
        text = html(
            get_profile(
                auth_client, start_date=month_day(3), end_date=month_day(3)
            )
        )
        assert row_count(text) == 1
        assert present_descriptions(text) == {"Groceries"}
        # Day 1 .. day 5 includes both boundary days.
        text = html(
            get_profile(
                auth_client, start_date=month_day(1), end_date=month_day(5)
            )
        )
        assert present_descriptions(text) == {
            "Monthly rent",
            "Groceries",
            "Metro card top-up",
        }

    def test_only_start_date_is_open_ended(self, auth_client):
        resp = get_profile(auth_client, start_date=month_day(20))
        text = html(resp)
        assert resp.status_code == 200
        values = stat_values(text)
        assert "₹33.75" in values, f"Got {values}"
        assert "2" in values
        assert row_count(text) == 2
        assert "Lunch with friends" in text
        assert "₹18.75" in text
        assert "₹15.00" in text
        assert "Food" in text and "Other" in text

    def test_only_end_date_is_everything_up_to_and_including(
        self, auth_client
    ):
        text = html(get_profile(auth_client, end_date=month_day(3)))
        assert row_count(text) == 2
        assert present_descriptions(text) == {"Monthly rent", "Groceries"}
        assert "₹1,245.50" in stat_values(text)

    def test_empty_range_shows_zero_state_without_error(self, auth_client):
        resp = get_profile(
            auth_client, start_date="2000-01-01", end_date="2000-01-31"
        )
        text = html(resp)
        assert resp.status_code == 200
        values = stat_values(text)
        assert "₹0.00" in values, f"Got {values}"
        assert "0" in values
        assert "—" in values, "Top category should be an em dash"
        assert row_count(text) == 0
        assert category_row_count(text) == 0
        assert text.count(EMPTY_MSG) >= 2, (
            "Empty state expected in both transactions and categories"
        )
        assert "No expenses yet." not in text
        assert INVALID_MSG not in text and ORDER_MSG not in text

    def test_unfiltered_empty_state_text_not_used_for_data(self, auth_client):
        text = html(get_profile(auth_client))
        assert EMPTY_MSG not in text

    def test_other_users_expenses_never_counted(self, auth_client):
        db_module.create_user("Other Person", "other@example.com", "secret123")
        conn = sqlite3.connect(db_module.DB_PATH)
        try:
            other = conn.execute(
                "SELECT id FROM users WHERE email = ?", ("other@example.com",)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, "
                "description) VALUES (?, ?, ?, ?, ?)",
                (other, 999.0, "Travel", month_day(2), "Other user secret"),
            )
            conn.commit()
        finally:
            conn.close()
        text = html(
            get_profile(
                auth_client, start_date=month_day(1), end_date=month_day(10)
            )
        )
        assert "Other user secret" not in text
        assert "₹1,335.50" in stat_values(text)


# ------------------------------------------- caption, prefill, bookmarking
class TestCaptionAndPrefill:
    def test_both_dates_caption_and_prefill(self, auth_client):
        s, e = month_day(1), month_day(10)
        text = html(get_profile(auth_client, start_date=s, end_date=e))
        assert f"Showing {fmt(s)} – {fmt(e)}" in text
        assert re.search(
            r'<input(?=[^>]*name="start_date")[^>]*value="' + s + '"', text
        )
        assert re.search(
            r'<input(?=[^>]*name="end_date")[^>]*value="' + e + '"', text
        )

    def test_only_start_caption(self, auth_client):
        s = month_day(20)
        text = html(get_profile(auth_client, start_date=s))
        assert f"Showing from {fmt(s)}" in text

    def test_only_end_caption(self, auth_client):
        e = month_day(10)
        text = html(get_profile(auth_client, end_date=e))
        assert f"Showing up to {fmt(e)}" in text

    def test_reloading_same_url_reproduces_same_view(self, auth_client):
        a = get_profile(
            auth_client, start_date=month_day(1), end_date=month_day(10)
        )
        b = get_profile(
            auth_client, start_date=month_day(1), end_date=month_day(10)
        )
        assert stat_values(html(a)) == stat_values(html(b))
        assert row_count(html(a)) == row_count(html(b)) == 4

    def test_clear_returns_to_full_totals(self, auth_client):
        get_profile(
            auth_client, start_date=month_day(1), end_date=month_day(10)
        )
        text = html(auth_client.get("/profile"))
        assert FULL_TOTAL in stat_values(text)
        assert row_count(text) == 8


# ------------------------------------------------------ validation errors
class TestValidation:
    @pytest.mark.parametrize(
        "params",
        [
            {"start_date": "not-a-date"},
            {"end_date": "not-a-date"},
            {"start_date": "2026-13-01"},
            {"start_date": "2026-02-30"},
            {"start_date": "20261101"},
            {"end_date": "20261101"},
            {"start_date": "2026/11/01"},
            {"start_date": "11-01-2026"},
            {"start_date": "2026-W47-4"},
            {"start_date": "2026-11-01", "end_date": "garbage"},
            {"start_date": "' OR 1=1 --"},
            {"end_date": "2026-11-01'; DROP TABLE expenses; --"},
        ],
    )
    def test_invalid_date_returns_400_with_error_and_unfiltered_data(
        self, auth_client, params
    ):
        resp = get_profile(auth_client, **params)
        text = html(resp)
        assert resp.status_code == 400, f"{params} should give 400"
        assert INVALID_MSG in text
        assert FULL_TOTAL in stat_values(text), "Data should be unfiltered"
        assert row_count(text) == 8

    @pytest.mark.parametrize(
        "start,end",
        [
            ("2026-11-30", "2026-11-01"),
            ("2026-11-02", "2026-11-01"),
            ("2027-01-01", "2026-12-31"),
        ],
    )
    def test_start_after_end_returns_400_with_error_and_unfiltered_data(
        self, auth_client, start, end
    ):
        resp = get_profile(auth_client, start_date=start, end_date=end)
        text = html(resp)
        assert resp.status_code == 400
        assert ORDER_MSG in text
        assert INVALID_MSG not in text
        assert FULL_TOTAL in stat_values(text)
        assert row_count(text) == 8

    def test_start_equal_to_end_is_valid(self, auth_client):
        d = month_day(3)
        resp = get_profile(auth_client, start_date=d, end_date=d)
        assert resp.status_code == 200
        assert ORDER_MSG not in html(resp)

    def test_error_page_has_no_caption(self, auth_client):
        text = html(get_profile(auth_client, start_date="not-a-date"))
        assert "Showing" not in text


# ------------------------------------------------------- DB side effects
class TestNoSideEffects:
    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"start_date": "2026-01-01", "end_date": "2026-12-31"},
            {"start_date": "2000-01-01", "end_date": "2000-01-31"},
            {"start_date": "not-a-date"},
            {"start_date": "' OR 1=1; DROP TABLE expenses; --"},
            {"start_date": "2026-11-30", "end_date": "2026-11-01"},
        ],
    )
    def test_get_profile_does_not_change_expenses_table(
        self, auth_client, params
    ):
        before = expense_rows()
        assert len(before) == 8
        get_profile(auth_client, **params)
        assert expense_rows() == before, "GET /profile must be read-only"


# ------------------------------------- pure helpers (signatures per spec)
class TestHelpers:
    def test_build_date_presets_ranges(self):
        from app import build_date_presets

        today = date(2026, 11, 19)
        presets = build_date_presets(today)
        by_label = {p["label"]: p for p in presets}
        assert by_label["This month"]["start_date"] == "2026-11-01"
        assert by_label["This month"]["end_date"] == "2026-11-19"
        assert by_label["Last 30 days"]["start_date"] == "2026-10-21"
        assert by_label["Last 30 days"]["end_date"] == "2026-11-19"

    def test_parse_date_filter_valid_and_blank(self):
        from app import parse_date_filter

        assert parse_date_filter({}) == (None, None, None)
        assert parse_date_filter({"start_date": "", "end_date": ""}) == (
            None,
            None,
            None,
        )
        assert parse_date_filter(
            {"start_date": "2026-11-01", "end_date": "2026-11-10"}
        ) == ("2026-11-01", "2026-11-10", None)
        assert parse_date_filter({"start_date": "2026-11-01"}) == (
            "2026-11-01",
            None,
            None,
        )

    @pytest.mark.parametrize(
        "args,message",
        [
            ({"start_date": "nope"}, INVALID_MSG),
            ({"start_date": "20261101"}, INVALID_MSG),
            ({"start_date": "2026-11-30", "end_date": "2026-11-01"}, ORDER_MSG),
        ],
    )
    def test_parse_date_filter_errors(self, args, message):
        from app import parse_date_filter

        start, end, error = parse_date_filter(args)
        assert error == message
        assert start is None and end is None


# ----------------------------------------- DB helper backward compat/range
class TestDbHelpers:
    def _uid(self):
        return db_module.get_user_by_email(DEMO_EMAIL)["id"]

    def test_helpers_without_dates_unchanged(self, app):
        uid = self._uid()
        assert db_module.get_summary_stats(uid) is not None
        assert len(db_module.get_recent_transactions(uid, limit=100)) == 8
        assert len(db_module.get_category_breakdown(uid)) == 7

    def test_helpers_with_range_filter_rows(self, app):
        uid = self._uid()
        s, e = month_day(1), month_day(10)
        assert (
            len(
                db_module.get_recent_transactions(
                    uid, limit=100, start_date=s, end_date=e
                )
            )
            == 4
        )
        cats = db_module.get_category_breakdown(uid, start_date=s, end_date=e)
        assert len(cats) == 4
        assert (
            len(db_module.get_category_breakdown(uid, start_date=month_day(20)))
            == 2
        )
