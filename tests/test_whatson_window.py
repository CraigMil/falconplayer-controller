"""Day bucketing in Pacific time. This is where UTC arithmetic goes wrong."""

from datetime import datetime, timezone

from fpp.displays.whatson.window import PACIFIC, bucket, clock, date_range

NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)  # 7am PDT, Sat 29 Aug


def test_date_range_covers_today_and_tomorrow_in_pacific():
    assert date_range(NOW) == "20260829-20260830"


def test_utc_evening_game_is_still_today_in_pacific():
    # 02:00 UTC Sun 30 Aug is 7pm PDT Sat 29 — today, not tomorrow.
    kickoff = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    assert bucket(kickoff, NOW) == "today"


def test_utc_next_day_morning_is_tomorrow():
    # 17:00 UTC Sun 30 Aug is 10am PDT Sunday.
    kickoff = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)
    assert bucket(kickoff, NOW) == "tomorrow"


def test_two_days_out_is_outside_the_window():
    kickoff = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)
    assert bucket(kickoff, NOW) is None


def test_clock_renders_pacific_lowercase_meridiem():
    # 16:30 UTC = 9:30am PDT — the ET lunchtime NFL window.
    assert clock(datetime(2026, 8, 29, 16, 30, tzinfo=timezone.utc)) == "9:30a"
    assert clock(datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)) == "7:00p"


def test_bounds_are_pacific_midnight():
    from fpp.displays.whatson.window import bounds
    start, end = bounds(NOW)
    assert start.astimezone(PACIFIC).hour == 0
    assert (end - start).days == 2
