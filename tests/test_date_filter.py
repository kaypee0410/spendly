"""Step 6: date-range filter on the profile page."""
from datetime import date

import pytest

from app import build_date_presets, format_short_date, parse_date_filter
from database.db import (
    _date_range_clause,
    create_user,
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_email,
)

DEMO_EMAIL = "demo@spendly.com"
INVALID_DATE_ERROR = "Please enter valid dates."
DATE_ORDER_ERROR = "Start date must be on or before end date."
EMPTY_FILTERED = "No expenses in this period."
EMPTY_UNFILTERED = "No expenses yet."


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def d(day):
    """ISO date for a day of the current month — matches seed_db()."""
    return date.today().replace(day=day).isoformat()


def demo_id():
    return get_user_by_email(DEMO_EMAIL)["id"]


def log_in(client, user_id=None, name="Demo User"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id if user_id is not None else demo_id()
        sess["user_name"] = name


def get_profile(client, **params):
    log_in(client)
    resp = client.get("/profile", query_string=params)
    return resp, resp.get_data(as_text=True)


def stat(value):
    return f'<span class="profile-stat-value">{value}</span>'


# ------------------------------------------------------------------ #
# _date_range_clause                                                  #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "start, end, expected_sql, expected_params",
    [
        (None, None, "", []),
        ("2026-11-01", None, " AND date >= ?", ["2026-11-01"]),
        (None, "2026-11-10", " AND date <= ?", ["2026-11-10"]),
        (
            "2026-11-01",
            "2026-11-10",
            " AND date >= ? AND date <= ?",
            ["2026-11-01", "2026-11-10"],
        ),
    ],
)
def test_date_range_clause(start, end, expected_sql, expected_params):
    sql, params = _date_range_clause(start, end)
    assert sql == expected_sql
    assert params == expected_params


def test_date_range_clause_never_embeds_values():
    hostile = "2026-01-01' OR '1'='1"
    sql, params = _date_range_clause(hostile, hostile)
    assert hostile not in sql
    assert params == [hostile, hostile]


# ------------------------------------------------------------------ #
# parse_date_filter                                                   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "args",
    [{}, {"start_date": "", "end_date": ""}, {"start_date": "   ", "end_date": " "}],
)
def test_parse_date_filter_blank_means_no_filter(args):
    assert parse_date_filter(args) == (None, None, None)


def test_parse_date_filter_start_only():
    assert parse_date_filter({"start_date": "2026-11-01"}) == ("2026-11-01", None, None)


def test_parse_date_filter_end_only():
    assert parse_date_filter({"end_date": "2026-11-10"}) == (None, "2026-11-10", None)


def test_parse_date_filter_valid_pair():
    args = {"start_date": "2026-11-01", "end_date": "2026-11-10"}
    assert parse_date_filter(args) == ("2026-11-01", "2026-11-10", None)


def test_parse_date_filter_same_day_is_valid():
    args = {"start_date": "2026-11-05", "end_date": "2026-11-05"}
    assert parse_date_filter(args) == ("2026-11-05", "2026-11-05", None)


def test_parse_date_filter_reversed_range():
    args = {"start_date": "2026-11-30", "end_date": "2026-11-01"}
    assert parse_date_filter(args) == (None, None, DATE_ORDER_ERROR)


@pytest.mark.parametrize(
    "bad",
    ["not-a-date", "2026-02-30", "20261101", "2026-W47-4", "2026-11-1",
     "2026-11-01' OR '1'='1"],
)
def test_parse_date_filter_invalid_values(bad):
    assert parse_date_filter({"start_date": bad}) == (None, None, INVALID_DATE_ERROR)
    assert parse_date_filter({"end_date": bad}) == (None, None, INVALID_DATE_ERROR)


# ------------------------------------------------------------------ #
# build_date_presets / short_date                                     #
# ------------------------------------------------------------------ #

