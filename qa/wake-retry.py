"""Does a read ride out a sleeping server, and does a write refuse to?

The API is on a host that stops the service after fifteen minutes of quiet.
Waking takes the better part of a minute and every request during it fails, so
the first thing a pharmacy does each morning produced a screenful of "could not
reach the server" — the software looking broken at exactly the moment somebody
is deciding whether to trust it.

Reads are retried through that. The half of this that matters more is that
WRITES ARE NOT.

A retried read costs a few hundred milliseconds. A retried write is a second
payment taken, a second script dispensed, a second stock adjustment. And the
till cannot tell "the request never arrived" from "the request arrived, was
processed, and the answer was lost coming back" — those are identical from the
client and only one of them is safe to repeat.

So this asserts both directions, and the second is the one worth having:

  1. A GET that fails and then succeeds returns the answer, with no error.
  2. A POST that fails is attempted exactly once, whatever the failure.

Checked by reading the code rather than by running a browser: the rule is one
condition, and what it must say is that `method === "GET"` gates every retry.

    python qa/wake-retry.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "frontend" / "src" / "api.ts"

failures: list[str] = []


def check(ok: bool, said: str, why: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {said}")
    if not ok:
        failures.append(why or said)


def main() -> int:
    src = API.read_text(encoding="utf-8")
    # Comments discuss the rule; they do not implement it.
    code = re.sub(r'/\*.*?\*/', "", src, flags=re.S)
    code = re.sub(r'^\s*//.*$', "", code, flags=re.M)

    retries = list(re.finditer(r'return request<T>\(method, path, body, stepUp,\s*attempt \+ 1\)',
                               code))
    check(bool(retries),
          f"the request function retries at all ({len(retries)} place(s))",
          "nothing retries, so a cold start is still reported as a failure")

    # Every retry must sit behind a GET test.
    for hit in retries:
        window = code[max(0, hit.start() - 400):hit.start()]
        guarded = 'method === "GET"' in window
        line = code.count("\n", 0, hit.start()) + 1
        check(guarded,
              f"the retry at line {line} is behind a GET test",
              f"api.ts:{line} retries without checking the method. A retried "
              f"POST is a second payment taken, a second script dispensed, or "
              f"a second stock adjustment — and the client cannot tell a "
              f"request that never arrived from one whose answer was lost on "
              f"the way back")

    # And a retry has to end.
    check("WAKE_ATTEMPTS" in code and "attempt <" in code,
          "the retries are capped, so a server that is down is reported "
          "rather than waited on forever",
          "no attempt cap: a genuinely dead server would hang the screen")

    # 500 is the application answering badly; retrying only delays the message.
    waking = re.search(r'function stillWaking\([^)]*\)[^{]*\{([^}]*)\}', code)
    check(waking is not None, "the retryable statuses are stated in one place",
          "could not find stillWaking()")
    if waking:
        body = waking.group(1)
        for status in ("502", "503", "504"):
            check(status in body, f"    {status} counts as still waking",
                  f"{status} is not treated as a server still starting up")
        check("500" not in body,
              "    500 does not, because that is the application answering",
              "500 is retried. That is the application replying badly and it "
              "will reply badly again; retrying only delays the message")

    print()
    if failures:
        for f in failures:
            print(f"  {f}\n")
        return 1
    print("a read waits for the server to wake; a write is attempted once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
