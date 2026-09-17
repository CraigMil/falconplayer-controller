"""Where the day's cache and the flag images live.

Not simply ~/.cache: on the Falcon Player, /home/fpp/.cache is owned by ROOT
(it has been since 2024, nothing to do with this service), so the fpp user
cannot create a subdirectory there. The service's first live deploy therefore
made its one Anthropic call a day, succeeded, and then threw the answer away on
a PermissionError — the most expensive possible way to fail.

systemd's CacheDirectory= is the correct answer: it creates the directory owned
by the unit's User and exports CACHE_DIRECTORY. This module honours that, with
an explicit override for anyone running the CLI by hand.
"""

from __future__ import annotations

import os
from pathlib import Path


def base() -> Path:
    override = os.environ.get("FPP_ONTHISDAY_CACHE")
    if override:
        return Path(override)
    # systemd may hand over a colon-separated list; the first is ours.
    managed = os.environ.get("CACHE_DIRECTORY")
    if managed:
        return Path(managed.split(":")[0])
    return Path.home() / ".cache" / "fpp-onthisday"
