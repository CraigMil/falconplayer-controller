"""The three editable YAML files, loaded once.

These live in src/fpp/data/ so they ship with the package and can be edited on
the device without a redeploy of code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_DATA = Path(__file__).resolve().parent.parent.parent / "data"


def _load(name: str):
    path = _DATA / name
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text()) or []


@lru_cache(maxsize=1)
def home_teams():
    return _load("home_teams.yaml")


@lru_cache(maxsize=1)
def oddities():
    return _load("oddities.yaml")


@lru_cache(maxsize=1)
def highlight_sources():
    return _load("highlight_sources.yaml")
