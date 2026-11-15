"""Prompt strategy registry.

Each strategy module exposes: NAME, SYSTEM, and build_user(request) -> str.
"""
from __future__ import annotations

from prompts import advanced, baseline

STRATEGIES = {
    advanced.NAME: advanced,
    baseline.NAME: baseline,
}


def get_strategy(name: str):
    if name not in STRATEGIES:
        raise KeyError(f"Unknown strategy {name!r}. Available: {sorted(STRATEGIES)}")
    return STRATEGIES[name]
