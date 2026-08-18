"""Lightweight SQLite schema migration.

`Base.metadata.create_all` creates new tables but never alters existing ones.
This adds any missing columns on tables that predate a feature, so upgrading
an existing rx3000.db never requires deleting it.
"""
import logging

import re
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("rx3000.migrate")

# table -> column -> DDL type (must be nullable / have a default for ALTER TABLE)
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "accounts": {"section": "VARCHAR(24)", "is_cash": "BOOLEAN DEFAULT 0"},
    "shifts": {
        "till_no": "VARCHAR(10)", "run_number": "INTEGER DEFAULT 0",
        "draw_no": "VARCHAR(10)", "branch_id": "INTEGER",
        "cashup_json": "TEXT", "counted_by_id": "INTEGER",
        "counted_at": "TIMESTAMP",
    },
    # Branches. Nullable on purpose: every row written before branches existed
    # is backfilled to the default branch by the seed rather than guessed at
    # here, and a column that arrives NOT NULL on a populated table cannot be
    # added at all on SQLite.
    "stock_batches": {"branch_id": "INTEGER"},
    "stock_movements": {"branch_id": "INTEGER"},
    "doctors": {
        # Prescriber portal sign-in. Null and false on every existing row, so an
        # upgrade never silently grants a prescriber the ability to write in.
        "portal_password_hash": "VARCHAR(255)",
        "portal_active": "BOOLEAN DEFAULT 0",
    },
    "sales": {
        # Which branch sold it. Drives branch takings and the branch VAT return.
        "branch_id": "INTEGER",
        # The till's own reference, so a sale replayed from the offline queue is
        # recognised rather than posted twice.
        "client_ref": "VARCHAR(64)",
        "taken_offline_at": "TIMESTAMP",
        "transferred_at": "TIMESTAMP",
        "transferred_by_id": "INTEGER",
        "shift_id": "INTEGER",
        "card_auth_code": "VARCHAR(20) DEFAULT ''",
        "card_reference": "VARCHAR(40) DEFAULT ''",
        "card_last4": "VARCHAR(4) DEFAULT ''",
        "card_scheme": "VARCHAR(20) DEFAULT ''",
        "terminal_id": "VARCHAR(30) DEFAULT ''",
        "card_batch": "VARCHAR(30) DEFAULT ''",
        "currency_code": "VARCHAR(5) DEFAULT ''",
    },
    "patients": {
        "marketing_opt_in": "BOOLEAN DEFAULT 1",
        "caregiver_name": "VARCHAR(120)",
        "caregiver_phone": "VARCHAR(30)",
        "caregiver_relationship": "VARCHAR(40)",
        "contact_caregiver_first": "BOOLEAN DEFAULT 0",
    },
    "prescriptions": {
        "status": "VARCHAR(12) DEFAULT 'active'",
        "draft_ref": "VARCHAR(30) DEFAULT ''",
        "started_by_id": "INTEGER",
        "updated_at": "DATETIME",
        "finalised_at": "DATETIME",
    },
    "sale_items": {
        "unit_cost": "FLOAT DEFAULT 0",
        "prescription_item_id": "INTEGER",
    },
    "funders": {"biometric_required": "BOOLEAN DEFAULT 0"},
    "prescription_items": {
        "icd10_code": "VARCHAR(12) DEFAULT ''",
        "supply_days": "INTEGER DEFAULT 30",
        "no_claim": "BOOLEAN DEFAULT 0",
        "not_dispensed": "BOOLEAN DEFAULT 0",
    },
    "remittance_lines": {"resolution_note": "VARCHAR(300) DEFAULT ''"},
    "medical_aids": {
        "credit_limit": "FLOAT DEFAULT 0",
        "pay_office_id": "INTEGER",
        "fee_model_id": "INTEGER",
        "currency_code": "VARCHAR(5) DEFAULT ''",
        "biometric_required": "BOOLEAN DEFAULT 0",
        "realtime": "BOOLEAN DEFAULT 0",
        "levy_fixed": "FLOAT DEFAULT 0",
        "levy_percent": "FLOAT DEFAULT 0",
        "discount_percent": "FLOAT DEFAULT 0",
        "extra_markup_percent": "FLOAT DEFAULT 0",
        "formulary_id": "INTEGER",
        "active": "BOOLEAN DEFAULT 1",
    },
    "claims": {
        "deferred_reason": "VARCHAR(200) DEFAULT ''",
        "deferred_at": "DATETIME",
        "submitted_at": "DATETIME",
        "submit_attempts": "INTEGER DEFAULT 0",
        "gross": "FLOAT DEFAULT 0",
        "discount": "FLOAT DEFAULT 0",
        "levy": "FLOAT DEFAULT 0",
        "dispensing_fee": "FLOAT DEFAULT 0",
        "icd10_code": "VARCHAR(12) DEFAULT ''",
        "authorisation": "VARCHAR(40) DEFAULT ''",
        "batch_id": "INTEGER",
        "settled_amount": "FLOAT DEFAULT 0",
        "settled_at": "DATETIME",
    },
    "products": {
        # DEFAULT '' matters on both of these. Without it every existing row is
        # NULL, and the API declares them as plain strings — which took
        # GET /api/products down with a 500 for all 545 products.
        "bin_location": "VARCHAR(20) DEFAULT ''",
        "manufacturer": "VARCHAR(120) DEFAULT ''",
        "sep_price": "DOUBLE PRECISION DEFAULT 0","mmap_price": "FLOAT DEFAULT 0",
                 "active_ingredient": "VARCHAR(160) DEFAULT ''"},
    "messages": {"campaign_id": "INTEGER"},
    "deals": {"campaign_id": "INTEGER"},
    "dispensings": {
        "pharmacist_initial": "VARCHAR(8)",
        "dispense_type": "VARCHAR(20) DEFAULT 'prescription'",
        "schedule": "INTEGER DEFAULT 0",
        "id_verified": "BOOLEAN DEFAULT 0",
        "id_number_seen": "VARCHAR(30) DEFAULT ''",
        "script_sighted": "BOOLEAN DEFAULT 0",
        "prescriber_verified": "BOOLEAN DEFAULT 0",
        "witness_id": "INTEGER",
        "compliance_notes": "TEXT DEFAULT ''",
    },
}


