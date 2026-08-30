"""Lightweight SQLite schema migration.

`Base.metadata.create_all` creates new tables but never alters existing ones.
This adds any missing columns on tables that predate a feature, so upgrading
an existing database file never requires deleting it.
"""
import logging

import re
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("rx5000.migrate")

# table -> column -> DDL type (must be nullable / have a default for ALTER TABLE)
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "accounts": {"section": "VARCHAR(24)", "is_cash": "BOOLEAN DEFAULT 0"},
    # Till PINs. Nullable throughout: every user that existed before this has no
    # PIN, and the password path has to keep working for them rather than
    # locking them out of a prompt they have always answered with a password.
    "users": {
        "is_platform_admin": "BOOLEAN DEFAULT 0",
        "pin_hash": "VARCHAR(255)",
        "pin_set_at": "TIMESTAMP",
        "pin_failures": "INTEGER DEFAULT 0",
        "pin_locked_until": "TIMESTAMP",
        "is_demo": "BOOLEAN DEFAULT 0",
        "demo_expires_at": "TIMESTAMP",
    },
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
        # The claiming agreement: when a month's claims are due in, and when
        # the funder pays. A pharmacy plans its float around both.
        "claim_cutoff_day": "INTEGER DEFAULT 0",
        "settlement_day": "INTEGER DEFAULT 0",
        "settlement_days": "INTEGER DEFAULT 0",
        "agreement_reference": "VARCHAR(60) DEFAULT ''",
        "agreement_note": "TEXT DEFAULT ''",
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
    "purchase_orders": {"branch_id": "INTEGER"},
    "products": {
        "category_id": "INTEGER",
        # The pharmacy's own code for the line, and what the shelf actually cost
        # on average — both come straight off their stock export.
        "stock_code": "VARCHAR(40) DEFAULT ''",
        "average_cost": "FLOAT DEFAULT 0",
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
        "collected_at": "TIMESTAMP",
        "collected_by_id": "INTEGER",
        "collected_name": "VARCHAR(120) DEFAULT ''",
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
            f"{table}__old has been kept, do not drop it.")
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
    # TRUE, not 1.
    #
    # SQLite has no boolean type and treats them as integers, so `is_cash = 1`
    # works locally and always will. PostgreSQL refuses it outright — "operator
    # does not exist: boolean = integer" — and because this runs inside the
    # startup lifespan, that refusal is not a failed migration but a server that
    # will not boot. It took the production API down while every local check
    # stayed green, which is the shape of every SQLite-versus-Postgres bug: the
    # dialect that accepts more is the one you develop against.
    already = conn.execute(text(
        "SELECT COUNT(*) FROM accounts WHERE is_cash = TRUE"
    )).scalar()
    if already:
        return 0
    result = conn.execute(text(
        "UPDATE accounts SET is_cash = TRUE "
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

    # The clinical tables had no indexes at all — not one, on any of the three.
    # That was survivable while a demo pharmacy held a few thousand rows and
    # stopped being so the moment sixteen months of a real pharmacy's history
    # was loaded: 55,741 dispensings, every one of them scanned by a patient's
    # own record, the repeat book, the churn analysis and the controlled
    # register. Each of these is a column those queries join or filter on.
    ("dispensings", "ix_dispensings_prescription_item_id", ("prescription_item_id",)),
    ("dispensings", "ix_dispensings_dispensed_at", ("dispensed_at",)),
    ("dispensings", "ix_dispensings_sale_id", ("sale_id",)),
    # Will-call reads "dispensed, never collected", which is this column being
    # null across the whole table.
    ("dispensings", "ix_dispensings_collected_at", ("collected_at",)),
    ("prescription_items", "ix_prescription_items_prescription_id", ("prescription_id",)),
    ("prescription_items", "ix_prescription_items_product_id", ("product_id",)),
    # The repeat book is this column, filtered by date, on every screen that
    # asks what is due.
    ("prescription_items", "ix_prescription_items_next_repeat", ("next_repeat_date",)),
    ("prescriptions", "ix_prescriptions_patient_id", ("patient_id",)),
    ("prescriptions", "ix_prescriptions_status", ("status",)),
    ("prescriptions", "ix_prescriptions_date", ("date_prescribed",)),
]


def _untangle_account_codes(conn, inspector, existing_tables: set) -> int:
    """Make an account code unique per pharmacy rather than per database.

    The original index was UNIQUE on accounts(code) alone. On one pharmacy that
    is right; on a shared database it means the first tenant to boot claims
    "1000" and no other tenant can ever seed a chart of accounts. Sixteen of
    seventeen pharmacies here had none, and the only symptom was an empty ledger.

    Dropping a unique index is safe in a way that adding one is not: nothing
    that was legal becomes illegal. The composite that replaces it is created
    only if the data allows — if two rows in one pharmacy really do share a
    code, that is a data problem to be seen rather than a migration to fail the
    boot on, so it is logged and the plain index stands.
    """
    if "accounts" not in existing_tables:
        return 0
    columns = {c["name"] for c in inspector.get_columns("accounts")}
    if "pharmacy_id" not in columns:
        return 0

    indexes = {i["name"]: i for i in inspector.get_indexes("accounts")}
    old = indexes.get("ix_accounts_code")
    if not (old and old.get("unique")):
        return 0

    conn.execute(text("DROP INDEX ix_accounts_code"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_accounts_code ON accounts (code)"))
    log.info("Account codes are no longer unique across every pharmacy")

    clash = conn.execute(text(
        "SELECT COUNT(*) FROM (SELECT pharmacy_id, code FROM accounts "
        "GROUP BY pharmacy_id, code HAVING COUNT(*) > 1) d")).scalar()
    if clash:
        log.warning(
            "%d account code(s) are duplicated within one pharmacy; the "
            "per-pharmacy unique index was not created", clash)
        return 1

    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_tenant_code "
        "ON accounts (pharmacy_id, code)"))
    log.info("Account codes are now unique within each pharmacy")
    return 1


#: Document numbers that belong to one pharmacy, not to the estate.
#:
#: Every one of these is produced by counting that pharmacy's OWN rows —
#: `helpers.next_number` does `count() + 1` under the tenant filter, and the
#: ledger's `next_reference` scans that tenant's highest. So two pharmacies with
#: the same number of sales in the same month both generate `INV260800001`, and
#: because the index was unique across the whole database the second one was
#: refused. Two brand-new pharmacies making their first sale in the same month
#: is not an edge case; it is opening week, and the failure lands at the till
#: in the middle of serving somebody.
#:
#: `users.username` is deliberately absent: signing in names a user without
#: naming a pharmacy, so it has to stay unique everywhere. So are the switch's
#: own transaction id and a step-up token, which are allocated elsewhere.
PER_TENANT_NUMBERS: list[tuple[str, str]] = [
    ("sales", "sale_number"),
    ("prescriptions", "rx_number"),
    ("purchase_orders", "order_number"),
    ("claims", "claim_number"),
    ("claim_batches", "batch_number"),
    ("waybills", "waybill_number"),
    ("laybys", "layby_number"),
    ("quotes", "quote_number"),
    ("tickets", "ticket_number"),
    ("stock_takes", "reference"),
    ("remittances", "remittance_number"),
    ("authorisations", "reference"),
    ("branch_transfers", "reference"),
    ("sample_receipts", "reference"),
    ("owed_items", "reference"),
    ("branches", "code"),
    ("trading_periods", "code"),
    ("journal_entries", "reference"),
    ("mixtures", "code"),
]


def _per_tenant_numbers(conn, inspector, existing_tables: set) -> int:
    """Move each document number's uniqueness from the estate to the pharmacy.

    Dropping a unique index is safe in the way that adding one is not: nothing
    that was legal becomes illegal. The composite that replaces it is created
    only where the data allows — if one pharmacy really does hold the same
    number twice, that is a data problem to be seen rather than a migration to
    fail the boot on, so it is logged and the plain index stands.
    """
    moved = 0
    for table, column in PER_TENANT_NUMBERS:
        if table not in existing_tables:
            continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in columns or "pharmacy_id" not in columns:
            continue

        indexes = {i["name"]: i for i in inspector.get_indexes(table)}
        composite = f"uq_{table}_tenant_{column}"
        if composite in indexes:
            continue                                  # already moved

        # A UNIQUE constraint and a unique index are the same thing to read and
        # different things to drop, and which one you have depends on whether
        # the model said `index=True` beside `unique=True`.
        #
        # Postgres reports a constraint's backing index in get_indexes() as
        # well, and then refuses to drop it: "cannot drop index … because
        # constraint … requires it". So the constraint is looked for FIRST and
        # dropped by name; only a plain index is dropped as an index.
        constraint = None
        try:
            constraint = next(
                (u["name"] for u in inspector.get_unique_constraints(table)
                 if u["column_names"] == [column] and u.get("name")), None)
        except NotImplementedError:                   # pragma: no cover
            constraint = None

        dropped = False
        if constraint and conn.dialect.name.startswith("postgres"):
            conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{constraint}"'))
            dropped = True
        elif constraint:
            # SQLite cannot drop a table constraint without rebuilding the
            # table. It is left alone on purpose: a SQLite file here is a
            # developer's or a desktop install serving one pharmacy, and a
            # number unique across a database holding one pharmacy is unique
            # within that pharmacy. Rebuilding a live table at startup to fix
            # something that cannot happen there is the riskier choice.
            log.info("%s.%s stays estate-wide on SQLite; it is a table "
                     "constraint, and one file holds one pharmacy", table, column)
            continue
        else:
            plain = next((n for n, i in indexes.items()
                          if i.get("unique") and i.get("column_names") == [column]),
                         None)
            if plain:
                conn.execute(text(f"DROP INDEX {plain}"))
                dropped = True

        if not dropped:
            continue
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})"))

        clash = conn.execute(text(
            f"SELECT COUNT(*) FROM (SELECT pharmacy_id, {column} FROM {table} "
            f"WHERE {column} IS NOT NULL "
            f"GROUP BY pharmacy_id, {column} HAVING COUNT(*) > 1) d")).scalar()
        if clash:
            log.warning("%s.%s is duplicated %d time(s) within one pharmacy; "
                        "left indexed but not unique", table, column, clash)
            moved += 1
            continue

        conn.execute(text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {composite} "
            f"ON {table} (pharmacy_id, {column})"))
        log.info("%s.%s is now unique within each pharmacy", table, column)
        moved += 1
    return moved


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


