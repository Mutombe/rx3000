"""Trading periods and step-up authorisation."""
from datetime import date

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import StepUpGrant, TradingPeriod, User
from ..services import periods, stepup

router = APIRouter(prefix="/api", tags=["periods"],
                   dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Step-up authorisation
# ---------------------------------------------------------------------------

def require_step_up(action_key: str):
    """Dependency: this endpoint needs a fresh, single-use authorisation.

    The token arrives in a header rather than the body so that protecting an
    endpoint never changes its payload — a route can be made sensitive without
    every caller having to be rewritten.
    """
    def checker(x_step_up: str = Header(default=""),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> StepUpGrant:
        if not x_step_up:
            detail = {"error_code": "STEP_UP_REQUIRED", **stepup.describe(action_key)}
            detail["message"] = (
                f"'{detail.get('name', action_key)}' needs a password before it can "
                "be done. " + ("Ask "
                               + stepup.approvers_phrase(detail.get("approvers", []))
                               + " to approve it."
                               if not detail.get("self_approval") else
                               "Re-enter your password to confirm."))
            # 428 Precondition Required, not 401. A 401 means "you are not
            # signed in", and any sane client responds by sending the user to
            # the login screen — which here would log a cashier out for trying
            # to void a sale. This is "signed in, but this action needs more".
            raise HTTPException(status_code=428, detail=detail)
        try:
            return stepup.redeem(db, action_key=action_key, token=x_step_up, actor=user)
        except stepup.StepUpError as exc:
            raise HTTPException(status_code=403, detail={
                "error_code": "STEP_UP_INVALID", "message": str(exc)}) from exc
    return checker


@router.get("/step-up/actions")
def protected_actions():
    """Every action that needs a password, and why. Published so the UI can explain."""
    return stepup.catalogue()


@router.post("/step-up")
def request_step_up(action: str = Body(...), password: str = Body(default=""),
                    pin: str = Body(default=""),
                    approver: str = Body(default=""), context: str = Body(default=""),
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Ask for authority to perform one action, once.

    `approver` names the supervisor typing their own password on someone else's
    till. Omit it to re-authenticate as yourself.
    """
    try:
        grant = stepup.request(db, action_key=action, actor=user, password=password,
                               pin=pin, approver_username=approver, context=context)
    except stepup.StepUpError as exc:
        raise HTTPException(status_code=403, detail={
            "error_code": "STEP_UP_REFUSED", "message": str(exc)}) from exc
    return {
        "token": grant.token,
        "action": grant.action,
        "expires_at": grant.expires_at,
        "approved_by": grant.approved_by.full_name if grant.approved_by else "",
        "self_approved": grant.approved_by_id == grant.requested_by_id,
    }


@router.get("/step-up/log")
def step_up_log(action: str = "", granted: bool | None = None, limit: int = 100,
                db: Session = Depends(get_db)):
    """Who asked for what, who approved it, and what was refused.

    Refusals are the interesting rows: repeated refusals on one till is what
    theft looks like from the outside.
    """
    query = db.query(StepUpGrant)
    if action:
        query = query.filter(StepUpGrant.action == action)
    if granted is not None:
        query = query.filter(StepUpGrant.granted.is_(granted))
    rows = query.order_by(desc(StepUpGrant.created_at)).limit(limit).all()
    return [{
        "id": g.id, "action": g.action,
        "action_name": (stepup.ACTIONS[g.action].name if g.action in stepup.ACTIONS
                        else g.action),
        "requested_by": g.requested_by.full_name if g.requested_by else "",
        "approved_by": g.approved_by.full_name if g.approved_by else "",
        "granted": g.granted, "reason": g.reason, "context": g.context,
        "created_at": g.created_at, "used_at": g.used_at,
        "supervisor_override": bool(g.approved_by_id
                                    and g.approved_by_id != g.requested_by_id),
    } for g in rows]


# ---------------------------------------------------------------------------
# Trading periods
# ---------------------------------------------------------------------------

@router.get("/periods")
def list_periods(limit: int = 36, db: Session = Depends(get_db)):
    return [periods.summarise(db, p, live=False)
            for p in periods.list_periods(db, limit)]


@router.get("/periods/current")
def current_period(db: Session = Depends(get_db)):
    return periods.summarise(db, periods.current(db))


@router.get("/periods/{code}")
def get_period(code: str, db: Session = Depends(get_db)):
    period = db.query(TradingPeriod).filter(TradingPeriod.code == code).first()
    if not period:
        raise HTTPException(status_code=404, detail=f"No trading period {code}")
    return periods.summarise(db, period)


@router.get("/periods/postable/check")
def check_postable(on: date | None = None, db: Session = Depends(get_db)):
    """Whether a transaction dated `on` may be posted. The till asks before saving."""
    ok, reason = periods.is_postable(db, on)
    return {"date": on or date.today(), "postable": ok, "reason": reason}


@router.post("/periods/{code}/open")
def open_period(code: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Create or reopen a period by code, for a pharmacy loading its history."""
    try:
        period = periods.open_code(db, code, user.id)
    except periods.PeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return periods.summarise(db, period)


@router.post("/periods/{code}/close")
def close_period(code: str, notes: str = Body(default="", embed=True),
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    period = db.query(TradingPeriod).filter(TradingPeriod.code == code).first()
    if not period:
        raise HTTPException(status_code=404, detail=f"No trading period {code}")
    try:
        periods.close(db, period, user.id, notes)
    except periods.PeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return periods.summarise(db, period)


@router.post("/periods/{code}/reopen")
def reopen_period(code: str, reason: str = Body(..., embed=True),
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user),
                  _grant=Depends(require_step_up("period.reopen"))):
    """Reopen a signed-off month. Needs an administrator's password and a reason."""
    period = db.query(TradingPeriod).filter(TradingPeriod.code == code).first()
    if not period:
        raise HTTPException(status_code=404, detail=f"No trading period {code}")
    try:
        periods.reopen(db, period, user.id, reason)
    except periods.PeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return periods.summarise(db, period)


@router.post("/periods/{code}/lock")
def lock_period(code: str, reason: str = Body(default="", embed=True),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    period = db.query(TradingPeriod).filter(TradingPeriod.code == code).first()
    if not period:
        raise HTTPException(status_code=404, detail=f"No trading period {code}")
    try:
        periods.lock(db, period, user.id, reason)
    except periods.PeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return periods.summarise(db, period)
