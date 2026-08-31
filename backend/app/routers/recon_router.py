"""One place to ask what does not tie up.

The individual reconciliations live where they always did — card settlement in
the POS router, bank statement in the ledger, remittances in claims. This adds
the question none of them answered: across all of them, what disagrees, and
what has nobody even looked at.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..services import recon_overview

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"],
                   dependencies=[Depends(get_current_user)])


@router.get("/overview")
def overview(days: int = recon_overview.WINDOW_DAYS,
             db: Session = Depends(get_db)):
    """Every reconciliation, and whether it agrees.

    Note what this deliberately does not do: report nought differences for a
    reconciliation nobody has run. Card and bank both need a file somebody
    uploads, and showing a clean tick for an exercise that never happened is
    worse than showing nothing — it converts "unchecked" into "checked and
    fine", which is the failure mode every control in here exists to avoid.
    """
    return recon_overview.overview(db, days=days)