# SQLite cannot relax a NOT NULL constraint with ALTER TABLE — the only way is
# to rebuild the table. This is the documented dance: build the new shape, copy
# the rows, swap. Listed explicitly rather than done generically, because a
# table rebuild is destructive if it is wrong and should never happen by
# accident.
RELAXED_NULLABLE = {
    # An unfinished script has no Rx number yet (it must not burn one from a
    # numbered register) and often no prescriber (that is usually the thing
    # still being chased when the pharmacist is interrupted).
    "prescriptions": ("rx_number", "doctor_id"),
}


def _portable(ddl: str, dialect: str) -> str:
    """Translate a column definition into something the target database accepts.

    The definitions in ADDED_COLUMNS are written the way SQLite thinks, because
    that is what development runs on. SQLite has no boolean type and no opinion
    about `DATETIME`, so it accepts `BOOLEAN DEFAULT 0` and `DATETIME` happily.
    Postgres accepts neither: a boolean column cannot take an integer default,
    and `DATETIME` is not a type it has.

    Every such definition in this file was a live landmine, and only one of them
    went off. The rest survived because their columns were created by
    `create_all` on a fresh Postgres database, so the ALTER that would have
    failed never ran. `is_cash` was genuinely new, the ALTER ran, and production
    would not start.

    Translating here rather than rewriting the table means the entries stay
    readable in the dialect they were written in, and any future one is fixed
    before it reaches a database that cares.
    """
    if not dialect.startswith("postgres"):
        return ddl

    out = ddl
    # A boolean default of 0/1 is an integer to Postgres.
    out = re.sub(r"\bBOOLEAN\s+DEFAULT\s+0\b", "BOOLEAN DEFAULT FALSE", out, flags=re.I)
    out = re.sub(r"\bBOOLEAN\s+DEFAULT\s+1\b", "BOOLEAN DEFAULT TRUE", out, flags=re.I)
    # Postgres has no DATETIME.
    out = re.sub(r"\bDATETIME\b", "TIMESTAMP", out, flags=re.I)
    return out


