"""What a branch must hold to be allowed to trade, and when it dies.

A pharmacy in Zimbabwe trades on a stack of paper that all expires. The MCAZ
premises licence, the responsible pharmacist's practice certificate, the city
health shop licence, fire brigade clearance, the ZIMRA tax clearance, the
dangerous drugs permit — each with its own issuer, its own renewal month, and
its own consequence for lapsing. For the first two, the consequence is that the
shop closes.

Every pharmacy manages this in a lever-arch file and somebody's diary, and the
failure is always the same shape: nobody notices a certificate has expired until
an inspector does, or until a wholesaler refuses an order because the licence
number on file has lapsed. The renewal is rarely difficult. Knowing it is due is
the entire problem.

THE HALF THAT MATTERS MOST

A register of what you have uploaded cannot tell you what you have not. A branch
with four current certificates and no fire clearance at all looks perfectly
healthy on a list of four green rows — and it is the missing one that closes the
shop. So every branch is measured against the list of what a pharmacy is
expected to hold, and a document that was never uploaded is reported as
**missing**, in the same table, with the same weight as one that has expired.

That is why the kinds below are a list in code rather than only rows in a table.
A pharmacy can add whatever it likes; it cannot make the expected ones
disappear by not entering them.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import Branch, ComplianceDocument

#: Inside this many days a renewal has to be started rather than noted. Most of
#: these take weeks: a tax clearance needs a return filed, an MCAZ renewal needs
#: an inspection booked. A fortnight's warning is not a warning, it is an
#: apology.
WARN_DAYS = 60

#: Inside this, it is the thing to do today.
URGENT_DAYS = 21

#: What a Zimbabwean retail pharmacy is expected to hold.
#:
#: (key, name, who issues it, typical renewal in months, closes the shop if
#:  lapsed, what it is for)
#:
#: `critical` is not a severity dial — it is the specific question "may this
#: branch legally open tomorrow without it". Three of these answer yes.
KINDS: list[tuple[str, str, str, int, bool, str]] = [
    ("mcaz_premises", "MCAZ premises licence",
     "Medicines Control Authority of Zimbabwe", 12, True,
     "The licence to operate the premises as a pharmacy. Without it the shop "
     "cannot lawfully open its doors."),
    ("pcz_practice", "Responsible pharmacist's practice certificate",
     "Pharmacists Council of Zimbabwe", 12, True,
     "A pharmacy may not trade without a registered pharmacist on the "
     "premises, and the certificate is the proof of registration."),
    ("dangerous_drugs", "Dangerous drugs permit",
     "Medicines Control Authority of Zimbabwe", 12, True,
     "Required to hold and dispense schedule 5 and 6 medicines. Lapsed, the "
     "controlled cupboard cannot lawfully be opened."),
    ("city_health", "City health shop licence",
     "Local authority — City of Harare, Bulawayo City Council", 12, False,
     "The municipal trading licence for a health premises. Enforced by "
     "inspection and by a padlock."),
    ("fire_clearance", "Fire brigade clearance certificate",
     "Municipal fire brigade", 12, False,
     "Certifies extinguishers, exits and alarms. Asked for by the local "
     "authority and by every insurer at renewal."),
    ("tax_clearance", "Tax clearance (ITF263)",
     "ZIMRA", 12, False,
     "Without a valid one, every customer who pays you is obliged to withhold "
     "10% — so it is a cash-flow document before it is a compliance one."),
    ("trade_licence", "Shop / trade licence",
     "Local authority", 12, False,
     "The general licence to trade from the address."),
    ("ema_hazard", "Environmental and hazardous waste",
     "Environmental Management Agency", 12, False,
     "Covers disposal of expired medicines and sharps, which a pharmacy "
     "generates whether or not it has thought about it."),
    ("fiscal_device", "Fiscal device registration",
     "ZIMRA", 0, False,
     "Registration of the fiscalised till. Not dated in the same way, but the "
     "certificate is asked for at audit."),
    ("public_liability", "Public liability insurance",
     "Insurer", 12, False,
     "A customer injured on the premises, and the stock itself."),
    ("professional_indemnity", "Professional indemnity insurance",
     "Insurer", 12, False,
     "Covers a dispensing error. The one nobody expects to need."),
    ("nssa", "NSSA registration",
     "National Social Security Authority", 0, False,
     "Employer registration. Asked for whenever the shop hires."),
    ("lease", "Lease agreement",
     "Landlord", 0, False,
     "The right to be in the building. Its end date is a business event, not "
     "only a legal one."),
]

BY_KEY = {k[0]: k for k in KINDS}


def _state(document: ComplianceDocument | None) -> tuple[str, int | None]:
    """Where a document stands: missing, expired, expiring, valid, undated."""
    if document is None:
        return "missing", None
    if not document.expires_on:
        # Some documents genuinely do not expire. Saying "valid" would be a
        # guess and saying "expired" would be a lie; it is simply not dated.
        return "undated", None
    days = (document.expires_on - date.today()).days
    if days < 0:
        return "expired", days
    if days <= URGENT_DAYS:
        return "urgent", days
    if days <= WARN_DAYS:
        return "expiring", days
    return "valid", days


#: Worst first, so a branch's row can be read from one number.
RANK = {"expired": 0, "missing": 1, "urgent": 2, "expiring": 3,
        "undated": 4, "valid": 5}


def branch_register(db: Session, branch_id: int) -> dict:
    """Every document a branch holds, and every one it does not.

    The missing rows are the point. A register of what has been uploaded cannot
    tell anybody what has not, and it is the certificate nobody entered that
    closes the shop.
    """
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise ValueError("That branch does not exist.")

    held = (db.query(ComplianceDocument)
            .options(joinedload(ComplianceDocument.created_by))
            .filter(ComplianceDocument.branch_id == branch_id,
                    ComplianceDocument.active.is_(True))
            .order_by(ComplianceDocument.expires_on.desc()).all())

    # The current one of each kind: the latest expiry wins, because a renewal
    # uploaded beside last year's must not be masked by it.
    current: dict[str, ComplianceDocument] = {}
    for doc in held:
        seen = current.get(doc.kind)
        if seen is None:
            current[doc.kind] = doc
            continue
        if (doc.expires_on or date.min) > (seen.expires_on or date.min):
            current[doc.kind] = doc

    rows = []
    for key, name, issuer, months, critical, why in KINDS:
        doc = current.get(key)
        state, days = _state(doc)
        rows.append({
            "kind": key, "name": name, "expected_issuer": issuer,
            "renewal_months": months, "critical": critical, "why": why,
            "state": state, "days_left": days,
            **_document_row(doc),
        })

    # Anything the pharmacy holds that is not on the expected list. Kept and
    # shown: a shop that has added a radiation licence or a liquor licence
    # should see it beside the rest, not have it vanish because this file did
    # not anticipate it.
    for doc in held:
        if doc.kind in BY_KEY:
            continue
        state, days = _state(doc)
        rows.append({
            "kind": doc.kind, "name": doc.title or doc.kind,
            "expected_issuer": doc.issuer, "renewal_months": 0,
            "critical": False, "why": "Added by this pharmacy.",
            "state": state, "days_left": days,
            **_document_row(doc),
        })

    rows.sort(key=lambda r: (RANK.get(r["state"], 9), not r["critical"],
                             r["days_left"] if r["days_left"] is not None else 9999))

    return {
        "branch_id": branch.id, "branch": branch.name, "code": branch.code,
        "documents": rows,
        **_summarise(rows),
        "history": [
            {**_document_row(d), "kind": d.kind,
             "name": BY_KEY.get(d.kind, (None, d.title or d.kind))[1]
                     if d.kind in BY_KEY else (d.title or d.kind)}
            for d in held if current.get(d.kind) is not d
        ],
    }


def document(db: Session, document_id: int) -> dict:
    """One certificate, with the chain of the ones it replaced.

    A register answers "are we licensed today". This answers the other
    question, which is the one an audit actually asks: **were we licensed in
    March**. A pharmacy holds a renewal every year and the previous certificate
    is the proof it was trading lawfully last year, so nothing here is ever
    deleted — a superseded document keeps its dates, its file and its uploader
    and simply stops being the current one.

    The chain is walked in both directions. From any certificate you can reach
    the one it replaced and the one that replaced it, because somebody handed a
    lapsed number by an inspector needs to get from that number to the current
    document without knowing which of eight rows is the live one.
    """
    doc = db.get(ComplianceDocument, document_id)
    if doc is None:
        raise ValueError("That document is not on file.")

    known = BY_KEY.get(doc.kind)
    branch = db.get(Branch, doc.branch_id)
    state, days = _state(doc)

    # Backwards: what this one replaced, oldest last.
    replaced: list[dict] = []
    seen = {doc.id}
    cursor = (db.query(ComplianceDocument)
              .filter(ComplianceDocument.superseded_by_id == doc.id).first())
    while cursor is not None and cursor.id not in seen:
        seen.add(cursor.id)
        replaced.append({**_document_row(cursor), "state": _state(cursor)[0]})
        cursor = (db.query(ComplianceDocument)
                  .filter(ComplianceDocument.superseded_by_id == cursor.id)
                  .first())

    # Forwards: what replaced this one. Usually nothing, but a document opened
    # from an old link must be able to say "there is a newer one, here".
    replaced_by = None
    if doc.superseded_by_id:
        newer = db.get(ComplianceDocument, doc.superseded_by_id)
        if newer is not None:
            replaced_by = {**_document_row(newer), "state": _state(newer)[0]}

    # Whether this is the branch's current one of its kind. Not the same as
    # `active`: two active certificates of one kind can sit side by side while
    # a renewal is filed early, and only the later expiry is the one in force.
    current = (db.query(ComplianceDocument)
               .filter(ComplianceDocument.branch_id == doc.branch_id,
                       ComplianceDocument.kind == doc.kind,
                       ComplianceDocument.active.is_(True))
               .order_by(ComplianceDocument.expires_on.desc()).first())

    return {
        **_document_row(doc),
        "kind": doc.kind,
        "name": known[1] if known else (doc.title or doc.kind),
        "title": doc.title or "",
        "expected_issuer": known[2] if known else "",
        "renewal_months": known[3] if known else 0,
        "critical": bool(known[4]) if known else False,
        "why": known[5] if known else "Added by this pharmacy.",
        "state": state,
        "days_left": days,
        "active": bool(doc.active),
        "is_current": current is not None and current.id == doc.id,
        "file_type": doc.file_type or "",
        "file_bytes": doc.file_bytes or 0,
        "branch_id": doc.branch_id,
        "branch": branch.name if branch else "",
        "branch_code": branch.code if branch else "",
        "replaced": replaced,
        "replaced_by": replaced_by,
    }


def _document_row(doc: ComplianceDocument | None) -> dict:
    if doc is None:
        return {"id": None, "reference": "", "issuer": "", "issued_on": None,
                "expires_on": None, "renewal_cost": 0.0, "has_file": False,
                "file_name": "", "notes": "", "uploaded_by": "",
                "uploaded_at": None}
    return {
        "id": doc.id, "reference": doc.reference or "",
        "issuer": doc.issuer or "", "issued_on": doc.issued_on,
        "expires_on": doc.expires_on,
        "renewal_cost": round(doc.renewal_cost or 0.0, 2),
        "has_file": bool(doc.file_data),
        "file_name": doc.file_name or "",
        "notes": doc.notes or "",
        "uploaded_by": doc.created_by.full_name if doc.created_by else "",
        "uploaded_at": doc.created_at,
    }


def _summarise(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    # Lapsed and never-entered are not the same finding, and conflating them is
    # the fastest way to have this whole register disbelieved.
    #
    # A critical licence recorded as EXPIRED is a real, dated fact: the branch
    # is trading on something that ran out, and somebody should act today.
    #
    # A critical licence that is MISSING means only that nothing has been
    # uploaded. On the day this feature is switched on, every branch is in that
    # state — and telling a pharmacy that has traded for fifteen years it
    # "cannot lawfully open" because nobody has scanned a certificate yet is
    # both wrong and the reason they would stop reading the screen.
    lapsed = [r["name"] for r in rows
              if r["critical"] and r["state"] == "expired"]
    unproven = [r["name"] for r in rows
                if r["critical"] and r["state"] == "missing"]
    at_risk = [r["name"] for r in rows if r["state"] in ("expired", "urgent")]
    stopped = lapsed

    if lapsed:
        verdict = "cannot trade"
        says = (f"{lapsed[0]} expired. A branch trading without it is not "
                f"lawfully open, and this is the one to deal with today.")
    elif unproven:
        verdict = "cannot be proved"
        says = (f"{len(unproven)} licence(s) that a branch cannot trade "
                f"without have nothing on file — {unproven[0]} among them. "
                f"The branch may well hold them; nobody here can show an "
                f"inspector that it does.")
    elif counts.get("expired"):
        verdict = "expired"
        says = (f"{counts['expired']} document(s) have expired. None of them "
                f"closes the shop on its own, and an inspection will still "
                f"find them.")
    elif counts.get("missing"):
        verdict = "gaps"
        says = (f"{counts['missing']} expected document(s) are not on file. "
                f"They may exist in a folder somewhere — until they are here, "
                f"nobody can say.")
    elif counts.get("urgent"):
        verdict = "renew now"
        says = (f"{counts['urgent']} renewal(s) fall due within "
                f"{URGENT_DAYS} days. Most of these take weeks.")
    elif counts.get("expiring"):
        verdict = "renewals due"
        says = f"{counts['expiring']} renewal(s) within {WARN_DAYS} days."
    else:
        verdict = "in order"
        says = "Everything expected is on file and current."

    return {
        "counts": counts,
        "verdict": verdict,
        "says": says,
        "blocking": stopped,
        "at_risk": at_risk,
        "renewal_cost_year": round(
            sum(r["renewal_cost"] for r in rows if r["renewal_months"]), 2),
    }


def overview(db: Session) -> dict:
    """Every branch's standing, worst first.

    An owner with four shops asks one question about this and it is not "show
    me the certificates" — it is "is anything about to stop one of my branches
    trading".
    """
    branches = (db.query(Branch).filter(Branch.active.is_(True))
                .order_by(Branch.name).all())
    rows = []
    for branch in branches:
        try:
            register = branch_register(db, branch.id)
        except ValueError:
            continue
        rows.append({
            "branch_id": branch.id, "branch": branch.name, "code": branch.code,
            "verdict": register["verdict"], "says": register["says"],
            "counts": register["counts"],
            "blocking": register["blocking"],
            "expired": register["counts"].get("expired", 0),
            "missing": register["counts"].get("missing", 0),
            "urgent": register["counts"].get("urgent", 0),
            "renewal_cost_year": register["renewal_cost_year"],
            "next": _next_renewal(register["documents"]),
        })

    order = {"cannot trade": 0, "cannot be proved": 1, "expired": 2,
             "gaps": 3, "renew now": 4, "renewals due": 5, "in order": 6}
    rows.sort(key=lambda r: order.get(r["verdict"], 9))

    stopped = [r["branch"] for r in rows if r["verdict"] == "cannot trade"]
    unproven = [r["branch"] for r in rows if r["verdict"] == "cannot be proved"]
    return {
        "branches": rows,
        "cannot_trade": stopped,
        "cannot_be_proved": unproven,
        "expired": sum(r["expired"] for r in rows),
        "missing": sum(r["missing"] for r in rows),
        "urgent": sum(r["urgent"] for r in rows),
        "renewal_cost_year": round(sum(r["renewal_cost_year"] for r in rows), 2),
        "headline": (
            f"{', '.join(stopped)}: a licence the shop cannot trade without "
            f"has expired. Deal with that today."
            if stopped else
            f"Nothing is on file yet. {len(unproven)} branch(es) hold licences "
            f"nobody here can produce — start with the MCAZ premises licence "
            f"and the practice certificate, which are the two an inspector "
            f"asks for first."
            if unproven and not any(r["expired"] or r["urgent"] for r in rows)
            else
            f"{sum(r['expired'] for r in rows)} expired, "
            f"{sum(r['missing'] for r in rows)} never uploaded, "
            f"{sum(r['urgent'] for r in rows)} due within {URGENT_DAYS} days "
            f"across {len(rows)} branch(es)."),
    }


def _next_renewal(documents: list[dict]) -> dict | None:
    dated = [d for d in documents
             if d["days_left"] is not None and d["days_left"] >= 0]
    if not dated:
        return None
    soonest = min(dated, key=lambda d: d["days_left"])
    return {"name": soonest["name"], "days": soonest["days_left"],
            "on": soonest["expires_on"]}


def suggest_expiry(kind: str, issued: date | None) -> date | None:
    """When a document of this kind would normally next fall due.

    Offered, never imposed. A pharmacy whose MCAZ licence runs to a different
    month than the default should type the real date, and the field is prefilled
    rather than computed so the typed one always wins.
    """
    entry = BY_KEY.get(kind)
    if not entry or not entry[3] or issued is None:
        return None
    months = entry[3]
    year = issued.year + (issued.month - 1 + months) // 12
    month = (issued.month - 1 + months) % 12 + 1
    day = min(issued.day, [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30,
                           31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)
