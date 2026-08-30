"""YouTube RSS in, at most three QR cards out."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpp.displays.whatson.highlights import matches, parse_feed, select

FEED = (Path(__file__).parent / "fixtures" / "youtube" / "f1_feed.xml").read_text()
NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)

PATTERNS = ["Race Highlights", "Qualifying Highlights", "Sprint Highlights"]


def test_parse_feed_returns_titles_ids_and_dates():
    entries = parse_feed(FEED)
    assert len(entries) == 6
    e = entries[0]
    assert e["video_id"] and e["title"]
    assert e["published"].tzinfo is not None


def test_filler_videos_do_not_match():
    assert not matches({"title": "Can Valtteri & Sergio Complete These Challenges?!"}, PATTERNS)
    assert not matches({"title": "Lando Norris Ranks His Best F1 Moments!"}, PATTERNS)


def test_highlight_titles_match_case_insensitively():
    assert matches({"title": "Italian GP | RACE HIGHLIGHTS"}, PATTERNS)


def test_the_real_feed_yields_only_the_three_highlight_videos():
    fresh = [e for e in parse_feed(FEED) if matches(e, PATTERNS)]
    assert len(fresh) == 4, "3 recent + 1 stale, filler excluded"


def test_only_the_last_48_hours_qualify():
    fresh = {"title": "Race Highlights", "video_id": "a",
             "published": NOW - timedelta(hours=47)}
    stale = {"title": "Race Highlights", "video_id": "b",
             "published": NOW - timedelta(hours=49)}
    cards = select({"Formula 1": [fresh, stale]}, NOW, {"Formula 1": PATTERNS})
    assert len(cards) == 1 and cards[0]["url"].endswith("a")


def test_one_card_per_source_even_when_a_weekend_posts_three():
    entries = parse_feed(FEED)
    cards = select({"Formula 1": entries}, NOW, {"Formula 1": PATTERNS})
    assert len(cards) == 1
    assert cards[0]["url"].endswith("raceVID0001"), "most recent wins"


def test_cards_carry_the_dwell_floor_and_an_age():
    entry = {"title": "Race Highlights", "video_id": "r", "published": NOW - timedelta(hours=2)}
    card = select({"Formula 1": [entry]}, NOW, {"Formula 1": PATTERNS})[0]
    assert card["dwell_floor"] == 15.0
    assert card["age"] == "2h"
    assert card["kind"] == "highlight"


def test_at_most_three_cards_across_all_sources():
    def entry(i):
        # Distinct events — identical titles are deduplicated, which is its own test.
        return {"title": f"Race {i} | Race Highlights", "video_id": f"v{i}",
                "published": NOW - timedelta(hours=i + 1)}

    by_source = {f"src{i}": [entry(i)] for i in range(6)}
    patterns = {f"src{i}": PATTERNS for i in range(6)}
    assert len(select(by_source, NOW, patterns)) == 3


def test_a_malformed_feed_yields_nothing_rather_than_raising():
    assert parse_feed("<not-xml") == []


def test_a_title_without_a_pipe_uses_the_source_as_subtitle():
    entry = {"title": "NC State Wolfpack vs. Virginia Cavaliers",
             "video_id": "x", "published": NOW - timedelta(hours=1)}
    card = select({"ESPN College Football": [entry]}, NOW,
                  {"ESPN College Football": ["vs."]})[0]
    # Not truncated any more: the card splits on "vs" and shrinks to fit, so
    # clipping here would only ever lose a real competitor's name.
    assert card["title"] == "NC STATE WOLFPACK VS. VIRGINIA CAVALIERS"
    assert card["subtitle"] == "ESPN College Football"


def test_a_piped_title_splits_into_event_and_kind():
    entry = {"title": "Italian GP | Race Highlights", "video_id": "y",
             "published": NOW - timedelta(hours=1)}
    card = select({"Formula 1": [entry]}, NOW, {"Formula 1": PATTERNS})[0]
    assert card["title"] == "ITALIAN GP"
    assert card["subtitle"] == "Race Highlights"


def test_the_same_game_posted_by_two_channels_appears_once():
    same = {"title": "NC State vs. Virginia | Full Game Highlights",
            "video_id": "a", "published": NOW - timedelta(hours=1)}
    dupe = {"title": "NC State vs. Virginia | Full Game Highlights",
            "video_id": "b", "published": NOW - timedelta(hours=2)}
    cards = select({"ESPN": [same], "ACC": [dupe]}, NOW,
                   {"ESPN": ["Highlights"], "ACC": ["Highlights"]})
    assert len(cards) == 1