def _assert_portable_defaults() -> None:
    """Refuse to start if a definition cannot be translated for Postgres.

    Cheap, and it turns the next occurrence of this class of bug into a failure
    on a developer's machine rather than a production deploy that will not boot.
    """
    # Each entry is a pattern that survives translation and that Postgres will
    # reject at ALTER time — which on Render means a deploy that never boots.
    unsafe = (
        (r"\bBOOLEAN\s+DEFAULT\s+\d",                 "boolean column with an integer default"),
        (r"\bDATETIME\b",                             "DATETIME is not a Postgres type"),
        # A quoted default on a numeric column is the same mistake in the other
        # direction, and was not previously checked for.
        (r"\b(?:INTEGER|FLOAT|DOUBLE PRECISION|NUMERIC)\b[^,]*DEFAULT\s+''",
                                                      "number column with a text default"),
        (r"\bAUTOINCREMENT\b",                        "AUTOINCREMENT is SQLite-only"),
    )
    bad = []
    for table, columns in ADDED_COLUMNS.items():
        for column, ddl in columns.items():
            translated = _portable(ddl, "postgresql")
            for pattern, why in unsafe:
                if re.search(pattern, translated, re.I):
                    bad.append(f"{table}.{column} = {ddl!r} ({why})")
    if bad:
        raise RuntimeError(
            "These column definitions are not valid on Postgres even after "
            "translation: " + "; ".join(bad)
        )


_assert_portable_defaults()


def _assert_no_shadowed_tables() -> None:
    """Fail loudly if a table is listed twice in ADDED_COLUMNS.

    A duplicate key in a dict literal is not an error in Python: the later one
    silently wins and the earlier one's columns are never created. That has
    already happened here once — `sales` was listed twice and `branch_id` was
    never added, which surfaced much later as a column present in the model and
    absent from the database.

    The literal is read back from the source file because by the time the dict
    object exists the evidence is gone: the duplicate has already collapsed.
    """
    import pathlib as _pathlib
    import re as _re

    text = _pathlib.Path(__file__).read_text(encoding="utf-8")
    body = text.split("ADDED_COLUMNS", 1)[-1]
    # Stop at the closing brace of this literal, so other dicts below are not
    # counted. Nesting here is only one level deep, so counting braces is enough.
    depth, cut = 0, len(body)
    for index, char in enumerate(body):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                cut = index
                break
    listed = _re.findall(r'^    "(\w+)":', body[:cut], _re.M)
    dupes = sorted({t for t in listed if listed.count(t) > 1})
    if dupes:
        raise RuntimeError(
            "ADDED_COLUMNS lists these tables more than once, so the earlier "
            "entries are silently ignored: " + ", ".join(dupes) + ". Merge them."
        )


_assert_no_shadowed_tables()


def _relax_not_null(conn, inspector, table: str, columns: tuple) -> int:
    cols = inspector.get_columns(table)
    if not any(c["name"] in columns and not c["nullable"] for c in cols):
        return 0

    names = [c["name"] for c in cols]
    defs = []
    for c in cols:
        ddl = f'"{c["name"]}" {c["type"]}'
        if c.get("primary_key"):
            ddl += " PRIMARY KEY"
        elif not c["nullable"] and c["name"] not in columns:
            ddl += " NOT NULL"
        defs.append(ddl)

    joined = ", ".join(f'"{n}"' for n in names)
    # Without `legacy_alter_table`, SQLite rewrites every foreign key in every
    # OTHER table to follow the rename — so the children end up pointing at
    # `<table>__old`, and dropping it orphans them. It is the documented
    # behaviour and the reason a naive rebuild quietly destroys referential
    # integrity. Foreign keys are also disabled for the duration, because the
    # intermediate state is legitimately inconsistent.
    conn.execute(text("PRAGMA legacy_alter_table=ON"))
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(text(f"ALTER TABLE {table} RENAME TO {table}__old"))
    conn.execute(text(f"CREATE TABLE {table} ({', '.join(defs)})"))
    conn.execute(text(f"INSERT INTO {table} ({joined}) SELECT {joined} FROM {table}__old"))
    copied = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    original = conn.execute(text(f"SELECT COUNT(*) FROM {table}__old")).scalar()
    if copied != original:
        # Leave the old table in place rather than drop it. A rebuild that lost
        # rows must be recoverable, and the half-done state is the evidence.
        raise RuntimeError(
            f"Rebuild of {table} copied {copied} of {original} rows. "
            f"{table}__old has been kept — do not drop it.")
    conn.execute(text(f"DROP TABLE {table}__old"))
    conn.execute(text("PRAGMA foreign_keys=ON"))
    conn.execute(text("PRAGMA legacy_alter_table=OFF"))
    log.info("Relaxed NOT NULL on %s.%s (%d rows preserved)",
             table, ", ".join(columns), copied)
    return 1


