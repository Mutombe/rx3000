"""Customer service help desk: tickets, SLA targets and threaded replies."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import helpers, schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Activity, Ticket, TicketMessage, User
from ..services import automation

router = APIRouter(prefix="/api/helpdesk", tags=["helpdesk"], dependencies=[Depends(get_current_user)])

# First-response SLA in hours by priority
SLA_HOURS = {"urgent": 4, "high": 8, "normal": 24, "low": 72}
OPEN_STATUSES = ("open", "pending")


def _serialize_due(ticket: Ticket) -> Ticket:
    return ticket


@router.get("/tickets", response_model=list[schemas.TicketOut])
def list_tickets(
    status: str = "", priority: str = "", assigned_to_id: int | None = None,
    q: str = "", breached: bool = False, limit: int = 200, db: Session = Depends(get_db),
):
    query = db.query(Ticket)
    if status == "open":
        query = query.filter(Ticket.status.in_(OPEN_STATUSES))
    elif status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if assigned_to_id:
        query = query.filter(Ticket.assigned_to_id == assigned_to_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Ticket.subject.ilike(like), Ticket.description.ilike(like),
                                 Ticket.ticket_number.ilike(like)))
    if breached:
        query = query.filter(Ticket.status.in_(OPEN_STATUSES), Ticket.due_at < datetime.utcnow())
    return query.order_by(Ticket.created_at.desc()).limit(limit).all()


@router.post("/tickets", response_model=schemas.TicketOut)
def create_ticket(body: schemas.TicketCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.priority not in SLA_HOURS:
        raise HTTPException(status_code=400, detail=f"Priority must be one of: {', '.join(SLA_HOURS)}")
    ticket = Ticket(
        **body.model_dump(),
        ticket_number=helpers.next_number(db, Ticket, "TKT", "ticket_number"),
        created_by_id=user.id,
        due_at=datetime.utcnow() + timedelta(hours=SLA_HOURS[body.priority]),
    )
    db.add(ticket)
    db.flush()
    automation.assign_ticket(db, ticket)
    if body.description:
        db.add(TicketMessage(ticket_id=ticket.id, from_customer=True, body=body.description))
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/tickets/{ticket_id}", response_model=schemas.TicketOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.put("/tickets/{ticket_id}", response_model=schemas.TicketOut)
def update_ticket(ticket_id: int, body: schemas.TicketUpdate, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    data = body.model_dump(exclude_none=True)
    if "priority" in data:
        if data["priority"] not in SLA_HOURS:
            raise HTTPException(
                status_code=400,
                detail=f"'{data['priority']}' is not a priority. Use one of: "
                       f"{', '.join(SLA_HOURS)}.")
        # re-base the SLA clock off ticket creation so escalation tightens the deadline
        ticket.due_at = ticket.created_at + timedelta(hours=SLA_HOURS[data["priority"]])
    if "status" in data:
        CASE_STATUSES = ("open", "pending", "resolved", "closed")
        if data["status"] not in CASE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"'{data['status']}' is not a case status. Use one of: "
                       f"{', '.join(CASE_STATUSES)}.")
        if data["status"] in ("resolved", "closed") and ticket.resolved_at is None:
            ticket.resolved_at = datetime.utcnow()
        if data["status"] in ("open", "pending"):
            ticket.resolved_at = None
    if "satisfaction" in data and not 1 <= data["satisfaction"] <= 5:
        raise HTTPException(status_code=400, detail="Satisfaction must be 1-5")

    for key, value in data.items():
        setattr(ticket, key, value)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.post("/tickets/{ticket_id}/messages", response_model=schemas.TicketOut)
def add_message(
    ticket_id: int,
    body: schemas.TicketMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    db.add(TicketMessage(
        ticket_id=ticket.id,
        author_id=None if body.from_customer else user.id,
        from_customer=body.from_customer,
        internal_note=body.internal_note,
        body=body.body,
    ))
    # first staff reply stops the SLA clock
    if not body.from_customer and not body.internal_note and ticket.first_response_at is None:
        ticket.first_response_at = datetime.utcnow()
    if body.from_customer and ticket.status in ("resolved", "closed"):
        ticket.status = "open"     # customer replied — reopen
        ticket.resolved_at = None
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/stats")
def helpdesk_stats(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    open_tickets = db.query(Ticket).filter(Ticket.status.in_(OPEN_STATUSES)).all()
    resolved = db.query(Ticket).filter(Ticket.resolved_at.isnot(None)).all()

    response_mins = [
        (t.first_response_at - t.created_at).total_seconds() / 60
        for t in resolved + open_tickets if t.first_response_at
    ]
    resolution_hours = [
        (t.resolved_at - t.created_at).total_seconds() / 3600 for t in resolved
    ]
    rated = [t.satisfaction for t in resolved if t.satisfaction]

    by_priority = {
        p: db.query(func.count(Ticket.id)).filter(
            Ticket.status.in_(OPEN_STATUSES), Ticket.priority == p
        ).scalar()
        for p in SLA_HOURS
    }
    by_category = dict(
        db.query(Ticket.category, func.count(Ticket.id))
        .filter(Ticket.status.in_(OPEN_STATUSES)).group_by(Ticket.category).all()
    )

    return {
        "open": len(open_tickets),
        "awaiting_first_response": len([t for t in open_tickets if t.first_response_at is None]),
        "sla_breached": len([t for t in open_tickets if t.due_at and t.due_at < now]),
        "due_within_2h": len([
            t for t in open_tickets if t.due_at and now <= t.due_at <= now + timedelta(hours=2)
        ]),
        "resolved_total": len(resolved),
        "avg_first_response_mins": round(sum(response_mins) / len(response_mins), 1) if response_mins else None,
        "avg_resolution_hours": round(sum(resolution_hours) / len(resolution_hours), 1) if resolution_hours else None,
        "csat": round(sum(rated) / len(rated), 2) if rated else None,
        "by_priority": by_priority,
        "by_category": by_category,
        "sla_hours": SLA_HOURS,
    }
