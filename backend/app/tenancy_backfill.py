"""Give every existing row a pharmacy to belong to.

Adding the column is the easy half. The dangerous half is the moment between
the column existing and the rows being filled: the scoping in `tenancy` narrows
a query with no pharmacy in force to nothing, so a deployment that adds
`pharmacy_id` and stops there does not break loudly — it comes up with every
screen empty and every patient apparently gone. That is a worse morning than a
failed migration.

So this runs in the same startup as the schema change, before the API serves a
request, and it is written to be safe to run again: the second run finds nothing
to fill and does nothing. An installation that already has data gets one
pharmacy created from what the branch record already says about itself, and
every row in every scoped table is stamped with it.

A fresh installation gets the same treatment for nothing, which is correct — a
single-shop pharmacy has one tenant and should never have to think about the
word.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from . import tenancy

log = logging.getLogger("rx5000.tenancy")


def _scoped_tables() -> list[str]:
    """Every table carrying the tenant column, asked of the models themselves.

    Read from the mapper rather than listed here, so a table added later is
    backfilled without anybody remembering to add it to a list — the same
    reasoning as the automatic filter it supports.
    """
    from .database import Base

    out = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if issubclass(cls, tenancy.TenantMixin):
            out.append(cls.__tablename__)
    return sorted(set(out))


def run(engine: Engine) -> tuple[int, int | None]:
    """Create the founding pharmacy if there is none, and stamp every row.

    Returns how many rows were stamped and which pharmacy is the founding one,
    because startup has to go on to run *as* that pharmacy — seeding, the
    default branch, the chart of accounts. Work done at boot with no pharmacy in
    force writes rows belonging to nobody, which are then invisible to everyone.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "pharmacies" not in tables:
        return 0, None

    filled = 0
    with engine.begin() as conn:
        pharmacy_id = conn.execute(
            text("SELECT id FROM pharmacies ORDER BY id LIMIT 1")).scalar()

        if pharmacy_id is None:
            # Named from the branch that already exists, because that record
            # already carries what this pharmacy calls itself. Inventing
            # "Default Pharmacy" would put a placeholder on the one row a group
            # of shops is identified by.
            name = reg = phone = addr = city = None
            if "branches" in tables:
                row = conn.execute(text(
                    "SELECT name, registration_no, phone, address, city "
                    "FROM branches ORDER BY id LIMIT 1")).first()
                if row:
                    name, reg, phone, addr, city = row
            pharmacy_id = conn.execute(text(
                "INSERT INTO pharmacies (name, trading_name, registration_no, "
                "phone, address, city, active) "
                "VALUES (:n, :t, :r, :p, :a, :c, :active) RETURNING id"
            ), {"n": name or "This pharmacy", "t": name or "",
                "r": reg or "", "p": phone or "", "a": addr or "",
                "c": city or "", "active": True}).scalar()
            log.info("Created the founding pharmacy %s (%s)", pharmacy_id, name)
            filled += 1

        for table in _scoped_tables():
            if table not in tables:
                continue
            columns = {c["name"] for c in inspector.get_columns(table)}
            if "pharmacy_id" not in columns:
                continue
            result = conn.execute(text(
                f"UPDATE {table} SET pharmacy_id = :pid WHERE pharmacy_id IS NULL"
            ), {"pid": pharmacy_id})
            if result.rowcount and result.rowcount > 0:
                log.info("Stamped %s row(s) in %s", result.rowcount, table)
                filled += result.rowcount

    # Somebody has to be able to reach the pharmacies screen, and on an
    # existing deployment nobody carries the flag yet. The founding
    # administrator gets it — they are already whoever set this system up.
    # Only when no platform administrator exists at all, so this never
    # re-promotes an account that was deliberately demoted.
    with engine.begin() as conn:
        has_owner = conn.execute(text(
            "SELECT COUNT(*) FROM users WHERE is_platform_admin = 1")).scalar()
        if not has_owner:
            promoted = conn.execute(text(
                "UPDATE users SET is_platform_admin = 1 WHERE id = ("
                "  SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1)"
            )).rowcount
            if promoted:
                log.info("Promoted the founding administrator to platform admin")

    return filled, pharmacy_id
