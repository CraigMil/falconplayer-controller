"""Per-card dwell. QR cards are the exception that drives the whole rule."""

from fpp.cli import _whatson_dwell


def ev(**kw):
    d = {"kind": "event", "dwell_floor": None}
    d.update(kw)
    return d


def test_quiet_board_uses_the_full_interval():
    assert _whatson_dwell([ev(), ev()], interval=12, cycle=210, min_interval=6) == [12.0, 12.0]


def test_busy_board_shrinks_towards_the_floor():
    dwells = _whatson_dwell([ev() for _ in range(40)], interval=12, cycle=210, min_interval=6)
    assert all(d == 6.0 for d in dwells)


def test_highlight_cards_keep_their_floor_when_everything_else_shrinks():
    slides = [ev() for _ in range(20)] + [ev(kind="highlight", dwell_floor=15.0)]
    dwells = _whatson_dwell(slides, interval=12, cycle=210, min_interval=6)
    assert dwells[-1] == 15.0
    assert dwells[0] < 15.0


def test_worst_case_lap_stays_near_the_cycle_budget():
    slides = ([ev() for _ in range(20)] + [ev(kind="divider")] * 4
              + [ev(kind="highlight", dwell_floor=15.0)] * 3)
    total = sum(_whatson_dwell(slides, interval=12, cycle=210, min_interval=6))
    assert total <= 230, f"lap ran to {total}s"


def test_the_refresh_wait_always_exceeds_a_lap():
    """Regression: the wait used to equal the lap exactly.

    The playlist is restarted from card 0 each cycle, so any overhead — 22
    image uploads, playlist-start latency — clipped the tail, and the tail is
    always the AVAILABLE TO WATCH block. The wait must leave slack.
    """
    from fpp.cli import _LAP_MARGIN
    slides = [ev() for _ in range(19)] + [ev(kind="highlight", dwell_floor=15.0)] * 3
    dwells = _whatson_dwell(slides, interval=12, cycle=210, min_interval=6)
    lap = sum(dwells)
    wait = max(lap + _LAP_MARGIN, 60)
    assert wait > lap, "a lap must be able to finish before the rebuild"
    assert wait - lap >= 15
