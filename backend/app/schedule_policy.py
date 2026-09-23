"""Dispensing policy by medicine schedule.

The rules themselves live in `jurisdictions.py` — this module resolves them for
whichever pack the installation runs under, so callers never need to know which
country they are in.
"""
from dataclasses import asdict

from .config import settings
from .jurisdictions import SchedulePolicy  # re-exported for type hints

__all__ = ["SchedulePolicy", "policy_for", "route_for", "all_policies",
           "schedules_for_route", "effective_max_repeats", "all_policies_raw",
           "code_for", "range_for"]


def schedules_for_route(route: str) -> list[int]:
    """Which schedule numbers a dispensing route covers in this jurisdiction.

    Routes are stable across packs (otc / prescription / controlled / prohibited)
    but the schedules behind them are not, so callers must ask rather than assume.
    """
    return [s for s, p in settings.jurisdiction.schedules.items() if p.route == route]


def policy_for(schedule: int | None) -> SchedulePolicy:
    return settings.jurisdiction.policy_for(schedule)


def code_for(schedule: int | None) -> str:
    """What THIS country writes on the box, the label and the register.

    The one line every caller wants and none of them had, which is why forty of
    them wrote `f"S{n}"` instead. A schedule number is an internal ordinal; the
    code is what a pharmacist says out loud and what an inspector asks about,
    and the two are only the same in South Africa.

    A register printed in Harare read "S5" where the law, the box and the
    inspector all say PP10. It sorted correctly, it looked plausible, and it was
    wrong about the single thing the column exists to say.
    """
    return policy_for(schedule).code or f"S{int(schedule or 0)}"


def range_for(low: int, high: int, joiner: str = "and") -> str:
    """Two codes as a person says them: "S5 and S6", or "PP10 and N".

    The joiner is a parameter because both readings occur and they are not
    interchangeable. A register covers PP10 AND N; a single item on a shelf is
    PP10 OR N, and "a PP10 and N item" describes one box that is somehow both.
    """
    return f"{code_for(low)} {joiner} {code_for(high)}"


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
