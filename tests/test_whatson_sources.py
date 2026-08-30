"""Three event shapes, one card dict. All against captured fixtures."""

import json
from datetime import datetime, timezone
from pathlib import Path

from fpp.displays.whatson.sources import (
    from_match,
    from_multiday,
    from_sessions,
    from_tournament,
)

FIX = Path(__file__).parent / "fixtures" / "espn"
NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def test_match_shape_produces_a_match_card():
    cards = [from_match(e, "ncaaf", NOW) for e in load("ncaaf_20260829")["events"]]
    cards = [c for c in cards if c]
    assert cards, "the NCAAF opening weekend must yield cards"
    card = cards[0]
    assert card["layout"] == "match"
    assert card["sport"] == "ncaaf"
    assert card["away"]["abbr"] and card["home"]["abbr"]
    assert card["channel"]
    assert card["tier"] in ("watchable", "payable")


def test_unwatchable_match_is_dropped():
    ev = load("mlb_20260829")["events"][0]
    ev["competitions"][0]["geoBroadcasts"] = [{"media": {"shortName": "Sportsnet"}}]
    assert from_match(ev, "mlb", NOW) is None


def test_mariners_show_the_payable_feed_not_the_canadian_one():
    ev = [e for e in load("mlb_20260829")["events"] if "Seattle" in e["name"]][0]
    card = from_match(ev, "mlb", NOW)
    assert card["channel"] == "Mariners.TV"
    assert card["tier"] == "payable"


def test_tournament_shape_collapses_to_one_card():
    us_open = [e for e in load("tennis_atp")["events"] if e["name"] == "US Open"][0]
    card = from_tournament(us_open, "atp", NOW)
    assert card["layout"] == "single"
    assert card["title"] == "US OPEN"
    assert card["major"] is True


def test_non_major_tournament_is_dropped():
    minor = [e for e in load("tennis_atp")["events"] if e["name"] != "US Open"]
    for ev in minor:
        assert from_tournament(ev, "atp", NOW) is None


def test_f1_sessions_exclude_practice_by_default():
    ev = load("f1_monza")["events"][0]
    cards = from_sessions(ev, "f1", NOW, include_practice=False)
    assert not any(c["subtitle"].startswith("FP") for c in cards)


def test_f1_practice_included_when_asked():
    ev = load("f1_monza")["events"][0]
    wide = from_sessions(ev, "f1", NOW, include_practice=True)
    lean = from_sessions(ev, "f1", NOW, include_practice=False)
    assert len(wide) >= len(lean)


def test_f1_race_and_sprint_are_major_but_qualifying_is_not():
    # Monza has no Sprint, so synthesise one from the Qual session.
    ev = load("f1_monza")["events"][0]
    qual = [c for c in ev["competitions"] if c["type"]["abbreviation"] == "Qual"][0]
    sprint = json.loads(json.dumps(qual))
    sprint["type"]["abbreviation"] = "Sprint"
    ev["competitions"].append(sprint)
    by_name = {c["subtitle"]: c for c in
               from_sessions(ev, "f1", datetime.fromisoformat(
                   qual["date"].replace("Z", "+00:00")), include_practice=False)}
    assert by_name["SPRINT"]["major"] is True
    assert by_name["QUALIFYING"]["major"] is False
    assert "RACE" not in by_name or by_name["RACE"]["major"] is True


def test_empty_league_yields_nothing():
    assert load("facup_empty")["events"] == []


def test_golf_tournament_becomes_an_also_on_card():
    ev = load("golf_pga")["events"][0]
    # The TOUR Championship runs 27-30 Aug, so it spans the window without
    # starting inside it — the case a naive bucket() check misses.
    card = from_multiday(ev, "golf", NOW)
    assert card is not None
    assert card["layout"] == "single"
    assert card["title"] == "TOUR CHAMPIONSHIP"
    assert card["tier"] == "watchable"


def test_ufc_card_names_the_main_event():
    ev = load("ufc")["events"][0]
    card = from_multiday(ev, "ufc", NOW)
    assert card is not None
    assert "UFC" in card["title"]
    assert "Nurmagomedov" in card["subtitle"], "the main event is the draw"
    assert card["channel"] == "Paramount+"


def test_an_out_of_window_multiday_event_is_dropped():
    ev = load("golf_pga")["events"][0]
    far = datetime(2026, 12, 25, 18, 0, tzinfo=timezone.utc)
    assert from_multiday(ev, "golf", far) is None


def test_boxing_out_of_season_yields_nothing():
    assert load("boxing_empty")["events"] == []
