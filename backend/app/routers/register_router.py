from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import paging
from ..models import Patient, RegisterEntry

router = APIRouter(prefix="/api/register", tags=["schedule-register"], dependencies=[Depends(get_current_user)])


def _entries(db: Session):
    """The register, with the three names each line is read by.

    Every row names a medicine, a patient and a prescriber, and each was being
    fetched one at a time as the response was built: three hundred rows became
    nine hundred separate queries. On a database in the same building that is
    slow; on a hosted one it is fatal, because each of those queries costs a
    round trip. Opening the register took seventy-four seconds against the live
    database, for a query that runs in under a millisecond.

    Loaded up front instead, which is three queries for the whole page however
    many rows it holds. `selectinload` rather than a join: these are many-to-one
    and a join would repeat the whole medicine row against every entry that
    names it.
    """
    return (db.query(RegisterEntry)
            .options(selectinload(RegisterEntry.product),
                     # The patient's scheme comes with the patient. It is on
                     # PatientOut, so leaving it behind only moved the problem
                     # one level down: the register still ran a query for every
                     # distinct patient who carries a medical aid.
                     selectinload(RegisterEntry.patient).selectinload(Patient.medical_aid),
                     selectinload(RegisterEntry.doctor)))


@router.get("", response_model=list[schemas.RegisterEntryOut])
def list_entries(
    product_id: int | None = None,
    schedule: int | None = None,
    date_from: str = "",
    date_to: str = "",
    limit: int = 300,
    db: Session = Depends(get_db),
):
    query = _entries(db)
    if product_id:
        query = query.filter(RegisterEntry.product_id == product_id)
    if schedule:
        query = query.filter(RegisterEntry.schedule == schedule)
    if date_from:
        query = query.filter(RegisterEntry.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(RegisterEntry.created_at <= datetime.fromisoformat(date_to + "T23:59:59"))
    return query.order_by(RegisterEntry.created_at.desc()).limit(limit).all()


@router.get("/paged")
def list_entries_paged(
    product_id: int | None = None,
    schedule: int | None = None,
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    per_page: int = paging.DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    """The controlled-drugs register, paged.

    This one matters more than the others. The register is a statutory record an
    inspector may ask to see, and a screen that showed 300 of 612 entries with
    no total was not an incomplete view. It was a misleading one.
    """
    query = _entries(db)
    if product_id:
        query = query.filter(RegisterEntry.product_id == product_id)
    if schedule:
        query = query.filter(RegisterEntry.schedule == schedule)
    if date_from:
        query = query.filter(RegisterEntry.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(RegisterEntry.created_at <= datetime.fromisoformat(date_to + "T23:59:59"))
    result = paging.page(query.order_by(RegisterEntry.created_at.desc()),
                         page=page, per_page=per_page)
    return result.envelope(
        lambda x: schemas.RegisterEntryOut.model_validate(x, from_attributes=True).model_dump()
    )
