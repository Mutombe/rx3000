"""Find endpoints no screen ever calls.

    python qa/endpoint-coverage.py           # grouped summary
    python qa/endpoint-coverage.py --all     # every route

The third of three coverage checks, and the bluntest:

    qa/dormant-fields.py     is a column ever written?
    qa/form-coverage.py      is a request field ever mentioned by the front end?
    qa/endpoint-coverage.py  is a route ever called by the front end?

Written after the field sweep, because that sweep kept saying "reachable through
the API" about things no human could reach. `products.bin_location` was on the
product schema for weeks and NULL on all 545 products, because no form had a
field for it — the backend was blameless and the feature did not exist.

The first run found 92 of 291 routes uncalled, including whole subsystems built
back-to-front: stock takes, lay-bys, remittances, compounding, fee models and the
dosage-abbreviation book all had complete APIs and no screen at all. Several had
been reported as delivered on the strength of the backend and its reports.

HOW IT DECIDES

A route counts as called if the literal part of its path — everything before the
first `{` — appears anywhere under frontend/src. A template literal like
`/api/laybys/${id}/pay` contains `/api/laybys/`, so prefix matching is what works
against a real front end.

WHAT A FINDING IS NOT

Uncalled is not automatically wrong. Some routes exist for other callers and
should never appear in this front end:

  * webhooks and public endpoints (`/api/public/...`)
  * machine-to-machine gateway traffic, which the backend itself submits
  * operational tools intended for a console or a cron job (`/api/ledger/backfill`)
  * anything the desktop shell or the patient portal calls instead

So this prints a list to read, not a defect count. The value is that a subsystem
with a dozen uncalled routes is visible immediately, which is how the six above
were found.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
# The app reads a relative SQLite path at import time.
import os  # noqa: E402

os.chdir(ROOT / "backend")

# Route prefixes that are not this front end's business. Listed with the reason,
# so the exemption can be argued with rather than assumed.
NOT_FOR_THIS_UI = {
    "/api/public": "public webhooks — called by outside systems, not by staff",
    "/api/gateway": "machine-to-machine claim traffic submitted by the backend",
    "/api/realtime": "switch callbacks",
    "/api/portal-admin": "patient and prescriber portal links",
    "/api/parity": "an internal consistency probe",
}

# Individual routes that correctly have no screen. Named one at a time, with
# the reason, because "no screen calls it" is the right question for finding
# gaps and the wrong one for finishing: a backfill an administrator runs once
# and a check the till makes before saving are both correct as they are, and
# reporting them for ever is how a number stops being read.
#
# Anything added here is a claim somebody can disagree with. That is the point.
NO_SCREEN_ON_PURPOSE = {
    "/api/ledger/backfill":
        "posts the history that predates the posting logic — run once by an "
        "administrator, not a thing a pharmacy does",
    "/api/periods/postable/check":
        "the till asks this before saving; it is a guard, not a screen",
    "/api/auth/demo/state":
        "tells a demo build how much of its trial is left",
    "/api/currency/convert":
        "a conversion helper; every screen that shows money already holds the "
        "rates and converts locally",
    "/api/system/interactions/coverage":
        "what the interaction checker holds. The screening response carries "
        "its own coverage note on every answer, which is where it has to be "
        "read — a coverage page nobody opens is worse than none",
    "/api/repeats/due":
        "the raw script lines. /repeats/call-sheet is the same question "
        "answered for a person: who to ring, in what order, and whether the "
        "shelf can serve them",
}


def frontend_text() -> str:
    parts = []
    for path in sorted((ROOT / "frontend" / "src").rglob("*")):
        if path.suffix in (".ts", ".tsx", ".js", ".jsx") and path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def main() -> int:
    show_all = "--all" in sys.argv

    from app.main import app

    ui = frontend_text()
    if len(ui) < 100_000:
        print(f"FAIL: only {len(ui)} characters of front end read — wrong path, so "
              f"every route would look uncalled")
        return 2

    routes = [p for p in sorted(app.openapi()["paths"]) if p.startswith("/api")]
    if len(routes) < 100:
        print(f"FAIL: only {len(routes)} routes enumerated — the app did not import "
              f"fully, so 'no gaps' would mean nothing")
        return 2

    # A sanity check in the other direction: routes that certainly are called.
    for certain in ("/api/auth/login", "/api/products"):
        if certain not in ui:
            print(f"FAIL: {certain} looks uncalled, which cannot be true — the "
                  f"matching is broken")
            return 2

    uncalled = {}
    for path in routes:
        stem = path.split("{")[0].rstrip("/")
        if stem and stem in ui:
            continue
        area = "/".join(path.split("/")[:3])
        uncalled.setdefault(area, []).append(path)

    # Set the deliberately screenless routes aside before anything is counted,
    # and keep them so they can be printed. Dropping them quietly would make
    # this audit agree with itself by hiding its own exceptions, which is worse
    # than the number it was hiding.
    on_purpose = []
    for area, items in list(uncalled.items()):
        kept = []
        for route in items:
            (on_purpose if route in NO_SCREEN_ON_PURPOSE else kept).append(route)
        if kept:
            uncalled[area] = kept
        else:
            del uncalled[area]

    exempt = {a: v for a, v in uncalled.items() if a in NOT_FOR_THIS_UI}
    real = {a: v for a, v in uncalled.items() if a not in NOT_FOR_THIS_UI}
    counted = sum(len(v) for v in real.values())

    print(f"{len(routes)} API routes, {counted} not called by any screen "
          f"({counted * 100 // max(1, len(routes))}%)\n")

    print(f"{'=' * 72}\nNO SCREEN CALLS THESE\n{'=' * 72}")
    for area, items in sorted(real.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  {area}  ({len(items)})")
        for path in (items if show_all else items[:4]):
            print(f"      {path}")
        if not show_all and len(items) > 4:
            print(f"      … and {len(items) - 4} more (--all)")

    if on_purpose:
        rule = "-" * 72
        print(f"\n{rule}\nNO SCREEN ON PURPOSE — each with the reason\n{rule}")
        for route in sorted(on_purpose):
            print(f"  {route}")
            print(f"      {NO_SCREEN_ON_PURPOSE[route]}")

    if exempt:
        print(f"\n{'-' * 72}\nNOT THIS UI'S JOB — exempt, with the reason\n{'-' * 72}")
        for area, items in sorted(exempt.items()):
            print(f"  {area:22} {len(items):3}  {NOT_FOR_THIS_UI[area]}")

    return 1 if counted else 0


if __name__ == "__main__":
    raise SystemExit(main())
