"""Fill the demonstration pharmacy. Run once per deployment.

    python -m app.demoseed

Deliberately a command somebody types rather than something a boot does.

The seed is about thirty-six thousand statements — two minutes against the
production database — and the host stops the service after fifteen minutes of
quiet, so a boot-time seed would sometimes be interrupted half way. It records
how far it got and refuses to start again over a partial run, but the better
answer is that a two-minute write into a live database happens because somebody
asked for it and watched it finish.

Idempotent: a second run says so and does nothing.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from .database import SessionLocal
from .services import demo_tenant


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=demo_tenant.DEMO_DAYS,
                        help="days of trade to generate")
    parser.add_argument("--fresh", action="store_true",
                        help="set a half-finished tenant aside and seed a new "
                             "one from scratch")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        pharmacy = demo_tenant.get(db)
        print(f"  demonstration pharmacy: {pharmacy.name} (id={pharmacy.id})")
        print(f"  state: {demo_tenant.state(db) or 'never seeded'}")

        if args.fresh:
            moved = demo_tenant.set_aside(db)
            if moved:
                print(f"  set aside: {moved}")
                pharmacy = demo_tenant.get(db)
                print(f"  new demonstration pharmacy: id={pharmacy.id}")

        if demo_tenant.is_seeded(db):
            print("\n  Already seeded. Nothing to do.")
            return 0

        print(f"\n  Seeding {args.days} days. This takes a couple of minutes "
              f"against a remote database.\n")
        start = time.perf_counter()
        made = demo_tenant.seed(db, days=args.days)
        took = time.perf_counter() - start

        if not made:
            print("  Nothing was written. See the warning above.")
            return 1
        for what, n in sorted(made.items(), key=lambda p: -p[1]):
            print(f"    {n:6,}  {what}")
        print(f"\n  Done in {took:.0f}s. A demo visitor now sees a working "
              f"pharmacy.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