def test_build_date_presets():
    presets = build_date_presets(date(2026, 11, 19))
    assert presets == [
        {"label": "This month", "start_date": "2026-11-01", "end_date": "2026-11-19"},
        {"label": "Last 30 days", "start_date": "2026-10-21", "end_date": "2026-11-19"},
    ]


def test_build_date_presets_crosses_month_boundary():
    presets = build_date_presets(date(2026, 3, 1))
    assert presets[0]["start_date"] == "2026-03-01"
    assert presets[1]["start_date"] == "2026-01-31"
    assert presets[1]["end_date"] == "2026-03-01"


def test_short_date_filter():
    assert format_short_date("2026-11-01") == "1 Nov 2026"
    assert format_short_date("2026-11-19") == "19 Nov 2026"


# ------------------------------------------------------------------ #
# DB helpers with a date range                                        #
# ------------------------------------------------------------------ #

def test_summary_stats_filtered_range(app):
    stats = get_summary_stats(demo_id(), d(1), d(10))
    assert stats == {"total_spent": 1335.50, "transaction_count": 4, "top_category": "Bills"}


def test_summary_stats_start_only(app):
    stats = get_summary_stats(demo_id(), start_date=d(20))
    assert stats["total_spent"] == 33.75
    assert stats["transaction_count"] == 2
    # Food 18.75 beats Other 15.00 within the range.
    assert stats["top_category"] == "Food"


def test_summary_stats_end_only(app):
    stats = get_summary_stats(demo_id(), end_date=d(5))
    assert stats["total_spent"] == 1275.50
    assert stats["transaction_count"] == 3


def test_summary_stats_single_day_is_inclusive(app):
    stats = get_summary_stats(demo_id(), d(8), d(8))
    assert stats == {"total_spent": 60.00, "transaction_count": 1, "top_category": "Health"}


def test_summary_stats_empty_range(app):
    stats = get_summary_stats(demo_id(), "2000-01-01", "2000-01-31")
    assert stats == {"total_spent": 0, "transaction_count": 0, "top_category": "—"}


def test_recent_transactions_filtered(app):
    rows = get_recent_transactions(demo_id(), start_date=d(1), end_date=d(10))
    assert [r["date"] for r in rows] == [d(8), d(5), d(3), d(1)]


def test_recent_transactions_limit_applies_after_filter(app):
    rows = get_recent_transactions(demo_id(), limit=2, start_date=d(1), end_date=d(10))
    assert [r["date"] for r in rows] == [d(8), d(5)]


def test_recent_transactions_empty_range(app):
    assert get_recent_transactions(demo_id(), start_date="2000-01-01",
                                   end_date="2000-01-31") == []


def test_category_breakdown_filtered(app):
    cats = get_category_breakdown(demo_id(), d(1), d(10))
    assert [c["name"] for c in cats] == ["Bills", "Health", "Food", "Transport"]
    assert sum(c["pct"] for c in cats) == 100
    assert all(isinstance(c["pct"], int) for c in cats)


def test_category_breakdown_empty_range(app):
    assert get_category_breakdown(demo_id(), "2000-01-01", "2000-01-31") == []


def test_helpers_without_dates_unchanged(app):
    uid = demo_id()
    assert get_summary_stats(uid)["total_spent"] == 1484.24
    assert len(get_recent_transactions(uid)) == 8
    assert len(get_category_breakdown(uid)) == 7


def test_filter_is_scoped_to_user(app):
    other = create_user("Other User", "other@example.com", "password123")
    stats = get_summary_stats(other, d(1), d(28))
    assert stats["transaction_count"] == 0


# ------------------------------------------------------------------ #
# GET /profile with filters                                           #
# ------------------------------------------------------------------ #

def test_profile_unfiltered_matches_step5(client):
    resp, html = get_profile(client)
    assert resp.status_code == 200
    assert stat("₹1,484.24") in html
    assert stat("8") in html
    assert stat("Bills") in html
    assert html.count('class="profile-row"') == 8
    assert html.count('class="profile-bar-row"') == 7
    assert "Showing" not in html


