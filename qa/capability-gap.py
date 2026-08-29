"""Where the backend can do more than the front end ever asks for.

The part-payment modal offered three words — Cash, Card, Mobile money — while
the endpoint behind it accepted a list of tenders, each with its own currency
and reference, and the till already had the wallet list to fill them in. The
gap was invisible from either side: the API worked, the screen worked, and the
record it produced could not be reconciled.

That is not a one-off shape. It happens whenever a schema grows and the screen
that feeds it does not, and nothing fails when it does — the request is valid,
the defaults apply, and the capability quietly goes unused.

So this compares the two directly. For every request body the API accepts, it
reads the fields the schema declares and then looks for each one in the code
that calls that path. Fields the front end never mentions are reported.

It is a lead generator, not a verdict. Some fields genuinely belong to another
caller — the device agent, the portal, a test — and some are server-side
defaults nobody should send. The point is to put the list in front of somebody
rather than wait for a pharmacist to find the gap at a counter.

    python qa/capability-gap.py
"""
import json
import pathlib
import re
import sys
import urllib.request

API = "http://127.0.0.1:8177"
FRONTEND = pathlib.Path(__file__).resolve().parents[1]/"frontend"/"src"

#: Fields the server fills in, or that belong to a caller that is not a screen.
IGNORE = {
    "id", "created_at", "updated_at", "pharmacy_id", "branch_id",
    "step_up_token", "idempotency_key", "csrf",
}


def spec():
    with urllib.request.urlopen(f"{API}/openapi.json", timeout=60) as r:
        return json.load(r)


def body_fields(doc, op) -> set[str]:
    """The field names one request body declares, following $ref."""
    body = (op.get("requestBody") or {}).get("content", {})
    schema = (body.get("application/json") or {}).get("schema") or {}
    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        schema = doc["components"]["schemas"].get(name, {})
    return set(schema.get("properties", {}) or {})


def callers(path: str) -> list[pathlib.Path]:
    """Which front-end files call this path.

    Matched on the literal stem before any parameter, because the front end
    writes them as templates: `/api/pos/sales/${id}/pay`.
    """
    stem = re.split(r"\{", path)[0].rstrip("/")
    if len(stem) < 8:
        return []
    out = []
    for f in FRONTEND.rglob("*.tsx"):
        if stem in f.read_text(encoding="utf-8", errors="ignore"):
            out.append(f)
    for f in FRONTEND.rglob("*.ts"):
        if stem in f.read_text(encoding="utf-8", errors="ignore"):
            out.append(f)
    return out


doc = spec()
findings = []
for path, ops in sorted(doc["paths"].items()):
    for verb in ("post", "put", "patch"):
        op = ops.get(verb)
        if not op:
            continue
        fields = body_fields(doc, op) - IGNORE
        if len(fields) < 3:
            continue                      # too small a schema to be a gap
        files = callers(path)
        if not files:
            continue                      # no screen calls it at all
        text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in files)
        # A path the front end only ever reads is a different thing from a form
        # that sends less than it could. Both are worth knowing, but only one of
        # them is a screen throwing capability away — the other is an endpoint
        # fed by some other flow entirely, like a goods receipt raising the
        # supplier invoice.
        stem = re.split(r"\{", path)[0].rstrip("/")
        if not re.search(r"api\.(post|put|patch)[^\n]{0,90}" + re.escape(stem), text):
            continue
        missing = sorted(f for f in fields if f not in text)
        if missing and len(missing) >= 2:
            findings.append((verb.upper(), path, sorted(fields), missing,
                             sorted({f.name for f in files})))

findings.sort(key=lambda r: -len(r[3]))
print(f"{len(findings)} endpoints where the screen sends less than the schema offers\n")
for verb, path, fields, missing, files in findings[:24]:
    print(f"  {verb:<5} {path}")
    print(f"        called from : {', '.join(files[:3])}")
    print(f"        never sent  : {', '.join(missing[:10])}"
          + (f" … +{len(missing)-10}" if len(missing) > 10 else ""))
    print(f"        of {len(fields)} fields the endpoint accepts")
    print()
sys.exit(0)
