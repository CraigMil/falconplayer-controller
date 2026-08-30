"""The whole board, assembled from fixtures with no network."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fpp.displays import whatson

FIX = Path(__file__).parent / "fixtures" / "espn"
NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)

SLUG_FIXTURES = {
    "football/college-football": "ncaaf_20260829",
    "football/nfl": "nfl_20260829",
    "soccer/eng.1": "epl_20260829",
    "soccer/eng.fa": "facup_empty",
    "soccer/uefa.champions": "ucl_20260829",
    "tennis/atp": "tennis_atp",
    "tennis/wta": "tennis_wta",
    "racing/f1": "f1_monza",
    "baseball/mlb": "mlb_20260829",
    "hockey/nhl": "nhl_empty",
    "soccer/usa.1": "mls_20260829",
    "soccer/usa.nwsl": "nwsl_20260829",
    "basketball/wnba": "wnba_20260829",
}


@pytest.fixture
def offline(monkeypatch):
    def fake_fetch(slug, dates=None):
        name = SLUG_FIXTURES.get(slug)
        if not name:
            return {"events": []}
        return json.loads((FIX / f"{name}.json").read_text())
    monkeypatch.setattr("fpp.displays.whatson.sources.fetch", fake_fetch)
    monkeypatch.setattr("fpp.displays.whatson.highlights.fetch_all", lambda now=None: [])
    # Fixtures carry real logo URLs, and rendering would otherwise fetch every
    # one of them over the network — slow, and wrong for an offline test suite.
    monkeypatch.setattr("fpp.displays.whatson.cards._logo", lambda url: None)


def test_board_builds_and_starts_with_the_seattle_block(offline):
    slides, _ = whatson.build_board(now=NOW)
    assert slides
    assert slides[0]["kind"] == "divider"
    assert slides[0]["title"] == "SEATTLE"


def test_seattle_teams_all_appear_including_the_payable_ones(offline):
    slides, _ = whatson.build_board(now=NOW)
    home = [s for s in slides if s.get("home_team")]
    channels = {s["channel"] for s in home}
    assert "Apple TV" in channels          # Sounders
    assert channels & {"Mariners.TV", "NWSL+"}
    assert all(s["tier"] in ("watchable", "payable") for s in home)
    assert "Sportsnet" not in channels, "never show a Canadian-only feed"


def test_caps_are_respected_across_the_whole_board(offline):
    from fpp.displays.whatson.select import CAPS
    slides, _ = whatson.build_board(now=NOW)
    events = [s for s in slides if s["kind"] == "event" and not s.get("home_team")]
    assert len([s for s in events if s["sport"] == "ncaaf"]) <= CAPS["ncaaf"]
    assert len([s for s in events if s["sport"] in ("atp", "wta")]) <= CAPS["tennis"]


def test_no_unwatchable_event_reaches_the_board(offline):
    slides, _ = whatson.build_board(now=NOW)
    for s in slides:
        if s["kind"] == "event":
            assert s["tier"] in ("watchable", "payable")


def test_non_seattle_games_from_home_only_leagues_are_discarded(offline):
    slides, _ = whatson.build_board(now=NOW)
    strays = [s for s in slides
              if s.get("sport") in ("mlb", "wnba", "mls", "nwsl") and not s.get("home_team")]
    assert strays == []


def test_an_entirely_empty_day_yields_the_empty_card(monkeypatch):
    monkeypatch.setattr("fpp.displays.whatson.sources.fetch",
                        lambda slug, dates=None: {"events": []})
    monkeypatch.setattr("fpp.displays.whatson.highlights.fetch_all", lambda now=None: [])
    slides, reason = whatson.build_board(now=NOW)
    assert len(slides) == 1 and slides[0]["kind"] == "empty"
    assert reason == "empty"


def test_every_slide_the_board_produces_can_be_rendered(offline):
    from fpp.displays.whatson.cards import render
    slides, _ = whatson.build_board(now=NOW)
    for s in slides:
        assert render(s).to_image_bytes()[:2] == b"\xff\xd8"
