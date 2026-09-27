# -*- coding: utf-8 -*-
"""Every request the screen makes is told what to do when it fails.

THE FAULT.

    api.get<Patient[]>(`/api/patients?q=${q}&limit=6`).then(setPatients);

No `.catch`. So when that request failed the browser logged an unhandled
rejection nobody was looking at, `patients` stayed `[]`, and the screen rendered
what it renders for an empty list:

    Nobody on file matches "Chido".      [ Add them ]

The dispenser adds them. The patient now has two records, and the allergy on the
first one is not on the screen the next dispenser reads. The same six lines
appeared on seven screens; three of them had no `.catch` at all.

It was not only search boxes. The reads with no `.catch` included the patient's
own record (three tabs of clinical history that each said "nothing on file"),
the fiscal register, what the ledger has not posted, the till's list of sales
awaiting payment, and the dose check. In every case the screen had a confident
sentence ready for an empty answer, and used it for a question that was never
asked.

WHAT THIS GUARD CHECKS.

One thing, mechanically: a `.then` with no `.catch` on the same chain. A promise
chain that rejects into nothing is never a decision anybody made. `.finally`
does not count — three sites had one, and all it did was turn the skeleton off
so the lie showed sooner.

It started as `api.*` only, and six chains walked straight past it: the
abbreviation book the dispensary's directions expand through (without it "1 t
od" stays "1 t od" on a label a patient reads at home), two file reads where an
empty box looks like an empty file, the printer probe, the pharmacy's own
letterhead and the portal preview's brand. None of them is called `api.get`, and
every one of them is a read that can fail.

WHAT IT DOES NOT CHECK.

Whether the `.catch` says anything useful. `catch(() => setRows([]))` passes
here and is still the fault above, wearing a coat. That judgement belongs to the
person writing the screen, and the test to apply is:

    if this list comes up empty, what does my screen tell somebody,
    and is it true when the question was never asked?

Where the answer is a confident sentence, the screen needs a second state. The
pattern the product settled on is a `somethingUnknown` flag beside the data,
named in the field's own words, per `never-a-dash-for-missing-data`.

THREE EXEMPTIONS, ALL EARNED.

`Promise.all([...])` — a rejection inside the array propagates to the outer
chain, so the `.catch` belongs there and the guard looks for it there.

`await` in a `try` — the `catch` block is the handler. This guard only looks at
`.then` chains.

`RETURNED` — a `.then` chain a function hands back to its caller, where the
caller is what decides. Four sites: `offline/db.ts` builds one promise per
IndexedDB request and `Doing.tsx` stores the job's `run` and catches at the
place it is started. Each is listed by name below with the reason, so the
exemption is a decision on the record rather than a pattern in a regex.

HOW IT WAS PROVED.

Run with `--plant`: it puts an uncaught `api.get(...).then(...)` into a real
page, checks that this guard names that file and line, and puts the page back.
My first version of this scan was fooled by a semicolon inside a `//` comment
and cleared a file that had the fault, so comments and strings are stripped
before anything is counted.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

CALL = re.compile(r"\b([A-Za-z_$][\w$.]*)\s*\(")

# Words that look like a call and are not one.
KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof",
    "await", "new", "delete", "void", "in", "of", "do", "else", "case",
}

# A `.then` chain handed back to whoever called the function, which is where the
# decision belongs. Keyed by file and the name of the call, with the reason.
RETURNED = {
    ("offline/db.ts", "open"):
        "one promise per IndexedDB request; `run` and its callers catch",
    ("offline/db.ts", "request"):
        "the same, one level down",
    ("components/Doing.tsx", "run"):
        "the job's own work, stored on the job; Doing.tsx:107 catches it and "
        "puts the job into its failed state",
    ("components/AssistantDiagram.tsx", "import"):
        "the lazy mermaid import, kept in `mermaidReady`; the render at :53 "
        "catches and the component says the diagram could not be drawn",
    ("components/AssistantDiagram.tsx", "mermaid"):
        "the same promise, read by the render that catches it",
}


def blanked(src: str) -> str:
    """Comments and string bodies replaced by spaces, offsets preserved.

    Offsets have to survive so a line number reported from the blanked text is
    the line number in the file. A semicolon in a comment ended a chain early in
    the first version of this and let a real fault through.
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == "//":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if two == "/*":
            while i < n and src[i:i + 2] != "*/":
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            for j in range(i, min(i + 2, n)):
                out[j] = " "
            i += 2
            continue
        if c in "\"'`":
            quote, i = c, i + 1
            while i < n:
                if src[i] == "\\":
                    out[i] = " "
                    if i + 1 < n:
                        out[i + 1] = " "
                    i += 2
                    continue
                if src[i] == quote:
                    out[i] = " "
                    i += 1
                    break
                # A template's ${...} holds real code, including its own calls,
                # so it is left alone. Only the literal text around it goes.
                if quote == "`" and src[i:i + 2] == "${":
                    depth = 0
                    while i < n:
                        if src[i] == "{":
                            depth += 1
                        elif src[i] == "}":
                            depth -= 1
                            if depth == 0:
                                i += 1
                                break
                        i += 1
                    continue
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            out[i - 1 if i <= n else n - 1] = " "
            continue
        i += 1
    return "".join(out)


