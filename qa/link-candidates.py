"""Find table cells that name a record and could open it.

Not "which tables have no links" — that was the last sweep, and it is too coarse
to act on. This finds the individual `<td>` that prints a patient's name, a
medicine, an rx number or a supplier, and reports whether an id for that thing
is in scope on the same row. Those are the edits worth making; a cell printing a
date or a quantity is not one.
"""
import pathlib
import re
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"

#: What names a record, and the id field that would open it.
SIGNALS = [
    ("patient",      r"patient_name|\.patient\b|patient\}", r"patient_id"),
    ("product",      r"product_name|\.product\b|product\}", r"product_id"),
    ("prescription", r"rx_number|\.rx\b",                    r"prescription_id|rx_id|\.rx\.id"),
    ("sale",         r"sale_number",                         r"sale_id"),
    ("supplier",     r"supplier_name|\.supplier\b",          r"supplier_id"),
    ("claim",        r"claim_number",                        r"claim_id|\.claim\.id"),
    ("batch",        r"batch_number",                        r"batch_id"),
    ("staff",        r"dispensed_by|cashier|user_name|\.user\b", r"user_id|cashier_id|dispensed_by_id"),
    ("prescriber",   r"doctor_name|\.doctor\b|prescriber",    r"doctor_id|prescriber_id"),
    ("order",        r"order_number",                         r"order_id"),
    ("invoice",      r"invoice_number",                       r"invoice_id"),
]

CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def cells(text):
    for m in CELL.finditer(text):
        yield m.start(), m.group(1)


found = []
for path in sorted(SRC.glob("pages/*.tsx")) + sorted(SRC.glob("components/*.tsx")):
    text = path.read_text(encoding="utf-8", errors="replace")
    if "<td" not in text:
        continue
    line_at = [0]
    for ch in text:
        line_at.append(line_at[-1] + (1 if ch == "\n" else 0))

    for pos, body in cells(text):
        if "EntityLink" in body or "<Link" in body:
            continue          # already opens something
        for kind, names, ids in SIGNALS:
            if not re.search(names, body):
                continue
            # Is an id for it anywhere in the file? Crude, but a false positive
            # here costs a glance and a false negative costs a dead end.
            has_id = bool(re.search(ids, text))
            found.append((f"{path.parent.name}/{path.name}", line_at[pos] + 1,
                          kind, has_id, " ".join(body.split())[:64]))
            break

with_id = [f for f in found if f[3]]
without = [f for f in found if not f[3]]

print(f"{len(found)} cells name a record and do not open it "
      f"({len(with_id)} have an id in the file, {len(without)} do not)\n")

by_file = {}
for file, line, kind, has_id, snippet in with_id:
    by_file.setdefault(file, []).append((line, kind, snippet))

for file in sorted(by_file, key=lambda f: -len(by_file[f])):
    rows = by_file[file]
    print(f"{file}  ({len(rows)})")
    for line, kind, snippet in rows:
        print(f"    {line:>5}  {kind:<12} {snippet}")

if without:
    print(f"\nNo id in the file — these need the API to return one first:")
    for file, line, kind, has_id, snippet in without:
        print(f"    {file}:{line}  {kind:<12} {snippet}")
sys.exit(0)
