"""Which data tables link their rows to a detail page, and which are dead ends.

The rule being checked: a row that names a thing — a patient, a script, a
product, an invoice — should be a way of getting to that thing. A table that
prints a patient's name as plain text makes the reader search for them by hand
on another screen, which is the difference between software and a report.

Reads the source rather than the running app, because a table that only appears
when a filter matches would never be seen by a crawler and still has to be right.
"""
import pathlib
import re
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"

#: The things a row can name, and where their detail page lives. Used to guess
#: what a table is *about* from the columns it prints.
ENTITIES = {
    "patient": "/patients/",
    "prescription": "/prescriptions/",
    "product": "/products/",
    "sale": "/sales/",
    "order": "/orders/",
    "supplier": "/suppliers/",
    "invoice": "/payables/invoices/",
    "claim": "/claims/",
    "batch": "/batches/",
    "deal": "/deals/",
    "contact": "/contacts/",
    "lead": "/leads/",
    "user": "/staff/",
    "doctor": "/prescribers/",
    "journal": "/ledger/journal/",
    "account": "/accounts/",
    "case": "/cases/",
    "campaign": "/campaigns/",
    "layby": "/laybys/",
    "shift": "/shifts/",
    "message": "/messages/",
}

LINKY = re.compile(r"<Link\b|useNavigate|navigate\(|<NavLink\b|onRowClick|rowHref|to=\{")


def tables_in(text: str) -> list[str]:
    """Each <table>…</table> block, crudely but adequately."""
    out, depth, start = [], 0, None
    for m in re.finditer(r"<table\b|</table>", text):
        if m.group(0) == "<table":
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start:m.end()])
                start = None
    return out


rows = []
for path in sorted(SRC.glob("pages/*.tsx")) + sorted(SRC.glob("components/*.tsx")):
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = tables_in(text)
    if not blocks:
        continue
    for i, block in enumerate(blocks):
        body = block[block.find("<tbody"):] if "<tbody" in block else block
        linked = bool(LINKY.search(body))
        # What does this table appear to be about?
        subject = [name for name in ENTITIES
                   if re.search(rf"\b{name}", block, re.I)]
        rows.append({
            "file": f"{path.parent.name}/{path.name}",
            "n": i + 1,
            "linked": linked,
            "names": ", ".join(subject[:4]) or "-",
        })

dead = [r for r in rows if not r["linked"]]
live = [r for r in rows if r["linked"]]

print(f"{len(rows)} tables across {len({r['file'] for r in rows})} files: "
      f"{len(live)} link somewhere, {len(dead)} are dead ends\n")

print("DEAD ENDS — rows that name something you cannot click through to")
print(f"  {'file':<34} {'#':>2}  names")
for r in sorted(dead, key=lambda r: r["file"]):
    print(f"  {r['file']:<34} {r['n']:>2}  {r['names']}")

print("\nALREADY LINKED")
for r in sorted(live, key=lambda r: r["file"]):
    print(f"  {r['file']:<34} {r['n']:>2}  {r['names']}")

sys.exit(0)
