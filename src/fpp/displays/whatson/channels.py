"""Broadcast names in, a tier and a display name out.

ESPN reports whatever the rights-holder calls itself that week, so everything
here is defensive: match on a normalised name, and treat anything unrecognised
as unavailable rather than guessing the user can watch it.
"""

from __future__ import annotations

import re

WATCHABLE = {
    # broadcast + cable
    "NBC", "CBS", "ABC", "FOX", "ESPN", "ESPN2", "ESPNU", "ESPNEWS", "FS1", "FS2",
    "USA", "TNT", "TBS", "truTV", "CNBC", "Golf Channel", "BTN", "SEC Network",
    "ACC Network", "ACCN", "Pac-12 Network", "NFL Network", "MLB Network", "NBA TV",
    "CBS Sports Network", "Spectrum Sports Net",
    # streaming the user has
    "Peacock", "Paramount+", "ESPN+", "Apple TV", "Prime Video", "Netflix", "Max",
    "Fox One", "Fox Sports App",
}

# Services the user could buy but does not have. Shown only for major events,
# and always marked with a "$".
PAYABLE = {
    "DAZN", "Fubo", "beIN Sports", "FloSports", "Victory+", "Willow", "WRC+",
    "MLB.TV", "Mariners.TV", "NWSL+", "NBA League Pass", "NHL Power Play",
}

# Never shown: no US rights, or a foreign-language-only feed.
UNAVAILABLE = {"Sportsnet", "TVA", "Universo", "TUDN", "Telemundo Deportes", "Sky Sports"}

_ALIASES = {
    "USA Net": "USA",
    "NBC Sports": "NBC",
    "CBS Sports Net": "CBS Sports Network",
    "Paramount Plus": "Paramount+",
    "Amazon Prime Video": "Prime Video",
    "HBO Max": "Max",
    "Golf Chnl": "Golf Channel",
    # ESPN's rebrand of ESPN+. Craig has it; unrecognised names default to
    # payable, so it was showing a "$" on tennis he can already watch.
    "ESPN Unlmtd": "ESPN+",
    "ESPN Unlimited": "ESPN+",
    "ESPN Select": "ESPN+",
}

# A bare local call sign — KOMO-TV, KING 5, KIRO. These are free over the air,
# so the Storm on KOMO must not be marked as costing money.
_CALLSIGN = re.compile(r"^K[A-Z]{2,3}\b|^W[A-Z]{2,3}\b")

# ESPN suffixes a regional feed with its market: "Prime Video-Seattle".
_REGIONAL = re.compile(r"\s*[-–]\s*(Seattle|Portland|Bay Area|LA|Chicago|New York|Boston)$")


def normalise(name: str) -> str:
    """Canonical display name for a broadcast, before any tier decision."""
    n = (name or "").strip()
    n = _REGIONAL.sub("", n)
    return _ALIASES.get(n, n)


def tier_of(name: str) -> str:
    """One of "watchable", "payable", "unavailable"."""
    n = normalise(name)
    if n in UNAVAILABLE:
        return "unavailable"
    if n in WATCHABLE:
        return "watchable"
    if n in PAYABLE:
        return "payable"
    if _CALLSIGN.match(n):
        return "watchable"
    # Unrecognised. Assume the worst rather than promising a channel the user
    # may not have — an unknown name is far more often a niche service than a
    # cable channel we forgot.
    return "payable"


_ORDER = {"watchable": 0, "payable": 1}

# League-wide out-of-market packages black out the local team's game, so when a
# team-specific feed is also listed, that one is the useful answer. Deprioritised
# rather than removed: out of market they are exactly the right subscription.
_BLACKED_OUT_LOCALLY = {"MLB.TV", "NBA League Pass", "NHL Power Play", "NFL Sunday Ticket"}


def best_channel(names):
    """The best showable broadcast: (display name, tier), or None if there is none.

    Watchable beats payable; unavailable is never returned, so a Mariners game
    listing Sportsnet and TVA alongside Mariners.TV shows the one the user could
    actually buy.
    """
    scored = []
    for raw in names or []:
        n = normalise(raw)
        t = tier_of(n)
        if t == "unavailable":
            continue
        scored.append((_ORDER[t], 1 if n in _BLACKED_OUT_LOCALLY else 0, n, t))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]))
    return scored[0][2], scored[0][3]