def _name_the_nameless(conn) -> int:
    """Give a name to any product that has none.

    `ProductBase.name` gained a `min_length=1` constraint after a blank name had
    already been allowed through, and `ProductOut` inherits it. That combination
    is worse than either half: writes are correctly rejected, but every existing
    blank row now fails *response* validation, so one bad record from months ago
    turns the whole product list into a 500 — which reaches the browser as a
    wordless failure on a screen that has nothing to do with that product.

    Naming them makes them readable again and, more to the point, makes them
    visible: an operator can find "Unnamed product #544" in the catalogue and
    correct or retire it, which is impossible while it is an empty string.
    """
    rows = conn.execute(text(
        "SELECT id FROM products WHERE name IS NULL OR TRIM(name) = ''"
    )).fetchall()
    for (pid,) in rows:
        conn.execute(
            text("UPDATE products SET name = :name WHERE id = :id"),
            {"name": f"Unnamed product #{pid}", "id": pid},
        )
        log.info("Named product %s, which had no name", pid)
    return len(rows)


def _mark_cash_accounts(conn) -> int:
    """Flag the obvious cash accounts on a chart that predates the column.

    Only run where nothing is flagged yet, so a pharmacy that has classified its
    own accounts is never overwritten by a guess. The guess itself is narrow on
    purpose: an account is cash if it is named like cash, not if it merely sits
    near cash in the numbering.
    """
    already = conn.execute(text(
        "SELECT COUNT(*) FROM accounts WHERE is_cash = 1"
    )).scalar()
    if already:
        return 0
    result = conn.execute(text(
        "UPDATE accounts SET is_cash = 1 "
        "WHERE type = 'asset' AND ("
        "  LOWER(name) LIKE '%cash%' OR LOWER(name) LIKE '%bank%'"
        "  OR LOWER(name) LIKE '%petty%' OR LOWER(name) LIKE '%till%')"
    ))
    count = result.rowcount or 0
    if count:
        log.info("Marked %d account(s) as cash for the cash flow statement", count)
    return count


# Columns that are filtered or ordered by, and were not indexed. Every one of
# these is cheap on a demo database and decisive on a real one: a pharmacy's
# claims table grows faster than anything else here, and every claims report
# filters it by status and date.
#
# Composite where the query uses the columns together — the outstanding-shortfall
# query asks for all three at once, and three separate indexes make the database
# choose one and scan for the rest.
WANTED_INDEXES: list[tuple[str, str, tuple[str, ...]]] = [
    ("claims", "ix_claims_status", ("status",)),
    ("claims", "ix_claims_medical_aid_id", ("medical_aid_id",)),
    ("claims", "ix_claims_created_at", ("created_at",)),
    ("claims", "ix_claims_batch_id", ("batch_id",)),
    ("sales", "ix_sales_status", ("status",)),
    ("sales", "ix_sales_shift_id", ("shift_id",)),
    ("branch_transfers", "ix_branch_transfers_status", ("status",)),
    ("branch_transfers", "ix_branch_transfers_despatched_at", ("despatched_at",)),
    ("remittance_lines", "ix_remittance_lines_open",
     ("status", "written_off", "patient_billed")),
    ("authorisations", "ix_authorisations_patient_id", ("patient_id",)),
]


