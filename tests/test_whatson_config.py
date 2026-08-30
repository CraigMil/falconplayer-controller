"""The editable config files load and carry what the design expects."""

from fpp.displays.whatson.config import highlight_sources, home_teams, oddities


def test_home_teams_cover_every_seattle_sport():
    teams = {h["team"] for h in home_teams()}
    assert "Seattle Mariners" in teams
    assert "Seattle Sounders FC" in teams
    assert "Washington Huskies" in teams
    assert all("slug" in h for h in home_teams())


def test_oddities_carry_a_window_and_a_channel():
    for o in oddities():
        assert o["start"] and o["end"] and o["channel"]
        assert o["start"] <= o["end"]


def test_rally_is_major_and_payable_by_channel():
    rally = [o for o in oddities() if "WRC" in o["name"]]
    assert rally, "rally must be present"
    assert all(o["channel"] == "WRC+" and o.get("major") for o in rally)


def test_highlight_sources_all_have_patterns_and_channel_ids():
    for s in highlight_sources():
        assert s["channel_id"].startswith("UC")
        assert len(s["channel_id"]) == 24, f"{s['name']} has a malformed channel id"
        assert s["patterns"]
