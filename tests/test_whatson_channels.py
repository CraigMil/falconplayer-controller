"""Which broadcasts the user may see, and what the card prints."""

import pytest

from fpp.displays.whatson.channels import best_channel, normalise, tier_of


@pytest.mark.parametrize("raw,expected", [
    ("USA Net", "USA"),
    ("NBC Sports", "NBC"),
    ("Prime Video-Seattle", "Prime Video"),   # regional suffix strips to the parent
    ("ESPN+", "ESPN+"),
])
def test_normalise_known_variants(raw, expected):
    assert normalise(raw) == expected


@pytest.mark.parametrize("name,tier", [
    ("NBC", "watchable"),
    ("SEC Network", "watchable"),
    ("Peacock", "watchable"),
    ("Apple TV", "watchable"),
    ("Prime Video-Seattle", "watchable"),
    ("KOMO-TV", "watchable"),      # bare local call sign, free over the air
    ("Mariners.TV", "payable"),
    ("NWSL+", "payable"),
    ("DAZN", "payable"),
    ("Sportsnet", "unavailable"),  # Canadian
    ("TVA", "unavailable"),
])
def test_tier_of(name, tier):
    assert tier_of(name) == tier


def test_spanish_only_is_unavailable_but_paired_is_watchable():
    assert best_channel(["Universo"]) is None
    assert best_channel(["USA Net", "Universo"]) == ("USA", "watchable")


def test_prefers_watchable_over_payable_and_never_shows_foreign():
    # The real Mariners broadcast list, from tests/fixtures/espn/mlb_20260829.json
    assert best_channel(["MLB.TV", "Mariners.TV", "Sportsnet", "TVA"]) == ("Mariners.TV", "payable")


def test_no_broadcast_at_all_is_none():
    assert best_channel([]) is None


@pytest.mark.parametrize("raw", ["ESPN Unlmtd", "ESPN Unlimited", "ESPN Select"])
def test_espn_plus_rebrands_are_watchable_not_payable(raw):
    """These appeared on US Open cards marked '$' — ESPN's own rename of ESPN+,
    which Craig has. Unrecognised names default to payable, so each alias has
    to be known explicitly."""
    assert normalise(raw) == "ESPN+"
    assert tier_of(raw) == "watchable"
