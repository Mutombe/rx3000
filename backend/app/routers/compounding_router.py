from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Mixture, MixtureIngredient, Product, User
from ..services import compounding

router = APIRouter(prefix="/api/compounding", tags=["compounding"],
                   dependencies=[Depends(get_current_user)])


@router.get("/mixtures", response_model=list[schemas.MixtureOut])
def list_mixtures(q: str = "", db: Session = Depends(get_db)):
    # Each mixture's ingredients, and each ingredient's product, were read per row
    # while serialising — six queries for two formulae, and it grows with the
    # formula book. Two queries now, whatever the size.
    query = (db.query(Mixture)
             .options(selectinload(Mixture.ingredients)
                      .joinedload(MixtureIngredient.product))
             .filter(Mixture.active))
    if q:
        query = query.filter(Mixture.name.ilike(f"%{q}%"))
    return query.order_by(Mixture.name).all()


@router.post("/mixtures", response_model=schemas.MixtureOut)
def create_mixture(body: schemas.MixtureCreate, db: Session = Depends(get_db)):
    if db.query(Mixture).filter(Mixture.code == body.code.upper()).first():
        raise HTTPException(status_code=400, detail=f"Mixture {body.code} already exists")
    if not body.ingredients:
        raise HTTPException(status_code=400, detail="A preparation needs at least one ingredient")
    for ing in body.ingredients:
        if not db.get(Product, ing.product_id):
            raise HTTPException(status_code=404, detail=f"Product {ing.product_id} not found")
        if ing.quantity <= 0:
            raise HTTPException(status_code=400, detail="Ingredient quantities must be positive")

    mixture = Mixture(**{**body.model_dump(exclude={"ingredients"}), "code": body.code.upper()})
    db.add(mixture)
    db.flush()
    for ing in body.ingredients:
        db.add(MixtureIngredient(mixture_id=mixture.id, **ing.model_dump()))
    db.commit()
    db.refresh(mixture)
    return mixture


@router.get("/mixtures/{mixture_id}", response_model=schemas.MixtureOut)
def get_mixture(mixture_id: int, db: Session = Depends(get_db)):
    mixture = db.get(Mixture, mixture_id)
    if not mixture:
        raise HTTPException(status_code=404, detail="Mixture not found")
    return mixture


@router.get("/mixtures/{mixture_id}/cost")
def cost_mixture(mixture_id: int, batches: float = 1.0, db: Session = Depends(get_db)):
    """What it costs to make up, and whether stock allows it."""
    mixture = db.get(Mixture, mixture_id)
    if not mixture:
        raise HTTPException(status_code=404, detail="Mixture not found")
    if batches <= 0:
        raise HTTPException(status_code=400, detail="Batches must be positive")
    try:
        return compounding.cost(db, mixture, batches)
    except compounding.CompoundingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/mixtures/{mixture_id}/prepare")
def prepare_mixture(mixture_id: int, batches: float = 1.0, reference: str = "",
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Make it up — draws the ingredients from stock through the usual FEFO path."""
    mixture = db.get(Mixture, mixture_id)
    if not mixture:
        raise HTTPException(status_code=404, detail="Mixture not found")
    if batches <= 0:
        raise HTTPException(status_code=400, detail="Batches must be positive")
    try:
        return compounding.prepare(db, mixture, user.id, batches, reference)
    except compounding.CompoundingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
