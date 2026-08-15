"""Lightweight SQLite schema migration.

`Base.metadata.create_all` creates new tables but never alters existing ones.
This adds any missing columns on tables that predate a feature, so upgrading
an existing rx3000.db never requires deleting it.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("rx3000.migrate")

# table -> column -> DDL type (must be nullable / have a default for ALTER TABLE)
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "accounts": {"section": "VARCHAR(24)", "is_cash": "BOOLEAN DEFAULT 0"},
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
        "shift_id": "INTEGER",
        "card_auth_code": "VARCHAR(20) DEFAULT ''",
        "card_reference": "VARCHAR(40) DEFAULT ''",
        "card_last4": "VARCHAR(4) DEFAULT ''",
        "card_scheme": "VARCHAR(20) DEFAULT ''",
        "terminal_id": "VARCHAR(30) DEFAULT ''",
        "card_batch": "VARCHAR(30) DEFAULT ''",
        "currency_code": "VARCHAR(5) DEFAULT ''",
    },
    "patients": {"marketing_opt_in": "BOOLEAN DEFAULT 1"},
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
    "medical_aids": {
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
    "products": {"mmap_price": "FLOAT DEFAULT 0",
                 "active_ingredient": "VARCHAR(160) DEFAULT ''"},
    "messages": {"campaign_id": "INTEGER"},
    "deals": {"campaign_id": "INTEGER"},
    "dispensings": {
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
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
                log.info("Added column %s.%s", table, column)
                applied += 1

        if "products" in existing_tables:
            applied += _name_the_nameless(conn)
        if "accounts" in existing_tables:
            applied += _mark_cash_accounts(conn)
    return applied
