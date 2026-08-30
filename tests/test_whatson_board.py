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
    "golf/pga": "golf_pga",
    "mma/ufc": "ufc",
    "boxing": "boxing_empty",
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
    assert slides[0]["title"] == "MY TEAMS"


def test_seattle_teams_all_appear_including_the_payable_ones(offline):
    slides, _ = whatson.build_board(now=NOW)
    home = [s for s in slides if s.get("home_team")]
    channels = {s["channel"] for s in home}
    assert "Apple TV" in channels          # Sounders
    assert channels & {"Mariners.TV", "NWSL+"}
    assert all(s["tier"] in ("watchable", "payable") for s in home)
    assert "Sportsnet" not in channels, "never show a Canadian-only feed"


def test_caps_are_respected_across_the_whole_board(offline):
    """Counted by BUCKET, not by sport: a minor ATP tournament is nominally
    tennis but deliberately occupies the ALSO ON slot, so counting by sport
    would double-count it against the tennis cap."""
    from fpp.displays.whatson.select import CAPS, _bucket_key
    slides, _ = whatson.build_board(now=NOW)
    events = [s for s in slides
              if s["kind"] == "event" and not s.get("home_team") and s["day"] == "today"]
    for bucket in ("ncaaf", "tennis", "oddity"):
        n = len([s for s in events if _bucket_key(s) == bucket])
        assert n <= CAPS[bucket], f"{bucket}: {n} > {CAPS[bucket]}"


def test_the_board_always_carries_at_least_one_also_on_card(offline):
    """Craig wants something fun every day, without exception."""
    from fpp.displays.whatson.select import _bucket_key
    slides, _ = whatson.build_board(now=NOW)
    also_on = [s for s in slides if s["kind"] == "event" and _bucket_key(s) == "oddity"]
    assert also_on, "the ALSO ON slot must never be empty"


def test_no_fake_oddity_when_only_one_sport_is_on(monkeypatch):
    """With only college football in the world there is nothing fun to show.

    The board would rather carry no ALSO ON card than relabel a fourth college
    football game as one — that reads as more of the same. The real defence
    against an empty slot is the breadth of the pool (four golf tours, UFC,
    boxing, every minor ATP/WTA event), not a fake.
    """
    from fpp.displays.whatson.select import _bucket_key

    def only_ncaaf(slug, dates=None):
        if slug == "football/college-football":
            return json.loads((FIX / "ncaaf_20260829.json").read_text())
        return {"events": []}

    monkeypatch.setattr("fpp.displays.whatson.sources.fetch", only_ncaaf)
    monkeypatch.setattr("fpp.displays.whatson.highlights.fetch_all", lambda now=None: [])
    monkeypatch.setattr("fpp.displays.whatson.cards._logo", lambda url: None)
    slides, _ = whatson.build_board(now=NOW)
    odd = [s for s in slides if s["kind"] == "event" and _bucket_key(s) == "oddity"]
    assert odd == []
    assert [s for s in slides if s["kind"] == "event"], "the rest of the board still builds"


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


def test_tennis_and_f1_are_fetched_undated(monkeypatch):
    """Regression: the dated query drops the US Open and the whole F1 weekend.

    Asked for 20260829-20260830, tennis/atp returns Winston-Salem but not the US
    Open, and racing/f1 returns nothing during a live race weekend. Both must be
    fetched undated and windowed by their own adapters.
    """
    seen = {}

    def fake_fetch(slug, dates=None):
        seen[slug] = dates
        return {"events": []}

    monkeypatch.setattr("fpp.displays.whatson.sources.fetch", fake_fetch)
    monkeypatch.setattr("fpp.displays.whatson.highlights.fetch_all", lambda now=None: [])
    whatson.build_board(now=NOW)

    assert seen["tennis/atp"] is None
    assert seen["tennis/wta"] is None
    assert seen["racing/f1"] is None
    assert seen["football/nfl"] == "20260829-20260830"
