"""Every card kind renders. Smoke tests: no exceptions, right dimensions."""

from datetime import datetime, timezone

import pytest

from fpp.displays.whatson.cards import render

NOW = datetime(2026, 8, 29, 16, 30, tzinfo=timezone.utc)


def base(**kw):
    b = dict(kind="event", sport="ncaaf", league_label="NCAAF", layout="match",
             start=NOW, day="today", state="pre", status_text="9:30a",
             channel="NBC", tier="watchable", major=False, home_team=False,
             drama=0, round_weight=0, dwell_floor=None, is_cup=False,
             title="SJSU @ USC", subtitle="", detail="", score=None,
             away={"abbr": "SJSU", "logo": "", "record": "0-0", "rank": None},
             home={"abbr": "USC", "logo": "", "record": "0-0", "rank": 21})
    b.update(kw)
    return b


@pytest.mark.parametrize("card", [
    base(),
    base(state="live", status_text="LIVE Q3", score=(17, 21)),
    base(tier="payable", channel="Mariners.TV"),
    base(layout="single", title="US OPEN", subtitle="Round of 16", detail="Men's & Women's"),
    base(layout="single", title="ITALIAN GP", subtitle="RACE", detail="Monza", channel="Apple TV"),
    dict(kind="divider", title="TODAY", subtitle="SAT · AUG 29", count=6, sport="divider"),
    dict(kind="divider", title="MY TEAMS", subtitle="", count=3, sport="divider"),
    dict(kind="empty", title="NOTHING ON", subtitle="next: EPL Sat 4:30a", sport="empty"),
])
def test_every_card_kind_renders_to_a_192_square(card):
    frame = render(card)
    assert frame._img.size == (192, 192)
    data = frame.to_image_bytes()
    assert data[:2] == b"\xff\xd8", "JPEG magic"
    assert len(data) > 500


def test_highlight_card_renders_with_a_qr():
    card = dict(kind="highlight", sport="highlight", title="ITALIAN GP",
                subtitle="Race Highlights", age="2h",
                url="https://youtu.be/dQw4w9WgXcQ", dwell_floor=15.0)
    assert render(card).to_image_bytes()[:2] == b"\xff\xd8"


def test_highlight_card_splits_a_matchup_onto_two_lines():
    card = dict(kind="highlight", sport="highlight",
                title="NC STATE WOLFPACK VS. VIRGINIA CAVALIERS",
                subtitle="ESPN College Football", age="1h",
                url="https://youtu.be/dQw4w9WgXcQ", dwell_floor=15.0)
    assert render(card).to_image_bytes()[:2] == b"\xff\xd8"


def test_highlight_card_without_a_matchup_still_renders():
    card = dict(kind="highlight", sport="highlight", title="ITALIAN GP",
                subtitle="Race Highlights", age="2h",
                url="https://youtu.be/dQw4w9WgXcQ", dwell_floor=15.0)
    assert render(card).to_image_bytes()[:2] == b"\xff\xd8"


def test_highlight_strips_a_descriptor_from_the_second_competitor():
    import re

    from fpp.displays.whatson.cards import _VS
    title = "JUVENTUS VS. PARMA: EXTENDED HIGHLIGHTS"
    parts = _VS.split(title, maxsplit=1)
    assert len(parts) == 2
    opponent = re.split(r"\s*[:|]\s*", parts[1], maxsplit=1)[0]
    assert opponent == "PARMA"


def test_a_long_headline_wraps_instead_of_overflowing():
    from fpp.displays.whatson.cards import _wrap
    rows = _wrap("NEWCASTLE UPEND SPURS; HULL CITY STUN COVENTRY CITY", 2)
    assert len(rows) == 2
    assert all(len(r) < 34 for r in rows), rows
    assert " ".join(rows) == "NEWCASTLE UPEND SPURS; HULL CITY STUN COVENTRY CITY"


def test_a_short_headline_stays_on_one_line():
    from fpp.displays.whatson.cards import _wrap
    assert _wrap("ITALIAN GP", 2) == ["ITALIAN GP"]
