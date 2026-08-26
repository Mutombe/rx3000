"""The contract every switch adapter must satisfy before it carries live claims.

The point of this module is to make finishing an integration a *checkable* job
rather than a judgement call. When Health 263 or Mediswitch publish their
specification, someone writes one adapter class — and then runs this. If it
passes, the adapter honours every promise the gateway makes to its callers. If
it does not, the report names which promise was broken.

Why this is worth having rather than trusting a careful implementer: the failure
mode of a claims integration is silent. An adapter that returns an approval for
a rejected claim, or swallows a suspended member into a generic error, does not
crash — it pays out wrong and nobody notices until reconciliation, weeks later.
These are the invariants that stop that.

Run it against the simulator to prove the harness itself is honest:

    python -m app.services.switch_conformance SIMULATOR
"""
from dataclasses import dataclass

from .gateway import ADAPTERS, GatewayError, SwitchResult

# A claim the adapter should be able to answer, and a member the funder should
# report as suspended. Both are shaped exactly as the router passes them on.
SAMPLE_CLAIM = {
    "transaction_header": {"source_system": "CONFORMANCE", "funder_id": "",
                           "switch_destination": ""},
    "provider_details": {"ahfoz_number": "1234567", "practice_type": "Pharmacy",
                         "facility_name": "Conformance Pharmacy"},
    "patient_details": {"policy_number": "5551234", "dependent_code": "00",
                        "first_name": "Test", "last_name": "Member"},
    "clinical_data": {"primary_icd10": "A09", "secondary_icd10": "", "referral_number": ""},
    "claim_lines": [{"line_number": 1, "service_date": "2026-08-09",
                     "tariff_code": "0101", "description": "Consultation",
                     "quantity": 1, "unit_price": 35.00, "total_price": 35.00}],
    "totals": {"currency": "USD", "gross_amount": 35.00},
}
SUSPENDED_POLICY = "5550000"      # the agreed trigger: a policy ending 000
SAMPLE_ELIGIBILITY = {
    "funder_id": "", "switch_id": "",
    "provider": {"ahfoz_number": "1234567"},
    "member": {"policy_number": "987654321", "first_name": "Test", "last_name": "Member"},
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    fatal: bool = False           # a failure that must block go-live


class _StubFunder:
    """Stands in for a Funder row so the harness needs no database."""

    def __init__(self, switch_id: str):
        self.funder_id = "CONFORMANCE_ZW"
        self.name = "Conformance Funder"
        self.switch_id = switch_id
        self.currency_code = "USD"
        self.biometric_required = False
        self.realtime = True
        self.active = True


def _claim(policy: str = "5551234", biometric: dict | None = None) -> dict:
    payload = {k: (dict(v) if isinstance(v, dict) else v) for k, v in SAMPLE_CLAIM.items()}
    payload["patient_details"] = {**SAMPLE_CLAIM["patient_details"], "policy_number": policy}
    payload["claim_lines"] = [dict(line) for line in SAMPLE_CLAIM["claim_lines"]]
    if biometric is not None:
        payload["biometric"] = biometric
    return payload


def run(switch_id: str) -> dict:
    """Check one adapter against the gateway contract. No network, no database."""
    adapter = ADAPTERS.get(switch_id.upper())
    if adapter is None:
        return {"switch_id": switch_id, "ran": False,
                "message": f"No adapter is registered for '{switch_id}'.",
                "checks": [], "passed": 0, "failed": 0, "ready": False}

    funder = _StubFunder(adapter.switch_id)
    checks: list[Check] = []

    def record(name, passed, detail="", fatal=False):
        checks.append(Check(name, passed, detail, fatal))

    # --- 1. it answers at all, or fails in the one way callers can handle ---
    implemented = True
    try:
        result = adapter.claim(_claim(), funder)
    except GatewayError as exc:
        implemented = False
        result = None
        record("an unimplemented adapter says so in the gateway vocabulary",
               exc.code in ("SWITCH_UNAVAILABLE", "SWITCH_TIMEOUT"),
               f"raised {exc.code}", fatal=True)
        record("its message names what is missing",
               len(exc.detail) > 30 and "not implemented" in exc.detail.lower(),
               exc.detail[:70])
    except Exception as exc:                                   # noqa: BLE001
        implemented = False
        result = None
        record("the adapter raises GatewayError, never a bare exception",
               False, f"{type(exc).__name__}: {exc}", fatal=True)

    if not implemented:
        passed = sum(1 for c in checks if c.passed)
        return {
            "switch_id": adapter.switch_id, "ran": True, "implemented": False,
            "ready": False,
            "message": ("This adapter is declared but not implemented. It fails "
                        "cleanly, which is correct, it is simply not usable yet."),
            "checks": [c.__dict__ for c in checks],
            "passed": passed, "failed": len(checks) - passed,
        }

    # --- 2. the shape of a successful adjudication ---
    record("a claim returns a SwitchResult", isinstance(result, SwitchResult),
           type(result).__name__, fatal=True)
    if isinstance(result, SwitchResult):
        record("the adjudication status is one the gateway publishes",
               result.status in ("APPROVED", "PARTIAL", "REJECTED"),
               result.status, fatal=True)
        record("an approved amount never exceeds the amount claimed",
               result.approved <= SAMPLE_CLAIM["totals"]["gross_amount"] + 0.005,
               f"approved {result.approved} of {SAMPLE_CLAIM['totals']['gross_amount']}",
               fatal=True)
        record("an approved amount is never negative", result.approved >= 0,
               str(result.approved), fatal=True)
        record("a switch reference comes back", bool(result.reference),
               result.reference, fatal=True)
        record("a funder reference comes back", bool(result.funder_reference),
               result.funder_reference)
        record("every submitted line is adjudicated",
               len(result.lines) == len(SAMPLE_CLAIM["claim_lines"]),
               f"{len(result.lines)} of {len(SAMPLE_CLAIM['claim_lines'])} lines", fatal=True)
        record("each adjudicated line carries its line number",
               all("line_number" in line for line in result.lines))
        record("the line amounts sum to the approved total",
               abs(sum(float(line.get("approved_amount", 0)) for line in result.lines)
                   - result.approved) < 0.02,
               f"lines {sum(float(l.get('approved_amount', 0)) for l in result.lines)} "
               f"vs total {result.approved}", fatal=True)
        record("a rejection carries a reason",
               result.status != "REJECTED" or bool(result.rejection_reason),
               result.rejection_reason or "n/a")

    # --- 3. the unhappy paths map onto the shared vocabulary ---
    try:
        adapter.claim(_claim(policy=SUSPENDED_POLICY), funder)
        record("a suspended member is refused, not approved", False,
               "the adapter approved a member the funder suspends", fatal=True)
    except GatewayError as exc:
        record("a suspended member is refused, not approved", True, exc.code)
        record("suspension maps to MEMBER_SUSPENDED, not a generic error",
               exc.code == "MEMBER_SUSPENDED", exc.code, fatal=True)
    except Exception as exc:                                   # noqa: BLE001
        record("a suspended member raises GatewayError, not a bare exception",
               False, f"{type(exc).__name__}: {exc}", fatal=True)

    # --- 4. eligibility ---
    try:
        eligibility = adapter.eligibility({**SAMPLE_ELIGIBILITY, "funder_id": funder.funder_id},
                                          funder)
        record("eligibility returns a mapping", isinstance(eligibility, dict),
               type(eligibility).__name__, fatal=True)
        if isinstance(eligibility, dict):
            record("eligibility reports a status", bool(eligibility.get("status")),
                   str(eligibility.get("status")), fatal=True)
            benefits = eligibility.get("benefit_details") or {}
            record("eligibility reports the available balance",
                   "available_balance" in benefits,
                   str(benefits.get("available_balance")), fatal=True)
            record("the balance never exceeds the limit",
                   float(benefits.get("available_balance", 0))
                   <= float(benefits.get("global_limit", 0)) + 0.005,
                   f"{benefits.get('available_balance')} of {benefits.get('global_limit')}")
    except GatewayError as exc:
        record("eligibility answers or fails in the gateway vocabulary",
               exc.code in ("SWITCH_UNAVAILABLE", "SWITCH_TIMEOUT", "MEMBER_SUSPENDED"),
               exc.code)
    except Exception as exc:                                   # noqa: BLE001
        record("eligibility raises GatewayError, not a bare exception", False,
               f"{type(exc).__name__}: {exc}", fatal=True)

    # --- 5. it must not keep what it was told not to keep ---
    template = "Y29uZm9ybWFuY2UtdGVtcGxhdGU="
    try:
        biometric_result = adapter.claim(
            _claim(biometric={"template": template, "format": "TEST",
                              "quality": 90, "finger": "right_index"}), funder)
        leaked = template in repr(biometric_result)
        record("no fingerprint template is echoed back in the result",
               not leaked, "template found in the adapter's result" if leaked else "clean",
               fatal=True)
    except GatewayError:
        record("no fingerprint template is echoed back in the result", True,
               "adapter refused the claim; nothing to leak")

    # --- 6. determinism: the same claim twice must not change the verdict ---
    try:
        again = adapter.claim(_claim(), funder)
        record("the same claim adjudicates the same way twice",
               isinstance(again, SwitchResult) and isinstance(result, SwitchResult)
               and again.status == result.status
               and abs(again.approved - result.approved) < 0.005,
               f"{getattr(result, 'status', '?')} then {getattr(again, 'status', '?')}",
               fatal=True)
    except GatewayError as exc:
        record("the same claim adjudicates the same way twice", False,
               f"second attempt raised {exc.code}", fatal=True)

    passed = sum(1 for c in checks if c.passed)
    fatal_failures = [c for c in checks if not c.passed and c.fatal]
    return {
        "switch_id": adapter.switch_id,
        "ran": True,
        "implemented": True,
        "ready": not fatal_failures,
        "message": ("This adapter honours the gateway contract and is safe to route "
                    "live claims through." if not fatal_failures else
                    f"{len(fatal_failures)} contract violation(s) must be fixed before "
                    "this adapter carries live claims."),
        "checks": [c.__dict__ for c in checks],
        "passed": passed,
        "failed": len(checks) - passed,
        "fatal_failures": [c.name for c in fatal_failures],
    }


def run_all() -> list[dict]:
    return [run(switch_id) for switch_id in sorted(ADAPTERS)]


if __name__ == "__main__":                                     # pragma: no cover
    import sys

    targets = sys.argv[1:] or sorted(ADAPTERS)
    exit_code = 0
    for target in targets:
        report = run(target)
        print(f"\n=== {report['switch_id']} ===")
        for check in report["checks"]:
            flag = "PASS" if check["passed"] else ("FAIL*" if check["fatal"] else "FAIL")
            print(f"{flag:5} {check['name']}  {check['detail']}")
        print(f"-> {report['message']}")
        if report.get("implemented") and not report["ready"]:
            exit_code = 1
    sys.exit(exit_code)