def _create_indexes(conn, inspector, existing_tables: set) -> int:
    """Add the indexes the queries actually need.

    `create_all` builds indexes for tables it creates and leaves existing tables
    alone, so an index added to a model after the first run never appears on a
    database that predates it. IF NOT EXISTS makes this idempotent on both SQLite
    and Postgres.
    """
    made = 0
    for table, name, columns in WANTED_INDEXES:
        if table not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        if not set(columns) <= present:
            continue
        existing = {i["name"] for i in inspector.get_indexes(table)}
        if name in existing:
            continue
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({', '.join(columns)})"))
        log.info("Created index %s on %s(%s)", name, table, ", ".join(columns))
        made += 1
    return made


def _unmix_remittance_notes(conn, existing_tables: set) -> int:
    """Take our working notes back out of the funder's stated reason.

    `resolve_line` used to append its note to `line.reason`, so every resolution
    rewrote what the scheme had said, and a line resolved repeatedly ended up
    reading "Reduced by the member's co-payment or levy. | uneconomic |
    uneconomic | uneconomic | uneconomic". The funder's reason is evidence in a
    dispute; ours is a working note. They now have separate columns, and this
    repairs the rows written before that.

    The split is safe because the funder's reason never contains a pipe: it comes
    from a fixed vocabulary. Everything before the first pipe is theirs,
    everything after is ours, de-duplicated because the same note was appended
    over and over.
    """
    if "remittance_lines" not in existing_tables:
        return 0
    rows = conn.execute(text(
        "SELECT id, reason FROM remittance_lines WHERE reason LIKE '%|%'"
    )).fetchall()
    for line_id, reason in rows:
        parts = [p.strip() for p in (reason or "").split("|")]
        funder_reason = parts[0]
        # dict.fromkeys keeps the order and drops the repeats.
        notes = list(dict.fromkeys(p for p in parts[1:] if p))
        conn.execute(
            text("UPDATE remittance_lines SET reason = :r, resolution_note = :n "
                 "WHERE id = :i"),
            {"r": funder_reason[:200], "n": " | ".join(notes)[:300], "i": line_id},
        )
    if rows:
        log.info("Unmixed notes from the funder's reason on %s remittance lines", len(rows))
    return len(rows)


def _fill_null_text(conn, inspector, existing_tables: set) -> int:
    """Turn NULLs in added text columns into empty strings.

    Adding a column leaves every existing row NULL, and the API declares these
    fields as plain strings — so one unfilled column answers 500 for every row
    in the table. Correcting the DDL fixes the next install and does nothing for
    the ones already running, which is where the outage actually is.

    Scoped to columns this file added and only where a DEFAULT '' is declared, so
    it can only ever write the value the column would have had anyway. Runs every
    startup: it is idempotent, and the same NULLs exist on any deployment that
    took the column before the default was there.
    """
    filled = 0
    for table, columns in ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        for column, ddl_type in columns.items():
            if column not in present:
                continue
            if "CHAR" not in ddl_type.upper() and "TEXT" not in ddl_type.upper():
                continue
            if "DEFAULT ''" not in ddl_type:
                continue
            done = conn.execute(text(
                f"UPDATE {table} SET {column} = '' WHERE {column} IS NULL"
            )).rowcount
            if done:
                log.info("Filled %s NULL %s.%s", done, table, column)
                filled += 1
    return filled


def run_migrations(engine: Engine) -> int:
    inspector = inspect(engine)
    applied = 0
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in RELAXED_NULLABLE.items():
            if table in existing_tables:
                applied += _relax_not_null(conn, inspector, table, columns)

        for table, columns in ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all will build it with every column
            present = {c["name"] for c in inspector.get_columns(table)}
            for column, ddl_type in columns.items():
                if column in present:
                    continue
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {column} "
                    f"{_portable(ddl_type, conn.dialect.name)}"
                ))
                log.info("Added column %s.%s", table, column)
                applied += 1

        applied += _fill_null_text(conn, inspector, existing_tables)
        applied += _unmix_remittance_notes(conn, existing_tables)
        applied += _create_indexes(conn, inspector, existing_tables)

        if "products" in existing_tables:
            applied += _name_the_nameless(conn)
        if "accounts" in existing_tables:
            applied += _mark_cash_accounts(conn)
    return applied
