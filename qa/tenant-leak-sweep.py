"""A brand-new pharmacy must see nothing, on every endpoint there is.

`tenant-isolation.py` proves the session filter works on ordinary model
queries. It did not catch the leak that actually happened.

The navigation badges were counted with `query.with_entities(func.count())` — a
bare count naming no column, which takes the entity out of the statement, and
the tenancy filter attaches to entities. So the badges came back unscoped: a
pharmacy created five minutes earlier, with no patients and no sales, showed
three hundred and fourteen repeats due and two hundred and sixty-eight claims,
every one of them another pharmacy's. Nothing errored. The sidebar simply
reported somebody else's work as this shop's own.

The lesson is that a filter applied by machinery still has edges, and the edges
are where somebody writes a query in a slightly unusual way. So this does not
test the machinery — it tests the outcome, across every GET endpoint the
application exposes, from the point of view of a tenant that owns nothing. Any
number it comes back with is somebody else's.

    python qa/tenant-leak-sweep.py            # against a running server
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("RX5000_API", "http://127.0.0.1:8177")
OWNER = ("admin", "admin123")

#: Endpoints that legitimately answer the same for everybody: the shared
#: reference books, and the platform's own health. Listed rather than guessed,
#: so adding one is a decision somebody makes on purpose.
SHARED = (
    # The platform's own answers, and the reference books every pharmacy shares.
    # Listed rather than guessed, so adding one is a decision somebody makes on
    # purpose and can be argued with in review.
    "/api/health", "/api/jurisdiction", "/api/version", "/api/openapi.json",
    "/api/claiming/diagnoses", "/api/claiming/diagnoses/chapters",
    "/api/claiming/fee-models", "/api/claiming/formularies",
    "/api/claiming/pay-offices", "/api/claiming/schemes/calendar",
    "/api/clinical-terms", "/api/dosage/abbreviations",
    "/api/medical-aids", "/api/gateway/funders", "/api/gateway/tariffs",
    # A catalogue of error codes and of guarded actions — definitions, not data.
    "/api/gateway/errors", "/api/step-up/actions",
    # Segment *definitions*; their sizes are counted per pharmacy.
    "/api/marketing/segments",
    "/api/settings", "/api/currency", "/api/formularies",
    "/api/remittances/reasons/vocabulary", "/api/dispensing/policy",
    # About the person asking, or their own pharmacy — the correct answer to a
    # tenant is its own row, not nothing.
    "/api/auth/me", "/api/auth/pin", "/api/auth/users", "/api/auth/demo/length",
    "/api/profile", "/api/branches", "/api/scorecard", "/api/pharmacies",
    "/api/crm/reports/by-owner",
    # Empty period buckets: twelve months of zeros is a shape, not a leak.
    "/api/crm/reports/forecast",
)



#: Parameters an endpoint hands back with its answer, rather than data.
ECHOED = {"days", "hours", "limit", "per_page", "page", "window",
          "seconds_left", "horizon", "within_days"}


def call(path, token=None, method="GET", body=None):
    req = urllib.request.Request(API + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, None
    except Exception:
        return None, None


def sized(payload):
    """How much this endpoint returned, for something that owns nothing."""
    if payload is None:
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("items", "queue", "lines", "rows", "results", "schemes",
                    "branches", "entries", "messages"):
            if isinstance(payload.get(key), list):
                return len(payload[key])
        # A bare mapping of counts — which is exactly what the nav badges are.
        # A mapping of figures — the navigation badges are exactly this. Only
        # non-zero values count: a pharmacy that owns nothing should produce
        # nothing, and every number here is somebody else's work.
        #
        # Except the parameters an endpoint echoes back. `{"days": 30}` beside
        # four zeros is the window that was asked for, not thirty of anything,
        # and counting it made two honest endpoints look like leaks — which is
        # how a check like this gets ignored.
        if payload and all(isinstance(v, (int, float, type(None)))
                           for v in payload.values()):
            return sum(1 for k, v in payload.items()
                       if v and k not in ECHOED)
    return 0


status, tok = call("/api/auth/login", method="POST",
                   body={"username": OWNER[0], "password": OWNER[1]})
if status != 200:
    sys.exit(f"could not sign in as the platform owner: {status}")
owner = tok["access_token"]

# A pharmacy that has never traded.
#
# One fixture, reused, rather than a fresh one per run. The first version
# stamped the name with the clock and left a tenant behind every time it ran —
# which on a real deployment is litter that accumulates in the one list a
# platform owner reads to see who their customers are.
FIXTURE = "Leak Sweep (test fixture)"
FIXTURE_USER = "leak.sweep.fixture"
FIXTURE_PASS = "leaksweep123"

status, existing = call("/api/pharmacies", owner)
already = any(p["name"] == FIXTURE for p in (existing or {}).get("items", []))

if not already:
    status, made = call("/api/pharmacies", owner, "POST", {
        "name": FIXTURE,
        "admin_username": FIXTURE_USER,
        "admin_password": FIXTURE_PASS,
        "admin_name": "Leak Sweep",
    })
    if status != 200:
        sys.exit(f"could not create the empty pharmacy: {status} {made}")

status, tok = call("/api/auth/login", method="POST",
                   body={"username": FIXTURE_USER, "password": FIXTURE_PASS})
if status != 200:
    sys.exit(f"could not sign in as the empty pharmacy: {status}")
empty = tok["access_token"]

status, spec = call("/openapi.json")
paths = [p for p in (spec or {}).get("paths", {})
         if "get" in spec["paths"][p] and "{" not in p]

leaks, checked = [], 0
for path in sorted(paths):
    if path in SHARED:
        continue
    status, payload = call(path, empty)
    if status != 200:
        continue                      # a refusal is not a leak
    checked += 1
    n = sized(payload)
    if n:
        leaks.append((path, n))

print(f"{checked} endpoints asked, as a pharmacy that owns nothing\n")
if leaks:
    print(f"{len(leaks)} LEAKING — every row below belongs to another pharmacy:")
    for path, n in leaks:
        print(f"  FAIL {path:<52} {n}")
else:
    print("  ok   every one of them came back empty")

# Its own branch is the one thing it legitimately has.
status, own = call("/api/branches", empty)
print(f"\n  {'ok  ' if sized(own) == 1 else 'FAIL'} it can see its own branch "
      f"({sized(own)})")

sys.exit(1 if leaks else 0)