def test_profile_filtered_range(client):
    resp, html = get_profile(client, start_date=d(1), end_date=d(10))
    assert resp.status_code == 200
    assert stat("₹1,335.50") in html
    assert stat("4") in html
    assert stat("Bills") in html
    assert html.count('class="profile-row"') == 4
    assert html.count('class="profile-bar-row"') == 4
    assert "Monthly rent" in html
    assert "New shoes" not in html
    assert f'value="{d(1)}"' in html
    assert f'value="{d(10)}"' in html
    assert f"Showing {format_short_date(d(1))} – {format_short_date(d(10))}" in html


def test_profile_start_only(client):
    resp, html = get_profile(client, start_date=d(20))
    assert resp.status_code == 200
    assert stat("₹33.75") in html
    assert html.count('class="profile-row"') == 2
    assert "Lunch with friends" in html
    assert "Monthly rent" not in html
    assert f"Showing from {format_short_date(d(20))}" in html


def test_profile_end_only(client):
    resp, html = get_profile(client, end_date=d(5))
    assert resp.status_code == 200
    assert stat("₹1,275.50") in html
    assert html.count('class="profile-row"') == 3
    assert f"Showing up to {format_short_date(d(5))}" in html


def test_profile_blank_params_are_unfiltered(client):
    resp, html = get_profile(client, start_date="", end_date="")
    assert resp.status_code == 200
    assert stat("₹1,484.24") in html
    assert "Showing" not in html


def test_profile_empty_range(client):
    resp, html = get_profile(client, start_date="2000-01-01", end_date="2000-01-31")
    assert resp.status_code == 200
    assert stat("₹0.00") in html
    assert stat("0") in html
    assert stat("—") in html
    assert html.count(EMPTY_FILTERED) == 2
    assert EMPTY_UNFILTERED not in html


def test_profile_reversed_range_is_400_and_unfiltered(client):
    resp, html = get_profile(client, start_date=d(20), end_date=d(1))
    assert resp.status_code == 400
    assert DATE_ORDER_ERROR in html
    assert stat("₹1,484.24") in html
    assert html.count('class="profile-row"') == 8
    assert "Showing" not in html


@pytest.mark.parametrize("bad", ["not-a-date", "2026-02-30", "20261101"])
def test_profile_invalid_date_is_400_and_unfiltered(client, bad):
    resp, html = get_profile(client, start_date=bad)
    assert resp.status_code == 400
    assert INVALID_DATE_ERROR in html
    assert stat("₹1,484.24") in html
    assert html.count('class="profile-row"') == 8


def test_profile_filter_bar_markup(client):
    _, html = get_profile(client)
    assert 'method="get"' in html
    assert 'type="date"' in html
    assert '<label for="start_date">' in html
    assert '<label for="end_date">' in html
    assert ">Apply</button>" in html
    assert ">Clear</a>" in html
    for label in ("This month", "Last 30 days", "All time"):
        assert label in html


def test_profile_preset_links(client):
    _, html = get_profile(client)
    for preset in build_date_presets(date.today()):
        href = (f'href="/profile?start_date={preset["start_date"]}'
                f'&amp;end_date={preset["end_date"]}"')
        assert href in html
    # Clear and All time both point at the unfiltered page.
    assert html.count('href="/profile"') >= 2


def test_profile_filter_bar_above_stats(client):
    _, html = get_profile(client)
    assert html.index("profile-filter") < html.index("profile-stats")


def test_profile_all_time_active_when_unfiltered(client):
    _, html = get_profile(client)
    assert 'class="profile-preset is-active" href="/profile"' in html


def test_profile_filtered_unauthenticated_redirects(client):
    resp = client.get("/profile", query_string={"start_date": d(1)})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_profile_filtered_page_has_no_inline_styles(client):
    _, html = get_profile(client, start_date=d(1), end_date=d(10))
    assert 'style="' not in html
