"""Password on sensitive actions.

Being logged in is not authorisation for everything. Two different needs sit
behind the same password prompt, and treating them as one is the usual mistake:

* **Re-authentication** — "prove you are still the person who logged in". Tills
  are left unlocked while the pharmacist walks to a shelf, and some actions
  destroy value or evidence.
* **Supervisor override** — "get someone senior to approve what you cannot".
  The cashier is not allowed to discount, so the manager walks over and types
  *their own* password on the cashier's till.

The second is the one that actually happens in a pharmacy, and it is why a grant
records two people: who performed the action, and who authorised it. A system
that only supported the first would force the manager to log the cashier out and
log themselves in, which in practice means the manager's password ends up known
to the whole shop.

Design rules the rest of the module follows:

* A grant is **single-action and single-use**. Approving a price override does
  not also approve a void an hour later.
* A grant is **short-lived**. Authority granted at the counter should not
  outlive the customer standing there.
* **Every attempt is recorded, including refusals.** A refused override is more
  interesting than a granted one — repeated refusals on the same till is what
  theft looks like from the outside.
"""
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..auth import verify_password
from . import pins
from ..models import StepUpGrant, User

# How long an approval stays usable. Long enough to finish the transaction the
# supervisor walked over for; short enough that it is not still valid when they
# have gone back to the dispensary.
GRANT_TTL_SECONDS = 180


@dataclass(frozen=True)
class Action:
    key: str
    name: str
    why: str
    # Who may approve it. A supervisor override needs someone in this list to
    # type their password — which may be the same person, if they qualify.
    approvers: tuple = ("admin",)
    # True when the person acting may approve themselves by re-entering their
    # own password. False forces a second person, which is the point for
    # anything where the risk is the operator rather than the unattended till.
    self_approval: bool = True


ACTIONS: dict[str, Action] = {}


def register(action: Action) -> Action:
    ACTIONS[action.key] = action
    return action


register(Action(
    key="sale.void", name="Void a sale",
    why="Voiding destroys a completed transaction and returns stock. It is the "
        "simplest way to take cash from a till and leave no trace, so it is the "
        "action most worth a second signature.",
    approvers=("admin", "pharmacist"), self_approval=False))

register(Action(
    key="sale.price_override", name="Override a price",
    why="A discount given at the counter is money out of the business, and a "
        "cashier under pressure from a customer is exactly who should not be "
        "able to decide it alone.",
    approvers=("admin", "pharmacist"), self_approval=False))

register(Action(
    key="stock.adjust", name="Adjust stock without a document",
    why="An adjustment with no invoice or script behind it is how shrinkage is "
        "hidden. It should cost somebody a password.",
    approvers=("admin", "pharmacist"), self_approval=True))

register(Action(
    key="register.view", name="Open the controlled-substances register",
    why="A legal record of who received which controlled medicine. Access should "
        "be deliberate and attributable, not incidental to being logged in.",
    approvers=("admin", "pharmacist"), self_approval=True))

register(Action(
    key="stocktake.close", name="Close a stock take",
    why="Closing a count posts every variance as a stock movement, and a count "
        "can write off thousands of dollars in one call. It is the largest "
        "single adjustment anybody in the building can make, and the shape of "
        "action that should not rest on one login.",
    approvers=("admin", "pharmacist"), self_approval=False))

register(Action(
    key="layby.cancel", name="Cancel a lay-by",
    why="Cancelling returns goods to the shelf and decides what is refunded and "
        "what fee is kept. A customer's money is being handed back, or not, on "
        "somebody's judgement.",
    approvers=("admin", "pharmacist"), self_approval=True))

register(Action(
    key="script.alter", name="Alter a captured script",
    why="A script is the one record here that carries clinical weight. Changing "
        "a dose or directions after capture is a clinical act, and the trail is "
        "worth nothing if the change itself was casual.",
    approvers=("admin", "pharmacist"), self_approval=True))

register(Action(
    key="pettycash.record", name="Take money out of the till",
    why="A payout leaves the drawer with no sale behind it. Small amounts, often, "
        "with a description nobody checks is the oldest way to lose cash from a "
        "pharmacy.",
    approvers=("admin", "pharmacist", "manager"), self_approval=True))

register(Action(
    key="settings.global", name="Change global settings",
    why="These decide how the whole system behaves, VAT, currency, scheme terms, "
        "reminder rules. One wrong figure here is wrong on every transaction "
        "afterwards, silently.",
    approvers=("admin",), self_approval=True))

