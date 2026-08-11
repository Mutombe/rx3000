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


@router.get("/licence")
def licence():
    return station.licence()


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


@router.post("/interactions/check")
def check_interactions(product_ids: list[int] = Body(..., embed=True),
                       db: Session = Depends(get_db)):
    """Check a basket against the interaction pairs held locally.

    The response always carries its coverage. A clear result means none of the
    pairs this system holds were found — not that the combination is safe — and
    the wording says so, because a pharmacist who is told twice that the system
    checks interactions will trust it the third time.
    """
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    missing = set(product_ids) - {p.id for p in products}
    if missing:
        raise HTTPException(status_code=404,
                            detail=f"Unknown product(s): {sorted(missing)}")
    return interactions.check([
        {"product_id": p.id, "name": p.name,
         "active_ingredient": p.active_ingredient or ""}
        for p in products
    ])


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
