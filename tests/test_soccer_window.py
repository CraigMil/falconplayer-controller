"""Fetching a date window from ESPN, which no longer accepts date ranges.

`dates=START-END` answers 400 on every scoreboard, which took the whole soccer
board down — not just the next-game strip. Every window is now asked for a
month at a time and filtered locally.
"""

from datetime import datetime, timedelta, timezone

import pytest

from fpp.displays import soccer

UTC = timezone.utc


def _event(event_id: str, iso: str) -> dict:
    return {
        "id": event_id, "date": iso,
        "competitions": [{
            "status": {"type": {"state": "pre", "shortDetail": "", "detail": ""},
                       "displayClock": "", "period": 0},
            "competitors": [
                {"homeAway": "home", "score": "0", "aggregateScore": None,
                 "team": {"id": "359", "abbreviation": "ARS",
                          "shortDisplayName": "Arsenal", "displayName": "Arsenal"}},
                {"homeAway": "away", "score": "0", "aggregateScore": None,
                 "team": {"id": "364", "abbreviation": "LIV",
                          "shortDisplayName": "Liverpool", "displayName": "Liverpool"}},
            ],
        }],
    }


def test_months_between_inside_one_month():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    assert soccer.months_between(start, start + timedelta(days=10)) == ["202609"]


def test_months_between_spanning_two_months():
    """A 35-day fixture window from late September runs into October."""
    start = datetime(2026, 9, 20, tzinfo=UTC)
    assert soccer.months_between(start, start + timedelta(days=35)) == \
        ["202609", "202610"]


def test_months_between_crosses_the_year_boundary():
    start = datetime(2026, 12, 20, tzinfo=UTC)
    assert soccer.months_between(start, start + timedelta(days=35)) == \
        ["202612", "202701"]


def test_the_window_is_asked_for_by_month_not_by_range(monkeypatch):
    asked = []

    def fake_json(slug, dates=None):
        asked.append(dates)
        return {"events": []}

    monkeypatch.setattr(soccer, "_scoreboard_json", fake_json)
    start = datetime(2026, 9, 20, tzinfo=UTC)
    soccer.fetch_games_window("epl", start, start + timedelta(days=15))

    assert asked == ["202609", "202610"]
    assert not any("-" in a for a in asked)


def test_games_outside_the_window_are_dropped(monkeypatch):
    """A month query returns the whole month; the window has to be re-applied."""
    events = [_event("in", "2026-09-22T14:00Z"), _event("out", "2026-09-30T14:00Z")]
    monkeypatch.setattr(soccer, "_scoreboard_json", lambda slug, dates=None: {"events": events})
    start = datetime(2026, 9, 20, tzinfo=UTC)
    got = soccer.fetch_games_window("epl", start, start + timedelta(days=5))
    assert [g["event_id"] for g in got] == ["in"]


def test_the_end_of_the_window_is_exclusive(monkeypatch):
    """The Tue->Mon block ends at the next block's first midnight."""
    events = [_event("edge", "2026-09-25T00:00Z")]
    monkeypatch.setattr(soccer, "_scoreboard_json", lambda slug, dates=None: {"events": events})
    start = datetime(2026, 9, 20, tzinfo=UTC)
    assert soccer.fetch_games_window("epl", start, datetime(2026, 9, 25, tzinfo=UTC)) == []


def test_a_game_returned_by_two_months_is_listed_once(monkeypatch):
    monkeypatch.setattr(soccer, "_scoreboard_json",
                        lambda slug, dates=None: {"events": [_event("1", "2026-09-22T14:00Z")]})
    start = datetime(2026, 9, 20, tzinfo=UTC)
    got = soccer.fetch_games_window("epl", start, start + timedelta(days=20))
    assert [g["event_id"] for g in got] == ["1"]


def test_one_failed_month_does_not_lose_the_others(monkeypatch):
    """September failing must not also discard October's fixtures."""
    def flaky(slug, dates=None):
        if dates == "202609":
            raise RuntimeError("400")
        return {"events": [_event("oct", "2026-10-03T14:00Z")]}

    monkeypatch.setattr(soccer, "_scoreboard_json", flaky)
    start = datetime(2026, 9, 20, tzinfo=UTC)
    got = soccer.fetch_games_window("epl", start, start + timedelta(days=20))
    assert [g["event_id"] for g in got] == ["oct"]


def test_fixtures_use_the_window_fetch(monkeypatch):
    """Regression: the strip read "no fixture scheduled" for every team."""
    monkeypatch.setattr(soccer, "_scoreboard_json",
                        lambda slug, dates=None: {"events": [_event("1", "2026-09-22T14:00Z")]}
                        if dates == "202609" else {"events": []})
    out = soccer.fetch_fixtures(["epl"], days=10,
                                now=datetime(2026, 9, 20, tzinfo=UTC))
    assert [f["event_id"] for f in out] == ["1"]
    assert out[0]["home_abbr"] == "ARS"
