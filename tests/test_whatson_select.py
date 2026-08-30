"""Caps, ranking, and how the blocks go together."""

from datetime import datetime, timedelta, timezone

from fpp.displays.whatson.select import (
    CAPS,
    TOMORROW_CAPS,
    apply_caps,
    assemble,
    mark_home,
    oddity_cards,
    rank_key,
)

NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)


def card(**kw):
    base = dict(kind="event", sport="ncaaf", league_label="NCAAF", layout="match",
                start=NOW + timedelta(hours=3), day="today", state="pre",
                status_text="9:30a", channel="NBC", tier="watchable", major=False,
                home_team=False, drama=0, round_weight=0, dwell_floor=None,
                is_cup=False, title="A @ B", away={"abbr": "A"}, home={"abbr": "B"},
                score=None)
    base.update(kw)
    return base


def test_caps_are_per_sport():
    cards = [card(sport="ncaaf") for _ in range(10)] + [card(sport="nfl") for _ in range(10)]
    kept = apply_caps(cards)
    assert sum(1 for c in kept if c["sport"] == "ncaaf") == CAPS["ncaaf"]
    assert sum(1 for c in kept if c["sport"] == "nfl") == CAPS["nfl"]


def test_all_cup_slugs_share_one_cap():
    cards = [card(sport=s, is_cup=True) for s in ("ucl", "uel", "facup", "libertadores")]
    assert len(apply_caps(cards)) == CAPS["cup"]


def test_today_outranks_tomorrow():
    assert rank_key(card(day="today")) < rank_key(card(day="tomorrow"))


def test_live_outranks_upcoming_and_drama_orders_the_live_ones():
    tight = card(state="live", drama=3)
    blowout = card(state="live", drama=1)
    upcoming = card(state="pre")
    assert rank_key(tight) < rank_key(blowout) < rank_key(upcoming)


def test_watchable_outranks_payable():
    assert rank_key(card(tier="watchable")) < rank_key(card(tier="payable"))


def test_ranked_teams_outrank_unranked():
    ranked = card(home={"abbr": "USC", "rank": 3})
    plain = card(home={"abbr": "USC", "rank": None})
    assert rank_key(ranked) < rank_key(plain)


def test_home_games_bypass_caps_and_leave_the_day_blocks():
    home = [card(sport="mlb", home_team=True) for _ in range(2)]
    others = [card(sport="ncaaf") for _ in range(10)]
    slides = assemble(home, apply_caps(others), [], NOW)
    assert slides[0]["kind"] == "divider"
    assert slides[0]["title"] == "MY TEAMS"
    assert sum(1 for s in slides if s.get("home_team")) == 2


def test_assemble_orders_the_blocks_and_inserts_dividers():
    slides = assemble([card(home_team=True)],
                      [card(day="today"), card(day="tomorrow")],
                      [dict(kind="highlight", title="X", dwell_floor=15.0)], NOW)
    titles = [s["title"] for s in slides if s["kind"] == "divider"]
    assert titles == ["MY TEAMS", "TODAY", "TOMORROW", "AVAILABLE TO WATCH"]


def test_empty_everything_yields_a_single_empty_card():
    slides = assemble([], [], [], NOW)
    assert len(slides) == 1 and slides[0]["kind"] == "empty"


def test_oddity_matches_only_inside_its_window():
    during = datetime(2026, 12, 20, 20, 0, tzinfo=timezone.utc)
    outside = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)
    assert any("DARTS" in c["title"] for c in oddity_cards(during))
    assert not any("DARTS" in c["title"] for c in oddity_cards(outside))


def test_oddity_major_from_promotes_late_rounds():
    early = oddity_cards(datetime(2026, 12, 15, 20, 0, tzinfo=timezone.utc))
    late = oddity_cards(datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc))
    darts_early = [c for c in early if "DARTS" in c["title"]][0]
    darts_late = [c for c in late if "DARTS" in c["title"]][0]
    assert darts_early["major"] is False
    assert darts_late["major"] is True


def test_payable_oddity_needs_to_be_major_to_appear():
    # Snooker is on DAZN (payable) and only major from 30 Apr.
    early = oddity_cards(datetime(2027, 4, 20, 20, 0, tzinfo=timezone.utc))
    late = oddity_cards(datetime(2027, 5, 1, 20, 0, tzinfo=timezone.utc))
    assert not any("SNOOKER" in c["title"] for c in early)
    assert any("SNOOKER" in c["title"] for c in late)


def test_mark_home_flags_configured_teams_only():
    seattle = card(away={"abbr": "SEA", "name": "Seattle Mariners"},
                   home={"abbr": "TOR", "name": "Toronto Blue Jays"}, sport="mlb")
    other = card(away={"abbr": "NYY", "name": "New York Yankees"},
                 home={"abbr": "BOS", "name": "Boston Red Sox"}, sport="mlb")
    marked = mark_home([seattle, other])
    assert marked[0]["home_team"] is True
    assert marked[1]["home_team"] is False


def test_tomorrow_gets_its_own_slots_rather_than_today_taking_them_all():
    """Regression: caps used to apply across the whole window.

    rank_key sorts today ahead of tomorrow, so today consumed every slot of
    every sport and the TOMORROW block was empty on any busy day — the board
    ran for a day showing only today.
    """
    today = [card(sport="epl", day="today") for _ in range(5)]
    tomorrow = [card(sport="epl", day="tomorrow") for _ in range(4)]
    kept = apply_caps(today + tomorrow)
    assert [c for c in kept if c["day"] == "tomorrow"], "tomorrow must not be starved"
    assert len([c for c in kept if c["day"] == "today"]) == CAPS["epl"]


def test_tomorrow_is_a_preview_not_a_second_full_board():
    tomorrow = [card(sport="ncaaf", day="tomorrow") for _ in range(20)]
    kept = apply_caps(tomorrow)
    assert len(kept) == TOMORROW_CAPS["ncaaf"]
    assert TOMORROW_CAPS["ncaaf"] < CAPS["ncaaf"]
