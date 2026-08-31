"""Basket value on a repeat, and what sells in which month.

Two questions a pharmacy owner asks and nothing here answered: what a repeat
patient is really worth once the rest of their basket is counted, and what to
have on the shelf before the season it sells in. Both per branch and
consolidated, because they are used for different decisions.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..services import basket, seasonality

router = APIRouter(prefix="/api/insight", tags=["insight"],
                   dependencies=[Depends(get_current_user)])


@router.get("/basket")
def repeat_basket(days: int = 90, branch_id: int | None = None,
                  db: Session = Depends(get_db)):
    """What a repeat collection is worth once the whole visit is counted.

    Refuses to answer where the visits found are worth less than the repeats
    they are supposed to contain — which means the dispensings and the sales
    were never tied together, and any multiple computed from them would be a
    number somebody acts on and should not.
    """
    return basket.repeat_baskets(db, days=days, branch_id=branch_id)


@router.get("/seasons")
def seasons(branch_id: int | None = None, limit: int = 40,
            db: Session = Depends(get_db)):
    """Which lines move with the calendar, and when.

    Every row carries how many separate years it was seen in. A month observed
    once is an observation, not a season — with a single year a growing shop
    looks seasonal in every later month, because trend and season are the same
    shape when you only see them once.
    """
    return seasonality.products(db, branch_id=branch_id, limit=limit)


@router.get("/seasons/group")
def seasons_group(limit: int = 15, db: Session = Depends(get_db)):
    """Every branch's year beside the group's.

    The rows worth reading are the ones that disagree: a branch whose busiest
    month is not the group's is one the group buying pattern is actively wrong
    for.
    """
    return seasonality.group(db, limit=limit)
