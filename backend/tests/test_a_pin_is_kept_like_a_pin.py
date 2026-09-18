"""A four digit code is kept the way a four digit code should be kept.

The PIN used to be hashed exactly like a password: PBKDF2 at 200,000 rounds.
That is the right thing to do to a password and the wrong thing to do to four
digits. Ten thousand combinations does not become unsearchable because each
guess costs 150ms — it becomes twenty minutes of one core, and seconds on a
GPU — so the work factor was defending nothing while being paid for by every
dispenser unlocking a till.

It is now mixed with the application secret before it is stretched, which is
the thing that actually helps: a stolen database cannot be attacked at all
without the deployment's own key. This pins that down, because "we made the
login faster" is the sentence that precedes most authentication holes.

    python tests/test_a_pin_is_kept_like_a_pin.py
"""
import sys
import time

sys.path.insert(0, ".")

from app.auth import hash_password                         # noqa: E402
from app.config import settings                            # noqa: E402
from app.services import pins                              # noqa: E402

ok = True


def check(cond, label, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'ok  ' if cond else 'FAIL'}  {label}{'   ' + extra if extra else ''}")


def run():
    stored = pins.hash_pin("8317")
    check(stored.startswith("pin2$"), "a code is stored in the current format")
    check(len(stored) <= 255, "and fits the column it lives in",
          f"{len(stored)} of 255")

    check(pins.verify_pin("8317", stored) == (True, False),
          "the right code verifies and needs no rewrite")
    check(pins.verify_pin("8318", stored)[0] is False, "a wrong code does not")
    check(pins.verify_pin("", stored)[0] is False, "nor an empty one")
    check(pins.verify_pin("8317", "")[0] is False, "nor anything, against no code")
    check(pins.verify_pin("8317", "rubbish")[0] is False,
          "and a damaged record refuses rather than raising")

    # Two people with the same code must not share a hash, or the database
    # tells whoever reads it which accounts to try first.
    check(pins.hash_pin("8317") != pins.hash_pin("8317"),
          "the same code hashes differently each time it is set")

    # THE WHOLE POINT. Without the application secret the stored value is not
    # attackable, which is what makes four digits defensible at all.
    real = settings.SECRET_KEY
    try:
        settings.SECRET_KEY = "somebody who has only the database"
        check(pins.verify_pin("8317", stored)[0] is False,
              "the stored code does NOT verify without the application secret")
    finally:
        settings.SECRET_KEY = real
    check(pins.verify_pin("8317", stored)[0] is True, "and verifies again with it")

    # Codes set before this existed still work, and ask to be rewritten now
    # that the one thing the database cannot supply is in hand.
    legacy = hash_password("8317")
    check(pins.verify_pin("8317", legacy) == (True, True),
          "a code from before this verifies, and asks to be rewritten")
    check(pins.verify_pin("9999", legacy)[0] is False,
          "and an old record still refuses a wrong code")

    # It has to be quick, because that is why any of this was touched.
    t = time.perf_counter()
    for _ in range(10):
        pins.verify_pin("8317", stored)
    each = (time.perf_counter() - t) * 100
    check(each < 40, "and a check is quick enough to wait for", f"{each:.1f} ms each")

    # The rules that do the real work are untouched.
    refused = 0
    for weak in ("1234", "0000", "1111", "4321", "2222", "0123"):
        try:
            pins.validate(weak)
        except pins.PinError:
            refused += 1
    check(refused == 6, "guessable codes are still refused", f"{refused} of 6")
    for bad in ("12", "", "abcd", "123456"):
        try:
            pins.validate(bad)
            check(False, f"'{bad}' should not be accepted")
        except pins.PinError:
            pass
    check(True, "and so is anything that is not four digits")
    check(pins.validate(" 8317 ") == "8317", "a code is taken without its spaces")

    # The lockout is the control that actually stops online guessing, so it has
    # to survive a change made for speed.
    check(pins.MAX_FAILURES == 5 and pins.LOCKOUT.total_seconds() == 600,
          "and the lockout is still five tries, then ten minutes")


if __name__ == "__main__":
    run()
    print("\nall passed" if ok else "\nFAILURES")
    sys.exit(0 if ok else 1)
