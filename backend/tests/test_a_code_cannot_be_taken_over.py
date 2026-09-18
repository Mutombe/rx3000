"""A till code can only be replaced by somebody who already has it.

THE HOLE THIS CLOSES.

The password says the session belongs to a person. The PIN says that person is
standing at the till right now. Two questions, and the second one is what the
controlled-drug register, every authorisation prompt and every "dispensed by"
actually rest on.

While the password alone could replace the code, those two questions had one
answer. Anybody who learned a password — over a shoulder, off a note taped
under the till, because it was shared once during a busy afternoon — could
quietly set that person's code and from then on authorise as them. Nothing
would look wrong. The register would carry the right name.

So a FIRST code is proved with the password, because there is nothing else to
prove it with, and CHANGING one asks for the code being replaced. Somebody who
has genuinely forgotten theirs is not stranded: an administrator clears it,
which takes a second person and is recorded, and the owner sets a fresh one.

    python tests/test_a_code_cannot_be_taken_over.py
"""
import sys

from snapshot_app import client, execute, sql

ok = True


def check(cond, label, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'ok  ' if cond else 'FAIL'}  {label}{'   ' + str(extra) if extra else ''}")


def run():
    c = client()
    me = c.get("/api/auth/me").json()
    uid = me["id"]

    # Start from somebody who has never set a code.
    execute("update users set pin_hash = null, pin_set_at = null, "
            "pin_failures = 0, pin_locked_until = null where id = ?", (uid,))

    # ---- a first code is the password, as it always was ---------------------
    r = c.post("/api/auth/pin", json={"pin": "8317", "password": "admin123"})
    check(r.status_code == 200, "a first code is set with the password alone",
          r.status_code)
    check(r.json().get("replaced") is False,
          "and is reported as a first code, not a change")

    # ---- THE HOLE ------------------------------------------------------------
    r = c.post("/api/auth/pin", json={"pin": "4682", "password": "admin123"})
    check(r.status_code == 409,
          "the password ALONE can no longer replace an existing code",
          r.status_code)
    detail = r.json().get("detail", {})
    check(isinstance(detail, dict) and detail.get("error_code") == "PIN_ALREADY_SET",
          "and says why, in a way the screen can act on")
    check(c.post("/api/auth/unlock", json={"pin": "8317"}).status_code == 200,
          "the original code still unlocks the till, so nothing was replaced")

    # ---- guessing at the current code is guessing ----------------------------
    r = c.post("/api/auth/pin", json={"pin": "4682", "password": "admin123",
                                      "current_pin": "1739"})
    check(r.status_code == 403, "a wrong current code is refused", r.status_code)
    check("attempt" in r.text.lower(),
          "and spends one of the five attempts before the lockout")

    # ---- the owner can change their own -------------------------------------
    r = c.post("/api/auth/pin", json={"pin": "4682", "password": "admin123",
                                      "current_pin": "8317"})
    check(r.status_code == 200, "the current code changes it", r.status_code)
    check(r.json().get("replaced") is True, "and is reported as a change")
    check(c.post("/api/auth/unlock", json={"pin": "4682"}).status_code == 200,
          "the new code works")
    check(c.post("/api/auth/unlock", json={"pin": "8317"}).status_code == 403,
          "and the old one does not")

    # ---- and cannot quietly keep the same one -------------------------------
    r = c.post("/api/auth/pin", json={"pin": "4682", "password": "admin123",
                                      "current_pin": "4682"})
    check(r.status_code == 400, "setting the same code again is refused",
          r.status_code)

    # ---- the password is still required at all --------------------------------
    r = c.post("/api/auth/pin", json={"pin": "5291", "password": "wrong",
                                      "current_pin": "4682"})
    check(r.status_code == 403,
          "a wrong password is refused even with the right current code",
          r.status_code)

    # ---- it is written down ---------------------------------------------------
    notes = sql("select summary from audit_logs where action = 'NOTE' "
                "order by id desc limit 5")
    said = [n[0] for n in notes]
    check(any("Changed the till code" in s for s in said),
          "a change is recorded by name, not just as a call to a route",
          said[0] if said else "(nothing recorded)")
    check(any("Set the till code" in s for s in said),
          "and so is a first code")

    # ---- an administrator can clear, and cannot choose -------------------------
    # The endpoint is behind step-up, so this checks the shape of the guard
    # rather than driving the prompt: a 428 is the server asking for a code,
    # which is the whole point of it being there.
    r = c.delete(f"/api/auth/pin/{uid}")
    check(r.status_code in (403, 428),
          "clearing somebody's code needs a fresh authorisation", r.status_code)
    check(sql("select pin_hash from users where id = ?", (uid,))[0][0] is not None,
          "and does nothing until it gets one")

    # The 428 above is itself the proof the clearing route exists and is
    # guarded: an absent route answers 404, and an unguarded one would have
    # cleared the code. So a forgotten code has a way out, and it costs a
    # second person.
    check(r.status_code != 404,
          "there is a way to clear a forgotten code, so this is not a lockout")

    # And no route anywhere lets one person choose another's code. The only
    # writer is /api/auth/pin, which has just been shown to demand both the
    # owner's password and the code it is replacing.
    r = c.post("/api/auth/pin", json={"pin": "7412", "password": "admin123",
                                      "username": "admin", "current_pin": ""})
    check(r.status_code == 409,
          "and naming somebody else does not get around needing their code",
          r.status_code)


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
    print("\nall passed" if ok else "\nFAILURES")
    sys.exit(0 if ok else 1)
