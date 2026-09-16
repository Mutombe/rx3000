"""Somebody who has never set a code can set one without losing their place.

The prompt is where people find out they have not got a code, and it is also
where the work they would lose by going to look for one is sitting. A pharmacist
walks to a cashier's till to approve something, is asked for a code, and has
never made one — their only route was to log the cashier out, sign in, find
settings, make a code, sign out, sign the cashier back in, and by then the
transaction and the patient are both gone.

So the code is made from the prompt. This is what must stay true of it:

  - the session belongs to one person and the code is set for another, on that
    other person's own password
  - a wrong password sets nothing
  - a name nobody answers to sets nothing
  - the first three codes anybody tries are still refused
  - the code works immediately, for the thing they were in the middle of
  - and it is never a way in: knowing somebody's password is what it costs, so
    it grants no more than signing in as them already would

  python tests/test_a_code_made_on_the_spot.py
"""
import sys

from snapshot_app import client, execute, sql


def run():
    c = client()
    from app.auth import hash_password

    for name, role, full in (("jit_kuda", "cashier", "Kuda at the till"),
                             ("jit_farai", "pharmacist", "Farai the pharmacist")):
        if not sql("select id from users where username = ?", (name,)):
            execute("insert into users (username, password_hash, full_name, role, active, "
                    "pharmacy_id, branch_id) values (?, ?, ?, ?, 1, 1, 1)",
                    (name, hash_password("Their-own-pass-1"), full, role))
    execute("update users set pin_hash = NULL, pin_set_at = NULL, pin_failures = 0, "
            "pin_locked_until = NULL where username = 'jit_farai'")

    # The till is signed in as the cashier. That is the whole situation.
    r = c.post("/api/auth/login", json={"username": "jit_kuda", "password": "Their-own-pass-1"},
               headers={"Authorization": ""})
    assert r.status_code == 200, r.text
    till = {"Authorization": "Bearer " + r.json()["access_token"]}

    # The pharmacist has no code, and the prompt says so rather than guessing.
    asked = c.post("/api/step-up", json={"action": "script.price_set",
                                         "approver": "jit_farai", "pin": "8261"},
                   headers=till)
    assert asked.status_code >= 400, asked.text
    assert "no pin is set" in asked.text.lower(), asked.text
    print("ok    the prompt says there is no code yet, in those words")

    wrong = c.post("/api/auth/pin", json={"username": "jit_farai", "pin": "8261",
                                          "password": "not-their-password"}, headers=till)
    assert wrong.status_code == 403, wrong.text
    assert not sql("select pin_hash from users where username = 'jit_farai'")[0][0]
    print("ok    a wrong password sets nothing")

    nobody = c.post("/api/auth/pin", json={"username": "nobody_at_all", "pin": "8261",
                                           "password": "Their-own-pass-1"}, headers=till)
    assert nobody.status_code == 404, nobody.text
    print("ok    a name nobody answers to sets nothing")

    for guessable in ("1234", "0000", "7777"):
        weak = c.post("/api/auth/pin", json={"username": "jit_farai", "pin": guessable,
                                             "password": "Their-own-pass-1"}, headers=till)
        assert weak.status_code == 400, (guessable, weak.text)
    print("ok    1234, 0000 and four of the same digit are still refused")

    made = c.post("/api/auth/pin", json={"username": "jit_farai", "pin": "8261",
                                         "password": "Their-own-pass-1"}, headers=till)
    assert made.status_code == 200, made.text
    assert made.json()["username"] == "jit_farai", made.json()
    print(f"ok    set from the cashier's till, for {made.json()['full_name']}, "
          f"on their own password")

    # And it works for the thing they were in the middle of, immediately.
    now = c.post("/api/step-up", json={"action": "script.price_set",
                                       "approver": "jit_farai", "pin": "8261",
                                       "context": "Amoxil 500 · 9.00 → 8.00 each"},
                 headers=till)
    assert now.status_code == 200, now.text
    grant = sql("select requested_by_id, approved_by_id, context from step_up_grants "
                "where token = ?", (now.json()["token"],))[0]
    cashier_id = sql("select id from users where username = 'jit_kuda'")[0][0]
    pharm_id = sql("select id from users where username = 'jit_farai'")[0][0]
    assert grant[0] == cashier_id and grant[1] == pharm_id, grant
    assert "Amoxil" in (grant[2] or ""), grant
    print("ok    the code authorises immediately, and names both people and the reason")

    # Never a way in. The code signs one action; it does not open a session.
    signin = c.post("/api/auth/login", json={"username": "jit_farai", "password": "8261"},
                    headers={"Authorization": ""})
    assert signin.status_code >= 400, "a code signed somebody in"
    print("ok    the code is not a password: it signs an action, never a session")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:                  # noqa: BLE001
        import os
        import traceback
        traceback.print_exc()
        print("FAIL", exc)
        sys.stdout.flush()
        os._exit(1)
    print("\nall passed")
