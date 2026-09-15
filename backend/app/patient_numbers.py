"""Every patient gets a profile number, however they came to be on file.

CareXpress To-Be blueprint §3 step 1: a new patient is registered and their
profile number is auto-generated. RX5000 had none — a patient was their
database id, which nobody can say across a counter and which means nothing
once records move between systems.

The number is `PT` + year and month + a five-digit sequence — `PT260900412` —
the same shape as a script (`RX…`) or an invoice (`INV…`), so staff read it
the same way. It is issued once and never changes.

Issued at flush, not in the registration endpoint, because patients arrive by
more than one door: the counter, the CareXpress importer, the seeds. A number
issued only at the counter would leave every imported patient without one, and
the per-pharmacy unique index would then refuse the second import on a clash
of blanks. Hooking the flush means no door can forget.
"""
from datetime import datetime

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from . import tenancy

PREFIX = "PT"


def _stamp(when: datetime | None = None) -> str:
    return f"{PREFIX}{(when or datetime.utcnow()):%y%m}"


def _highest(session: Session, stamp: str, pharmacy_id: int | None) -> int:
    """The highest sequence issued this month — in plain SQL, on purpose.

    Not through the ORM. Every ORM read is filtered by the pharmacy in force,
    and outside a request — the importer, a seed — there is none, so the filter
    narrows the read to rows with no pharmacy at all. The highest number came
    back as nothing, numbering restarted at 00001, and the insert collided with
    the patient who already had it. Found by writing a patient the importer's
    way in the test, not at the counter, where the filter happens to be right.

    Scoped to the patient's pharmacy when it is known. When it is not, the
    highest across every pharmacy is used: a number above all of them is unique
    in each of them, which is the property that matters.
    """
    if pharmacy_id is not None:
        row = session.connection().execute(text(
            "SELECT MAX(profile_number) FROM patients "
            "WHERE pharmacy_id = :p AND profile_number LIKE :s"),
            {"p": pharmacy_id, "s": f"{stamp}%"}).scalar()
    else:
        row = session.connection().execute(text(
            "SELECT MAX(profile_number) FROM patients WHERE profile_number LIKE :s"),
            {"s": f"{stamp}%"}).scalar()
    tail = str(row)[len(stamp):] if row else ""
    return int(tail) if tail.isdigit() else 0


def _number_new_patients(session: Session, flush_context, instances) -> None:
    from .models import Patient  # imported late: models imports database

    fresh = [o for o in session.new
             if isinstance(o, Patient) and not (o.profile_number or "").strip()]
    if not fresh:
        return

    stamp = _stamp()
    # The pharmacy from the row if it has been stamped, otherwise the one in
    # force: the hook that stamps new rows is registered on each session and
    # this one on the class, and nothing promises which runs first.
    in_force = tenancy.current_pharmacy_id()
    next_for: dict[int | None, int] = {}
    # Several patients in one flush — an import — are numbered from one read per
    # pharmacy, in the order they were added, so none is handed the same number.
    for patient in fresh:
        pharmacy = getattr(patient, "pharmacy_id", None) or in_force
        if pharmacy not in next_for:
            next_for[pharmacy] = _highest(session, stamp, pharmacy) + 1
        patient.profile_number = f"{stamp}{next_for[pharmacy]:05d}"
        next_for[pharmacy] += 1


def install() -> None:
    """On every session, not one factory: the importers and seeds open their own."""
    if not event.contains(Session, "before_flush", _number_new_patients):
        event.listen(Session, "before_flush", _number_new_patients)