register(Action(
    key="scheme.edit", name="Change a medical scheme's terms",
    why="Levies, discounts and fee models decide what every future claim pays. A "
        "wrong figure here misprices thousands of transactions before anyone "
        "notices.",
    approvers=("admin",), self_approval=True))

register(Action(
    key="period.reopen", name="Reopen a closed trading period",
    why="Reopening a signed-off month lets a figure someone has already reported "
        "change underneath them.",
    approvers=("admin",), self_approval=True))

register(Action(
    key="user.manage", name="Create or change a user",
    why="Whoever can create users can create themselves a second identity.",
    approvers=("admin",), self_approval=True))


class StepUpError(PermissionError):
    """Raised when an action is not authorised."""


def _expiry() -> datetime:
    return datetime.utcnow() + timedelta(seconds=GRANT_TTL_SECONDS)


def request(db: Session, *, action_key: str, actor: User, password: str = "",
            pin: str = "", approver_username: str = "", context: str = "") -> StepUpGrant:
    """Ask for authority to perform one action, once.

    `approver_username` names the person typing their credential when it is not
    the person at the till. Left empty, the actor is re-authenticating.

    Either a password or a PIN proves it. The PIN exists because this prompt
    appears mid-transaction on a shared till, with a patient waiting: a password
    typed at a counter is a password read over a shoulder, and one long enough to
    be worth having is long enough that people start choosing bad ones. Four
    digits, rate limited and locked after five failures, is the trade this
    prompt is for. The password path stays for anyone without a PIN set.
    """
    action = ACTIONS.get(action_key)
    if action is None:
        raise StepUpError(f"'{action_key}' is not a protected action.")

    approver = actor
    if approver_username and approver_username != actor.username:
        approver = (db.query(User)
                    .filter(User.username == approver_username, User.active).first())

    def refuse(reason: str) -> StepUpGrant:
        # Recorded, not just returned. A refused override is the interesting one.
        grant = StepUpGrant(
            action=action_key, token=secrets.token_urlsafe(24),
            requested_by_id=actor.id,
            approved_by_id=approver.id if approver and approver.id != actor.id else None,
            granted=False, reason=reason, context=context, expires_at=_expiry())
        db.add(grant)
        db.commit()
        raise StepUpError(reason)

    if approver is None:
        refuse(f"No active user is called '{approver_username}'.")
    if pin:
        try:
            pins.check(db, approver, pin)
        except pins.PinError as exc:
            refuse(str(exc))
    elif password:
        if not verify_password(password, approver.password_hash):
            refuse("That password was not accepted.")
    else:
        refuse("Enter a PIN or a password to authorise this.")
    if approver.role not in action.approvers and approver.role != "admin":
        refuse(f"{approver.full_name} is not permitted to approve "
               f"'{action.name.lower()}'. It needs "
               f"{' or '.join(action.approvers)}.")
    if approver.id == actor.id and not action.self_approval:
        refuse(f"'{action.name}' needs a second person to approve it. Ask a "
               f"{' or '.join(action.approvers)} to enter their own password.")

    grant = StepUpGrant(
        action=action_key, token=secrets.token_urlsafe(24),
        requested_by_id=actor.id, approved_by_id=approver.id,
        granted=True, context=context, expires_at=_expiry())
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return grant


def redeem(db: Session, *, action_key: str, token: str, actor: User) -> StepUpGrant:
    """Spend a grant. Single-use, single-action, and only by the person it was issued to."""
    grant = db.query(StepUpGrant).filter(StepUpGrant.token == (token or "")).first()
    if grant is None or not grant.granted:
        raise StepUpError("That authorisation is not valid.")
    if grant.action != action_key:
        raise StepUpError(
            f"That authorisation was given for '{ACTIONS[grant.action].name.lower()}', "
            f"not for '{ACTIONS[action_key].name.lower()}'.")
    if grant.requested_by_id != actor.id:
        raise StepUpError("That authorisation was issued to a different user.")
    if grant.used_at is not None:
        raise StepUpError("That authorisation has already been used.")
    if grant.expires_at and datetime.utcnow() > grant.expires_at:
        raise StepUpError("That authorisation has expired, ask again.")
    grant.used_at = datetime.utcnow()
    db.commit()
    return grant


def describe(action_key: str) -> dict:
    action = ACTIONS.get(action_key)
    if action is None:
        return {}
    return {"key": action.key, "name": action.name, "why": action.why,
            "approvers": list(action.approvers), "self_approval": action.self_approval,
            "valid_seconds": GRANT_TTL_SECONDS}


def catalogue() -> list[dict]:
    return [describe(k) for k in sorted(ACTIONS)]
