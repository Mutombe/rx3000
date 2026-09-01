"""The group view: how each branch is doing.

Restricted to the people who run the business rather than the counter. A branch
scorecard is a management document — it ranks shops against each other and shows
where money is going missing, and putting it in front of every till user is how
a cashier finds out their drawer is the worst in the group from a screen rather
than from their manager.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_role
from ..database import get_db
from ..models import User
from ..services import branch_scorecard

router = APIRouter(prefix="/api/scorecard", tags=["scorecard"])


@router.get("")
def branches(days: int = Query(30, ge=1, le=365),
             db: Session = Depends(get_db),
             _: User = Depends(require_role("admin", "manager", "pharmacist"))):
    """Every branch of this pharmacy, measured over the last `days`."""
    return branch_scorecard.scorecard(db, days=days)