def chain_from(text: str, start: int) -> str:
    """The expression from `start` to the end of its statement."""
    i, depth, end = start, 0, len(text)
    while i < end:
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                break
        elif c == ";" and depth == 0:
            break
        i += 1
    return text[start:i]


def promise_all_around(text: str, at: int) -> str | None:
    """The enclosing `Promise.all(...)` chain, if the call sits inside one."""
    head = text[:at]
    for m in reversed(list(re.finditer(r"\bPromise\.(?:all|allSettled)\s*\(", head))):
        chain = chain_from(text, m.start())
        if m.start() + len(chain) > at:
            return chain
    return None


def offenders() -> list[tuple[pathlib.Path, int, str]]:
    found, seen = [], set()
    for path in sorted(SRC.rglob("*.ts")) + sorted(SRC.rglob("*.tsx")):
        raw = path.read_text(encoding="utf-8")
        text = blanked(raw)
        rel = path.relative_to(SRC).as_posix()
        for m in CALL.finditer(text):
            name = m.group(1)
            if name in KEYWORDS or (rel, name.split(".")[-1]) in RETURNED:
                continue
            chain = chain_from(text, m.start())
            at = chain.find(".then(")
            if at < 0 or ".catch(" in chain:
                continue
            # The `.then` has to hang off THIS call rather than off something
            # nested inside its arguments, or every outer call in a chain of
            # three reports the same fault three times.
            if chain[:at].count("(") != chain[:at].count(")"):
                continue
            line = raw[:m.start()].count("\n") + 1
            if (path, line) in seen:
                continue
            seen.add((path, line))
            found.append((path, line, name))
    return found


def report(found) -> int:
    if not found:
        print(f"ok  every .then chain has a .catch "
              f"({len(list(SRC.rglob('*.ts*')))} files, "
              f"{len(RETURNED)} named exemptions)")
        return 0
    print(f"FAIL  {len(found)} request(s) with nothing to do when they fail:")
    for path, line, name in found:
        print(f"  {path.relative_to(ROOT)}:{line}  {name}(...)")
    print()
    print("  A .then with no .catch rejects into nothing. Add one, and then ask")
    print("  what the screen says when the list is empty — if it is a confident")
    print("  sentence, the screen needs to know the difference between nought")
    print("  and not asked.")
    return 1


def plant() -> int:
    """Prove the guard by putting the fault back."""
    victim = SRC / "pages" / "Stock.tsx"
    original = victim.read_text(encoding="utf-8")
    anchor = "  useEffect(load, [q, lowOnly]);"
    assert original.count(anchor) == 1, "anchor moved; pick another line"
    fault = anchor + '\n  // planted\n  useEffect(() => { api.get("/api/suppliers").then(() => 0); }, []);'
    try:
        victim.write_text(original.replace(anchor, fault), encoding="utf-8")
        found = offenders()
        hit = [row for row in found if row[0] == victim]
        if not hit:
            print("FAIL  the guard did not see a planted uncaught read")
            return 1
        print(f"ok  planted fault caught at {victim.name}:{hit[0][1]}")
        return 0
    finally:
        victim.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(plant() if "--plant" in sys.argv else report(offenders()))
