from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings
from . import tenancy

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")


def _normalise(url: str) -> str:
    """Point a bare postgres URL at the driver that is actually installed.

    Hosting platforms hand out `postgresql://...` (and Heroku-style `postgres://`).
    SQLAlchemy maps both to psycopg2, which this project does not install — it
    uses psycopg 3. The build then succeeds and the process dies on first import
    with ModuleNotFoundError, which looks like a deployment fault rather than a
    one-word URL problem. Naming the driver explicitly avoids that entirely.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


#: Keepalives, so a connection that dies mid-query fails instead of hanging.
#:
#: `pool_pre_ping` checks a connection when it is handed out, which catches the
#: pooler having closed it between requests. It does nothing for a socket that
#: dies while a query is in flight: the read simply blocks, for ever, with no
#: exception for anything to retry. A seeding run against a hosted database sat
#: like that for twenty-five minutes at nought per cent CPU, looking from the
#: outside exactly like slow progress.
#:
#: These make the kernel probe an idle socket and give up after about a minute,
#: which turns a silent hang into an ordinary error the retry loop can act on.
_PG_CONNECT_ARGS = {
    "connect_timeout": 15,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}

engine = create_engine(
    _normalise(settings.DATABASE_URL),
    connect_args=({"check_same_thread": False, "timeout": 30} if _is_sqlite
                  else _PG_CONNECT_ARGS),
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


# Every ORM read on a session from this factory is filtered by pharmacy. Done
# once, here, so that no query anywhere has to remember — see `tenancy` for why
# the alternative does not work.
tenancy.install(SessionLocal)

# And then narrowed again to the shops the person works in. Installed after
# tenancy and never instead of it: the two answer different questions, and a
# branch filter on its own would happily show one customer another customer's
# branch. See `branch_scope` for why the unset default points the opposite way
# to tenancy's.
#
# Imported here rather than at the top because it reads the models, which
# import this module for `Base`.
from . import branch_scope  # noqa: E402

branch_scope.install(SessionLocal)


def get_db():
    db = SessionLocal()
    # New rows get the pharmacy in force. Registered per session rather than on
    # the class so the handler is bound to this session's identity map.
    tenancy.stamp(db)
    # And the branch, where the person works in exactly one.
    branch_scope.stamp(db)
    try:
        yield db
    finally:
        db.close()