def _add_tenant_columns(conn, inspector, existing_tables) -> int:
    """Add `pharmacy_id` to every table the models say is tenant-scoped.

    Read from the mappers rather than listed in ADDED_COLUMNS, for the same
    reason the filter itself is automatic: seventy-three hand-written entries is
    seventy-three chances to omit one, and the omission does not fail — it
    produces a table whose rows belong to nobody and are therefore invisible to
    everybody.

    Nullable on purpose. The backfill that follows fills them; a NOT NULL added
    ahead of that takes the deployment down instead of the data.
    """
    from .database import Base
    from .tenancy import TenantMixin

    added = 0
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if not issubclass(cls, TenantMixin):
            continue
        table = cls.__tablename__
        if table not in existing_tables:
            continue                      # create_all builds it complete
        present = {c["name"] for c in inspector.get_columns(table)}
        if "pharmacy_id" in present:
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN pharmacy_id INTEGER"))
        log.info("Added column %s.pharmacy_id", table)
        added += 1
    return added


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

        applied += _add_tenant_columns(conn, inspector, existing_tables)
        applied += _fill_null_text(conn, inspector, existing_tables)
        applied += _unmix_remittance_notes(conn, existing_tables)
        applied += _untangle_account_codes(conn, inspector, existing_tables)
        applied += _per_tenant_numbers(conn, inspector, existing_tables)
        applied += _create_indexes(conn, inspector, existing_tables)

    # The tidying passes run in their own transactions, and a failure in one is
    # logged rather than raised.
    #
    # These are advisory: naming a product that has no name, guessing which
    # accounts are cash. None of them is a schema change and nothing downstream
    # is broken if one is skipped. Inside the block above they were fatal, and
    # because migrations run in the startup lifespan, "fatal" means the API does
    # not boot at all — which is what `is_cash = 1` did to production while
    # every local check stayed green, SQLite having no opinion about comparing a
    # boolean to an integer.
    #
    # Schema changes stay in the block above and stay fatal, deliberately: a
    # server running against a table that is missing a column should stop, not
    # answer 500 to one screen in nine.
    for label, needs, fix in [
        ("naming unnamed products", "products", _name_the_nameless),
        ("classifying cash accounts", "accounts", _mark_cash_accounts),
    ]:
        if needs not in existing_tables:
            continue
        try:
            with engine.begin() as conn:
                applied += fix(conn)
        except Exception:  # noqa: BLE001 - advisory, never worth the server
            log.exception("Skipped %s; the server is starting anyway", label)
    return applied
