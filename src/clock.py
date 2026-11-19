"""Today's date as the agents see it. Frozen when an evaluation is replayed, so prompts match the recording."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

BRASILIA = timezone(timedelta(hours=-3))  # no daylight saving since 2019

_frozen: date | None = None


def freeze(day: date | None) -> None:
    global _frozen
    _frozen = day


def today() -> date:
    return _frozen or datetime.now(BRASILIA).date()
