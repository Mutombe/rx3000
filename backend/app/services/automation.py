"""CRM automation engine — assignment, escalation, scoring and task creation.

Rules are stored records, evaluated in `sort_order`, and matched on a single
field/value pair. Blank `trigger_value` matches anything, so a catch-all
assignment rule is just a rule with no value.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Activity, AutomationRule, Lead, Ticket

log = logging.getLogger("rx5000.automation")

RULE_TYPES = [
    "lead_assignment", "lead_scoring", "ticket_assignment", "ticket_escalation", "deal_task",
]

# Baseline scoring applied before any custom rules
BASE_LEAD_SCORE = {
    "source": {"referral": 25, "event": 20, "campaign": 15, "web": 10, "phone": 10, "walk_in": 5},
}


def _rules(db: Session, rule_type: str) -> list[AutomationRule]:
    return (
        db.query(AutomationRule)
        .filter(AutomationRule.rule_type == rule_type, AutomationRule.active.is_(True))
        .order_by(AutomationRule.sort_order, AutomationRule.id)
        .all()
    )


def _matches(rule: AutomationRule, value) -> bool:
    if not rule.trigger_value:
        return True
    return str(value or "").strip().lower() == rule.trigger_value.strip().lower()


def _field(obj, name: str):
    return getattr(obj, name, None) if name else None


def rating_for(score: int) -> str:
    if score >= 60:
        return "hot"
    if score >= 30:
        return "warm"
    return "cold"


def score_lead(db: Session, lead: Lead) -> int:
    """Derive a lead score from its attributes plus any custom scoring rules."""
    score = BASE_LEAD_SCORE["source"].get((lead.source or "").lower(), 0)
    if lead.email:
        score += 10
    if lead.phone:
        score += 10
    if lead.company_name:
        score += 10
    if lead.estimated_value >= 50000:
        score += 25
    elif lead.estimated_value >= 10000:
        score += 15
    elif lead.estimated_value > 0:
        score += 5
    if lead.marketing_opt_in:
        score += 5

    for rule in _rules(db, "lead_scoring"):
        if _matches(rule, _field(lead, rule.trigger_field)):
            try:
                score += int(rule.action_value)
            except (TypeError, ValueError):
                continue
            rule.times_fired += 1

    score = max(0, min(100, score))
    lead.score = score
    lead.rating = rating_for(score)
    return score


def explain_lead_score(db: Session, lead: Lead) -> dict:
    """Itemise how a lead's score was reached.

    Mirrors `score_lead` exactly but has no side effects — nothing is written
    and no rule fire-count is incremented, so this is safe to call on every
    record view.
    """
    src = (lead.source or "").lower()
    factors: list[dict] = [
        {
            "label": f"Source — {src.replace('_', ' ') or 'unknown'}",
            "points": BASE_LEAD_SCORE["source"].get(src, 0),
            "max": max(BASE_LEAD_SCORE["source"].values()),
            "group": "Fit",
        },
        {"label": "Email address captured", "points": 10 if lead.email else 0,
         "max": 10, "group": "Contactability"},
        {"label": "Phone number captured", "points": 10 if lead.phone else 0,
         "max": 10, "group": "Contactability"},
        {"label": "Linked to a company", "points": 10 if lead.company_name else 0,
         "max": 10, "group": "Fit"},
    ]

    if lead.estimated_value >= 50000:
        value_points, value_label = 25, "Deal size, R50k or above"
    elif lead.estimated_value >= 10000:
        value_points, value_label = 15, "Deal size, R10k to R50k"
    elif lead.estimated_value > 0:
        value_points, value_label = 5, "Deal size, under R10k"
    else:
        value_points, value_label = 0, "Deal size, not estimated"
    factors.append({"label": value_label, "points": value_points, "max": 25, "group": "Value"})
    factors.append({
        "label": "Consented to marketing (POPIA)",
        "points": 5 if lead.marketing_opt_in else 0, "max": 5, "group": "Engagement",
    })

    for rule in _rules(db, "lead_scoring"):
        if _matches(rule, _field(lead, rule.trigger_field)):
            try:
                points = int(rule.action_value)
            except (TypeError, ValueError):
                continue
            factors.append({
                "label": f"Rule — {rule.name}", "points": points,
                "max": points, "group": "Automation",
            })

    raw = sum(f["points"] for f in factors)
    return {
        "score": max(0, min(100, raw)),
        "raw_score": raw,
        "rating": rating_for(max(0, min(100, raw))),
        "capped": raw > 100,
        "factors": factors,
    }


def assign_lead(db: Session, lead: Lead) -> None:
    if lead.owner_id is not None:
        return
    for rule in _rules(db, "lead_assignment"):
        if _matches(rule, _field(lead, rule.trigger_field)):
            try:
                lead.owner_id = int(rule.action_value)
            except (TypeError, ValueError):
                continue
            rule.times_fired += 1
            log.info("Lead %s auto-assigned by rule '%s'", lead.id, rule.name)
            return


def assign_ticket(db: Session, ticket: Ticket) -> None:
    if ticket.assigned_to_id is not None:
        return
    for rule in _rules(db, "ticket_assignment"):
        if _matches(rule, _field(ticket, rule.trigger_field)):
            try:
                ticket.assigned_to_id = int(rule.action_value)
            except (TypeError, ValueError):
                continue
            rule.times_fired += 1
            log.info("Ticket %s auto-assigned by rule '%s'", ticket.ticket_number, rule.name)
            return


def create_deal_tasks(db: Session, deal, owner_id: int | None) -> int:
    """Fire task-creation rules when a deal reaches a stage."""
    created = 0
    for rule in _rules(db, "deal_task"):
        if _matches(rule, _field(deal, rule.trigger_field or "stage")):
            db.add(Activity(
                activity_type="task",
                subject=rule.action_value or f"Follow up: {deal.title}",
                body=f"Auto-created by automation rule '{rule.name}'.",
                due_at=datetime.utcnow() + timedelta(days=2),
                owner_id=deal.owner_id or owner_id,
                deal_id=deal.id, company_id=deal.company_id, contact_id=deal.contact_id,
            ))
            rule.times_fired += 1
            created += 1
    return created


def escalate_overdue_tickets(db: Session) -> int:
    """Raise priority on tickets that have blown their SLA without a first reply."""
    now = datetime.utcnow()
    ladder = {"low": "normal", "normal": "high", "high": "urgent"}
    overdue = (
        db.query(Ticket)
        .filter(Ticket.status.in_(["open", "pending"]),
                Ticket.due_at < now,
                Ticket.first_response_at.is_(None))
        .all()
    )
    escalated = 0
    rules = _rules(db, "ticket_escalation")
    for ticket in overdue:
        target = None
        for rule in rules:
            if _matches(rule, _field(ticket, rule.trigger_field)):
                target = rule.action_value or ladder.get(ticket.priority)
                rule.times_fired += 1
                break
        else:
            target = ladder.get(ticket.priority)
        if target and target != ticket.priority:
            db.add(Activity(
                activity_type="note",
                subject=f"SLA breached, escalated {ticket.priority} → {target}",
                body=f"Ticket {ticket.ticket_number} passed its response target with no reply.",
                ticket_id=ticket.id, owner_id=ticket.assigned_to_id,
                completed_at=now,
            ))
            ticket.priority = target
            escalated += 1
    if escalated:
        db.commit()
        log.info("Escalated %d overdue ticket(s)", escalated)
    return escalated
