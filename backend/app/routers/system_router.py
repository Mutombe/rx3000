"""Station identity, licensing, backups, and interaction checking."""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Product, User
from ..services import backup, interactions, station

router = APIRouter(prefix="/api/system", tags=["system"],
                   dependencies=[Depends(get_current_user)])


@router.get("/info")
def info(db: Session = Depends(get_db)):
    """Which till this is. The panel that answers a support call in one screenshot."""
    return station.info(db)


# The licence used to be readable here on its own. /api/system/info embeds it
# and the System page reads that, so this was a second door to one fact —
# and the sort that drifts, because only one of the two gets updated when the
# shape of a licence changes.


@router.get("/backups")
def backups():
    return {"status": backup.status(), "files": backup.listing()}


@router.post("/backups")
def take_backup(note: str = Body(default="", embed=True),
                _user: User = Depends(get_current_user)):
    """Take a verified backup.

    Verified rather than merely taken: an unverified backup is worse than none,
    because somebody is relying on it.
    """
    try:
        return backup.take(note)
    except backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# The interaction check itself lives on /api/dispensing/interaction-screen,
# which the dispensing screen calls on every basket change. A second endpoint
# used to sit here doing the same job without the patient's medication history —
# and history is the whole point, because two lines on one script were written
# together by a prescriber who thought about it, while warfarin from March
# against ibuprofen today is two prescribers and nobody holding both facts.
#
# Nothing called it. Removed rather than left: the obvious-sounding name is
# exactly what a future integration would reach for, and it would silently get
# the weaker answer.


@router.get("/interactions/coverage")
def coverage():
    """What the checker holds, published so nobody has to guess at its limits."""
    return {
        "pairs": len(interactions.KNOWN),
        "is_clinical_database": False,
        "note": interactions.COVERAGE_NOTE.format(n=len(interactions.KNOWN)),
        "known": [{"a": i.a, "b": i.b, "severity": i.severity, "effect": i.effect}
                  for i in interactions.KNOWN],
    }
