from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        """SQLite's defaults are wrong for a shop with more than one till.

        Three of these fix real problems rather than tuning anything:

        * **foreign_keys is OFF by default.** Every ForeignKey in models.py is
          decorative until this is set — SQLite will happily store a sale item
          pointing at a product that does not exist. This is the important one.

        * **The default journal is a rollback journal**, under which a writer
          locks the whole database against readers. Two tills billing at once
          is the normal case in a pharmacy, not an edge case. WAL lets readers
          carry on while a write is in flight.

        * **busy_timeout is 0**, so the second concurrent writer fails
          immediately with "database is locked" rather than waiting its turn.
          That surfaces to a cashier as a random failed sale. Five seconds of
          patience turns almost all of them into a slight pause instead.

        `synchronous=NORMAL` is the recommended pairing with WAL: durable across
        an application crash, and only at risk from a power cut mid-write, which
        is what the receipt hash chain and the fiscal queue exist to survive.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
