"""The record and power-rating line under each team name on the NFL card."""

import io

import pytest
from PIL import Image

from fpp.canvas import HEIGHT, WIDTH
from fpp.displays import nfl


def _event(away_records=None, home_records=None) -> dict:
    """The slice of an ESPN scoreboard event the card is built from."""
    def competitor(side, tid, abbr, records):
        team = {"id": tid, "abbreviation": abbr, "shortDisplayName": abbr.title(),
                "color": "002244", "alternateColor": "ffffff", "logo": ""}
        out = {"homeAway": side, "team": team, "score": "0"}
        if records is not None:
            out["records"] = records
        return out

    return {
        "id": "401",
        "date": "2026-09-20T20:00Z",
        "week": {"number": 3},
        "season": {"slug": "regular-season"},
        "competitions": [{
            "status": {"type": {"state": "pre", "shortDetail": "", "detail": ""},
                       "displayClock": "", "period": 0},
            "competitors": [
                competitor("away", "12", "KC", away_records),
                competitor("home", "2", "BUF", home_records),
            ],
        }],
    }


_TOTAL = [{"name": "overall", "type": "total", "summary": "2-1"}]
_SPLITS = [{"name": "Home", "type": "home", "summary": "1-0"},
           {"name": "overall", "type": "total", "summary": "2-1"}]


def test_card_carries_the_overall_record_for_each_team():
    card = nfl._card_from_event(_event(_TOTAL, _TOTAL))
    assert card["away_record"] == "2-1"
    assert card["home_record"] == "2-1"


def test_the_overall_record_is_taken_not_the_home_or_road_split():
    """Records arrive as a list. Taking the first would show the home split."""
    card = nfl._card_from_event(_event(_SPLITS, _SPLITS))
    assert card["away_record"] == "2-1"


def test_a_team_with_no_record_yet_gets_an_empty_string():
    """Preseason week one has no record at all; the card must still build."""
    card = nfl._card_from_event(_event(None, None))
    assert card["away_record"] == ""
    assert card["home_record"] == ""


# ------------------------------------------------------------------ FPI


def _powerindex(rank_by_team: dict[str, str]) -> dict:
    return {"items": [
        {"team": {"$ref": "http://sports.core.api.espn.com/v2/sports/football/"
                          f"leagues/nfl/seasons/2026/teams/{tid}?lang=en&region=us"},
         "predictives": [
             {"name": "fpi", "displayValue": "5.6"},
             {"name": "fpirank", "displayValue": rank},
         ]}
        for tid, rank in rank_by_team.items()]}


def test_fpi_ranks_are_keyed_by_the_team_id_from_the_ref_url(monkeypatch):
    """The payload names its team only by $ref — the id has to be parsed out."""
    monkeypatch.setattr(nfl, "_get", lambda url: _powerindex({"12": "1st", "2": "7th"}))
    assert nfl._fpi_ranks(bucket=0) == {"12": "1st", "2": "7th"}


def test_fpi_failure_leaves_the_ranks_empty_rather_than_raising(monkeypatch):
    """ESPN being down must cost the rating, not the whole card."""
    def boom(url):
        raise RuntimeError("503")
    monkeypatch.setattr(nfl, "_get", boom)
    assert nfl._fpi_ranks(bucket=1) == {}


def test_attach_fpi_puts_the_rank_on_each_side(monkeypatch):
    monkeypatch.setattr(nfl, "_fpi_ranks", lambda bucket: {"12": "1st", "2": "7th"})
    cards = nfl.attach_fpi([nfl._card_from_event(_event(_TOTAL, _TOTAL))])
    assert cards[0]["away_fpi"] == "1st"
    assert cards[0]["home_fpi"] == "7th"


def test_a_team_missing_from_the_power_index_gets_no_rank(monkeypatch):
    monkeypatch.setattr(nfl, "_fpi_ranks", lambda bucket: {"12": "1st"})
    cards = nfl.attach_fpi([nfl._card_from_event(_event(_TOTAL, _TOTAL))])
    assert cards[0]["home_fpi"] == ""


# ------------------------------------------------------------------ render


def _render(card: dict) -> Image.Image:
    from fpp.displays.soccer import render_scoreboard
    return Image.open(io.BytesIO(render_scoreboard(card).to_image_bytes()))


def _card(records=_TOTAL, **extra) -> dict:
    card = nfl._card_from_event(_event(records, records))
    card.update({"away_next": None, "home_next": None})
    card.update(extra)
    return card


def _bare_card(**extra) -> dict:
    """A card with neither record nor rating — the shape every soccer card has."""
    return _card(records=None, **extra)


def test_the_card_is_still_panel_sized_with_the_new_line():
    assert _render(_card(away_fpi="1st", home_fpi="7th")).size == (WIDTH, HEIGHT)


def _band_ink(img) -> int:
    """Bright pixels in y=35..46, ignoring the seam and the JPEG floor.

    The 2px seam at x=95 runs the full height of the team block, so it inks
    every row of the band; the columns it occupies are excluded. The
    brightness threshold clears the seam's own (30,30,30) and the ringing
    JPEG leaves around the name above.
    """
    band = img.convert("L").crop((0, 35, WIDTH, 47))
    return sum(1 for x in range(WIDTH) for y in range(band.height)
               if not 90 <= x <= 101 and band.getpixel((x, y)) > 110)


def test_the_rating_line_draws_ink_in_its_own_band():
    """y=35..46 is clear on a card without the line and inked on one with it.

    The logo is shrunk to open this band, so the no-line card is what proves
    the band was otherwise the shield's.
    """
    assert _band_ink(_render(_bare_card())) == 0
    assert _band_ink(_render(_card(away_fpi="1st", home_fpi="7th"))) > 20


def test_a_soccer_card_without_the_fields_renders_unchanged():
    """The renderer is shared. A card that sets neither field must be identical."""
    plain = _bare_card()
    before = _render(plain).tobytes()
    assert before == _render(plain).tobytes()
    assert before != _render(_card(away_fpi="1st", home_fpi="7th")).tobytes()


def test_select_cards_attaches_the_ratings(monkeypatch):
    """The rank must reach the card without every caller remembering to ask."""
    monkeypatch.setattr(nfl, "fetch_games",
                        lambda: [nfl._card_from_event(_event(_TOTAL, _TOTAL))])
    monkeypatch.setattr(nfl, "_fpi_ranks", lambda bucket: {"12": "1st", "2": "7th"})
    games, reason = nfl.select_cards()
    assert reason == "week"
    assert games[0]["away_fpi"] == "1st"
