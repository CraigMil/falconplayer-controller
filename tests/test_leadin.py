"""The intro leadIn: when it is included, and what it looks like."""

import pytest

from fpp.cli import _INTRO_PAUSE, _INTRO_VIDEO, _WEEK_IMAGE, _intro_entries


class FakeClient:
    """Just enough FPPClient for the lead-in decision."""

    def __init__(self, media=()):
        self._media = list(media)
        self.uploaded = []

    def list_media(self):
        return list(self._media)

    def upload_file(self, file_type, filename, data):
        self.uploaded.append((file_type, filename, len(data)))


def _entries(**kw):
    args = dict(fpp=FakeClient([_INTRO_VIDEO]), league="nfl", week_label="WEEK 3",
                enabled=True, last_played=None, now=1000.0, every_secs=1800.0)
    args.update(kw)
    return _intro_entries(**args)


def test_the_leadin_is_video_then_week_card_then_pause():
    entries, played = _entries()
    assert [e["type"] for e in entries] == ["media", "image", "pause"]
    assert entries[0]["mediaName"] == _INTRO_VIDEO
    assert entries[1]["imagePath"] == _WEEK_IMAGE
    assert entries[2]["duration"] == _INTRO_PAUSE
    assert played == 1000.0


def test_the_video_entry_uses_fpp_9_5_2s_media_shape_not_video():
    """FPP 9.5.2 writes video entries as type media + mediaName. type 'video'
    with videoName is silently ignored — the entry just never plays."""
    entries, _ = _entries()
    assert entries[0]["type"] == "media"
    assert "videoName" not in entries[0]
    assert entries[0]["enabled"] == 1


def test_the_week_card_is_uploaded_but_the_video_never_is():
    """Re-uploading a file the decoder holds open wedges fppd. The video is
    shipped once from led-animations; this command only ever reads."""
    fpp = FakeClient([_INTRO_VIDEO])
    _entries(fpp=fpp)
    names = [n for _, n, _ in fpp.uploaded]
    assert names == [_WEEK_IMAGE]
    assert _INTRO_VIDEO not in names


def test_no_leadin_when_the_video_is_not_on_the_device():
    entries, played = _entries(fpp=FakeClient([]))
    assert entries == []
    assert played is None


def test_no_leadin_for_soccer():
    for league in ("epl", "ucl", "all"):
        entries, played = _entries(league=league)
        assert entries == []
        assert played is None


def test_no_leadin_when_disabled():
    entries, played = _entries(enabled=False)
    assert entries == []
    assert played is None


def test_throttled_inside_the_window():
    """Live football refetches every couple of minutes. Without this the
    intro would play every couple of minutes, which is the whole reason it
    is in leadIn rather than mainPlaylist."""
    entries, played = _entries(last_played=1000.0, now=1600.0, every_secs=1800.0)
    assert entries == []
    assert played == 1000.0


def test_plays_again_once_the_window_has_passed():
    entries, played = _entries(last_played=1000.0, now=2900.0, every_secs=1800.0)
    assert len(entries) == 3
    assert played == 2900.0


def test_the_boundary_is_inclusive():
    entries, played = _entries(last_played=1000.0, now=2800.0, every_secs=1800.0)
    assert len(entries) == 3
    assert played == 2800.0


@pytest.mark.parametrize("label", ["WEEK 1", "SUPER BOWL", "NFL"])
def test_any_week_label_produces_a_card(label):
    fpp = FakeClient([_INTRO_VIDEO])
    entries, _ = _entries(fpp=fpp, week_label=label)
    assert len(entries) == 3
    assert fpp.uploaded[0][2] > 0        # non-empty jpeg
