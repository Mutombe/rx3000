"""Branch registry, per-branch stock, and transfers between branches."""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import Branch, BranchTransfer, Product, User
from ..branch_scope import every_branch
from ..services import branches, permissions

def _guard(db: Session, user: User, capability: str) -> None:
    """Refuse in the server's own words, so the screen can relay them."""
    decision = permissions.check(db, user, capability)
    if not decision["allowed"]:
        raise HTTPException(403, decision["why"])


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


def _out_full(b: Branch) -> dict:
    """Everything about one branch, for the screen that opened it.

    The list carries what a list needs. This carries what somebody asking
    about a particular shop needs, and the difference is the part that
    explains a state rather than reporting it: a closed branch has a date, a
    person and a reason behind it, and "Closed" on its own invites the next
    question rather than answering it.
    """
    out = _out(b)
    out.update({
        "latitude": b.latitude, "longitude": b.longitude,
        "created_at": b.created_at,
        "frozen": bool(getattr(b, "frozen", False)),
        "frozen_at": getattr(b, "frozen_at", None),
        "frozen_reason": getattr(b, "frozen_reason", "") or "",
    })
    return out


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
    # Across every branch on purpose: stock in transit belongs to neither shop
    # at the moment it is asked about, and the whole point of the list is to
    # see the gap between the two.
    with every_branch():
        return branches.in_transit(db)


@router.get("/transfers/holdings")
def transfer_holdings(product_id: int, db: Session = Depends(get_db)):
    """What every branch holds of one product, for deciding where to move it.

    The screen that sends stock has to show both shelves before it moves
    anything, or "transfer 20" is a number typed into the dark. Unscoped for
    the same reason the transfer itself is: the question is about the estate,
    and somebody at head office stands at no branch at all.
    """
    with every_branch():
        product = db.get(Product, product_id)
        if not product:
            raise HTTPException(404, "No such product.")
        rows = (db.query(Branch)
                .filter(Branch.active.is_(True))
                .order_by(Branch.name).all())
        held = []
        for b in rows:
            held.append({
                "branch_id": b.id, "branch": b.name,
                "code": getattr(b, "code", "") or "",
                "on_hand": branches.on_hand(db, product_id, b.id),
            })
    return {
        "product_id": product.id,
        "product": product.name,
        "strength": product.strength or "",
        "units_per_pack": product.units_per_pack or 1,
        "branches": held,
        "group_total": sum(h["on_hand"] for h in held),
    }


@router.post("/transfers")
def create_transfer(body: TransferIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    _guard(db, user, "stock.transfer")
    try:
        # Unscoped, because a transfer is by definition work that crosses two
        # shops. Without this the batch query ran under the caller's own branch
        # filter, so despatching from anywhere but the branch you are standing
        # in reported "that branch holds 0" no matter how full its shelf was.
        # branch_scope's own docstring names a stock transfer as the example of
        # work that must cross branches; nothing had ever said so in code.
        with every_branch():
            transfer = branches.despatch(
                db, from_branch_id=body.from_branch_id, to_branch_id=body.to_branch_id,
                product_id=body.product_id, quantity=body.quantity,
                user_id=user.id, notes=body.notes)
    except branches.BranchError as e:
        raise HTTPException(400, str(e))
    # The message has to match what actually happened. A transfer above the
    # approval threshold has moved no stock at all, and telling somebody it is
    # "in transit" is how a lorry gets loaded against a request nobody has
    # agreed to.
    asked = transfer.status == "requested"
    return {"id": transfer.id, "reference": transfer.reference,
            "status": transfer.status,
            "message": ("Requested. Nothing has left the shelf: this is worth "
                        "more than the figure the pharmacy set, so somebody "
                        "has to approve it first."
                        if asked else
                        "Despatched. It is in transit until the receiving "
                        "branch books it in.")}


@router.post("/transfers/{transfer_id}/approve")
def approve_transfer(transfer_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Agree a requested transfer. This is when the stock leaves."""
    _guard(db, user, "stock.write_off")
    try:
        with every_branch():
            transfer = branches.approve_transfer(
                db, transfer_id=transfer_id, user_id=user.id)
    except branches.BranchError as e:
        raise HTTPException(400, str(e))
    return {"id": transfer.id, "reference": transfer.reference,
            "status": transfer.status,
            "message": (f"{transfer.reference} approved. {transfer.quantity} "
                        "unit(s) have left and are in transit.")}


@router.post("/transfers/{transfer_id}/refuse")
def refuse_transfer(transfer_id: int, body: dict = Body(default={}),
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Turn down a request. Nothing moved, so nothing has to move back."""
    _guard(db, user, "stock.write_off")
    try:
        with every_branch():
            transfer = branches.refuse_transfer(
                db, transfer_id=transfer_id, user_id=user.id,
                why=str(body.get("why") or ""))
    except branches.BranchError as e:
        raise HTTPException(400, str(e))
    return {"id": transfer.id, "reference": transfer.reference,
            "status": transfer.status,
            "message": f"{transfer.reference} refused. No stock moved."}


@router.post("/transfers/{transfer_id}/receive")
def receive_transfer(transfer_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _guard(db, user, "stock.transfer")
    try:
        with every_branch():
            transfer = branches.receive(db, transfer_id=transfer_id, user_id=user.id)
    except branches.BranchError as e:
        raise HTTPException(400, str(e))
    return {"reference": transfer.reference, "status": transfer.status,
            "message": "Received and on the shelf."}


@router.get("/{branch_id}")
def one_branch(branch_id: int, db: Session = Depends(get_db)):
    """One shop, for the screen that opened it.

    Declared last on purpose. A bare single segment path would otherwise sit
    in front of every literal route added after it, and `/transfers` would
    quietly start resolving to a branch whose id is the word transfers.
    """
    with every_branch():
        b = db.get(Branch, branch_id)
    if not b:
        raise HTTPException(404, "That branch is not on file.")
    return _out_full(b)
