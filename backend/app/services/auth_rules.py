"""What counts as an acceptable password.

Kept in one place because it is checked in three: creating a user, an
administrator resetting somebody, and a person resetting themselves with their
PIN. Three copies of a rule is two chances for them to disagree, and the one
that disagrees is always the path nobody tested.

The rules are deliberately short. Length does most of the work, and a policy
that demands a symbol and a digit produces `Pharmacy1!` on every till in the
country. What is refused here are the passwords that are actually guessed
first: the product's own name, the words on the login screen, and anything
short.
"""
from __future__ import annotations

MIN_LENGTH = 8

#: Guessed before anything else, so refused outright.
_OBVIOUS = {
    "password", "passw0rd", "12345678", "123456789", "qwertyui", "letmein",
    "rx5000", "rx3000", "pharmacy", "dispensary", "admin123", "changeme",
}


def password_problem(password: str) -> str | None:
    """The reason this password is refused, or None if it is fine."""
    value = (password or "").strip()
    if len(value) < MIN_LENGTH:
        return f"A password needs at least {MIN_LENGTH} characters."
    if value.lower() in _OBVIOUS:
        return "That password is one of the first anybody tries. Please choose another."
    if value.isdigit():
        return "A password of only digits is a PIN. Please include some letters."
    return None
