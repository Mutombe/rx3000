"""Dispensing policy by medicine schedule.

The rules themselves live in `jurisdictions.py` — this module resolves them for
whichever pack the installation runs under, so callers never need to know which
country they are in.
"""
from dataclasses import asdict

from .config import settings
from .jurisdictions import SchedulePolicy  # re-exported for type hints

__all__ = ["SchedulePolicy", "policy_for", "route_for", "all_policies",
           "schedules_for_route", "effective_max_repeats", "all_policies_raw"]


def schedules_for_route(route: str) -> list[int]:
    """Which schedule numbers a dispensing route covers in this jurisdiction.

    Routes are stable across packs (otc / prescription / controlled / prohibited)
    but the schedules behind them are not, so callers must ask rather than assume.
    """
    return [s for s, p in settings.jurisdiction.schedules.items() if p.route == route]


def policy_for(schedule: int | None) -> SchedulePolicy:
    return settings.jurisdiction.policy_for(schedule)


def route_for(schedule: int | None) -> str:
    return policy_for(schedule).route


def all_policies() -> list[dict]:
    return [asdict(p) for p in settings.jurisdiction.schedules.values()]


def all_policies_raw() -> list[SchedulePolicy]:
    """The policy objects themselves, for callers that want to read fields."""
    return list(settings.jurisdiction.schedules.values())


def effective_max_repeats(schedule: int | None, requested: int) -> int:
    """Cap a script's requested repeats at what the schedule legally allows."""
    policy = policy_for(schedule)
    if policy.max_repeats < 0:
        return requested
    return min(requested, policy.max_repeats)
