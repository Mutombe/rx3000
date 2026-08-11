"""Branch registry, per-branch stock, and transfers between branches."""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import Branch, BranchTransfer, User
from ..services import branches

router = APIRouter(prefix="/api/branches", tags=["branches"],
                   dependencies=[Depends(get_current_user)])


class BranchIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name: str = Field(min_length=1, max_length=120)
    registration_no: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    city: str = ""
    responsible_pharmacist: str = ""


class TransferIn(BaseModel):
    from_branch_id: int
    to_branch_id: int
    product_id: int
    quantity: int = Field(gt=0)
    notes: str = ""


def _out(b: Branch) -> dict:
    return {
        "id": b.id, "code": b.code, "name": b.name,
        "registration_no": b.registration_no or "",
        "phone": b.phone or "", "email": b.email or "",
        "address": b.address or "", "city": b.city or "",
        "responsible_pharmacist": b.responsible_pharmacist or "",
        "is_default": bool(b.is_default), "active": bool(b.active),
    }


@router.get("")
def list_branches(include_closed: bool = False, db: Session = Depends(get_db)):
    query = db.query(Branch)
    if not include_closed:
        query = query.filter(Branch.active.is_(True))
    rows = query.order_by(Branch.name).all()
    if not rows:
        # A single-shop pharmacy should never see an empty list and wonder what
        # it did wrong. One branch exists from the moment anyone asks.
        rows = [branches.default_branch(db)]
    return [_out(b) for b in rows]


@router.post("")
def create_branch(body: BranchIn, db: Session = Depends(get_db),
                  _: User = Depends(require_role("admin"))):
    if db.query(Branch).filter(Branch.code == body.code.strip().upper()).first():
        raise HTTPException(400, f"A branch with code {body.code.upper()} already exists.")
    first = db.query(Branch).count() == 0
    branch = Branch(**{**body.model_dump(), "code": body.code.strip().upper()},
                    is_default=first, active=True)
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return _out(branch)


@router.put("/{branch_id}")
def update_branch(branch_id: int, body: BranchIn, db: Session = Depends(get_db),
                  _: User = Depends(require_role("admin"))):
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")
    clash = (db.query(Branch)
             .filter(Branch.code == body.code.strip().upper(), Branch.id != branch_id)
             .first())
    if clash:
        raise HTTPException(400, f"Branch code {body.code.upper()} is already in use.")
    for key, value in body.model_dump().items():
        setattr(branch, key, value.strip().upper() if key == "code" else value)
    db.commit()
    return _out(branch)


@router.post("/{branch_id}/close")
def close_branch(branch_id: int, db: Session = Depends(get_db),
                 _: User = Depends(require_role("admin"))):
    """Close a branch without deleting it.

    Deleting would orphan every sale, batch and movement written there, and the
    history of a shop that has shut is exactly what an auditor asks for. The
    default branch cannot be closed: something has to own the rows.
    """
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")
    if branch.is_default:
        raise HTTPException(
            400,
            "This is the default branch and cannot be closed. Make another "
            "branch the default first.")
    # Closing a shop that still holds stock is a real situation, but it should
    # be said out loud rather than discovered at the next count.
    left = branches.stock_at(db, branch_id)
    branch.active = False
    db.commit()
    return {
        "message": f"{branch.name} is closed. Its history is kept.",
        "stock_lines_left_behind": len(left),
        "warning": (f"{len(left)} product line(s) are still on the shelf there. "
                    "Transfer them to another branch or write them off.")
        if left else "",
    }


@router.post("/{branch_id}/make-default")
def make_default(branch_id: int, db: Session = Depends(get_db),
                 _: User = Depends(require_role("admin"))):
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Branch not found")
    if not branch.active:
        raise HTTPException(400, "A closed branch cannot be the default.")
    db.query(Branch).update({Branch.is_default: False}, synchronize_session=False)
    branch.is_default = True
    db.commit()
    return {"message": f"{branch.name} is now the default branch."}


@router.get("/{branch_id}/stock")
def branch_stock(branch_id: int, low_only: bool = False,
                 db: Session = Depends(get_db)):
    """What is on the shelf here, not across the group."""
    if not db.get(Branch, branch_id):
        raise HTTPException(404, "Branch not found")
    rows = branches.stock_at(db, branch_id, low_only=low_only)
    return {
        "branch_id": branch_id,
        "lines": rows,
        "below_reorder": sum(1 for r in rows if r["below_reorder"]),
        "note": "Quantities are what this branch holds. The group total is "
                "shown alongside because reordering is usually a group decision.",
    }


@router.get("/transfers/in-transit")
def transfers_in_transit(db: Session = Depends(get_db)):
    return branches.in_transit(db)


@router.post("/transfers")
def create_transfer(body: TransferIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    try:
        transfer = branches.despatch(
            db, from_branch_id=body.from_branch_id, to_branch_id=body.to_branch_id,
            product_id=body.product_id, quantity=body.quantity,
            user_id=user.id, notes=body.notes)
    except branches.BranchError as e:
        raise HTTPException(400, str(e))
    return {"id": transfer.id, "reference": transfer.reference,
            "status": transfer.status,
            "message": "Despatched. It is in transit until the receiving branch "
                       "books it in."}


@router.post("/transfers/{transfer_id}/receive")
def receive_transfer(transfer_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    try:
        transfer = branches.receive(db, transfer_id=transfer_id, user_id=user.id)
    except branches.BranchError as e:
        raise HTTPException(400, str(e))
    return {"reference": transfer.reference, "status": transfer.status,
            "message": "Received and on the shelf."}
