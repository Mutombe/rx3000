"""One counter at a time where two at once would corrupt something.

Three terminals dispensing on a busy morning found three ways to break the
books, none of which a single request can show:

  * Twenty scripts for the last ten units, pressed together, sent five out
    while the shelf fell by three. Stock is read into Python, reduced and
    written back, so two requests reading 10 both wrote 9.
  * One script pressed from several terminals went out more than once: each
    request looked, saw no dispensing yet, and dispensed.
  * Document numbers are the highest issued plus one, so two requests read the
    same highest and the second insert broke the unique index — a 500 on an
    ordinary sale.

Each is a read followed by a write that assumes nothing changed in between.
`serialise` makes that true for the rest of the transaction, and `lock_product`
re-reads a medicine's stock under that guarantee.

The lock is released by the commit or rollback that ends the request, never by
hand, so a failure part-way cannot leave it held.

  PostgreSQL  a transaction-scoped advisory lock on a key, so only work on the
              same thing waits: the same script, the same medicine, the same
              pharmacy's run of invoice numbers. Different pharmacies on one
              database never wait for each other.
  SQLite      the database's own write lock, taken at the start of the
              transaction (BEGIN IMMEDIATE). SQLite has one writer at a time
              whatever is done, so this only makes it wait at the start of the
              work instead of failing, or silently losing an update, halfway.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import tenancy


def serialise(db: Session, key: str) -> None:
    """Hold the lock for `key` until this transaction ends."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        raw = db.connection().connection.dbapi_connection
        # Already writing means the write lock is already held; beginning again
        # would be refused ("cannot start a transaction within a transaction").
        if not raw.in_transaction:
            raw.execute("BEGIN IMMEDIATE")
    elif dialect == "postgresql":
        scoped = f"{tenancy.current_pharmacy_id() or 0}:{key}"
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": scoped})


def lock_product(db: Session, product):
    """The medicine's stock, re-read under a lock, ready to be changed.

    The object passed in may have been loaded before anybody else's change was
    committed; its counts are refreshed in place, so every caller holding it
    sees the current figure rather than the one it read earlier.
    """
    if product is None or product.id is None:
        return product
    serialise(db, f"product:{product.id}")
    # This request's own changes go down first, so the re-read includes them.
    db.flush()
    db.refresh(product)
    return product
