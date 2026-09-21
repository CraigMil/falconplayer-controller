"""The next-game strip's fixture window.

ESPN stopped accepting `dates=START-END`, which is what the 21-day span used
to be: every call 400d and every card read "no fixture scheduled". A month
query (`dates=YYYYMM`) is the replacement — it needs no week number and no
season type, and it spans the regular/post-season boundary that week numbering
resets across.
"""

from datetime import datetime, timezone

from fpp.displays import nfl


def _fixture_event(event_id: str, iso: str) -> dict:
    return {
        "id": event_id, "date": iso, "week": {"number": 3},
        "season": {"slug": "regular-season"},
        "competitions": [{
            "status": {"type": {"state": "pre", "shortDetail": "", "detail": ""},
                       "displayClock": "", "period": 0},
            "competitors": [
                {"homeAway": "away", "score": "0",
                 "team": {"id": "12", "abbreviation": "KC", "shortDisplayName": "Chiefs"}},
                {"homeAway": "home", "score": "0",
                 "team": {"id": "2", "abbreviation": "BUF", "shortDisplayName": "Bills"}},
            ],
        }],
    }


NOW = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)


def test_months_covering_a_window_inside_one_month():
    assert nfl._months(datetime(2026, 9, 1, tzinfo=timezone.utc), days=21) == ["202609"]


def test_months_covering_a_window_that_crosses_into_the_next_month():
    assert nfl._months(NOW, days=21) == ["202609", "202610"]


def test_months_crossing_a_year_boundary():
    """The playoffs are in January — the window must not ask for month 13."""
    assert nfl._months(datetime(2026, 12, 28, tzinfo=timezone.utc), days=21) == \
        ["202612", "202701"]


def test_fixtures_are_fetched_by_month_never_by_a_day_range(monkeypatch):
    asked = []

    def fake_get(url):
        asked.append(url)
        return {"events": []}

    monkeypatch.setattr(nfl, "_get", fake_get)
    nfl.fetch_fixtures(days=21, now=NOW)

    assert [u.split("dates=")[1] for u in asked] == ["202609", "202610"]
    assert not any("-" in u.split("dates=")[1] for u in asked)


def test_a_game_in_both_months_is_only_listed_once(monkeypatch):
    """Month queries can overlap at a boundary; the same id must not repeat."""
    monkeypatch.setattr(nfl, "_get",
                        lambda url: {"events": [_fixture_event("99", "2026-09-27T17:00Z")]})
    out = nfl.fetch_fixtures(days=21, now=NOW)
    assert [f["event_id"] for f in out] == ["99"]


def test_games_beyond_the_window_are_dropped(monkeypatch):
    """A month query returns the whole month, including games past the window."""
    events = [_fixture_event("1", "2026-09-27T17:00Z"),
              _fixture_event("2", "2026-10-25T17:00Z")]
    monkeypatch.setattr(nfl, "_get", lambda url: {"events": events})
    out = nfl.fetch_fixtures(days=21, now=NOW)
    assert [f["event_id"] for f in out] == ["1"]


def test_fixtures_come_back_in_date_order(monkeypatch):
    """next_fixture() takes the FIRST future match, so order is the contract."""
    events = [_fixture_event("late", "2026-10-04T17:00Z"),
              _fixture_event("early", "2026-09-27T17:00Z")]
    monkeypatch.setattr(nfl, "_get", lambda url: {"events": events})
    out = nfl.fetch_fixtures(days=21, now=NOW)
    assert [f["event_id"] for f in out] == ["early", "late"]
