"""What the barcode reader must get right, stated as examples.

These are the cases that cost money when they are wrong, not a sweep for
coverage. Each one is a real shape that comes off a real pack or a real
supplier file, and most of them were only found by holding a scanner up to
something and watching what arrived.

Runs under pytest, or on its own with `python tests/test_barcodes.py` — there is
no test runner configured in this project yet, and a check nobody can run is not
a check.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.barcodes import gtin_variants, read, valid_gtin  # noqa: E402


def test_plain_ean13():
    s = read("5000112637939")
    assert s.symbology == "ean13"
    assert s.code == "5000112637939"
    assert not s.carries_batch


def test_gs1_with_gs_separators():
    """The form a wedge scanner types: FNC1 rendered as the GS character."""
    s = read("\x1d010950600013435217261231" + "10ABC123" + "\x1d" + "21S99")
    assert s.code == "09506000134352"
    assert s.batch == "ABC123"
    assert s.expiry == date(2026, 12, 31)
    assert s.serial == "S99"
    assert s.carries_batch


def test_gs1_bracketed_terminates_variable_elements():
    """`(10)LOT(21)SER` — the batch must not swallow the serial."""
    s = read("(01)09506000134352(17)260800(10)LOT-7(21)SER9")
    assert s.batch == "LOT-7"
    assert s.serial == "SER9"


def test_gs1_day_zero_means_end_of_month():
    """`260800` is not invalid; it means 'usable through August 2026'."""
    assert read("(01)09506000134352(17)260800").expiry == date(2026, 8, 31)


def test_aim_identifier_is_stripped():
    """Some scanners prefix the symbology, e.g. `]d2` for DataMatrix."""
    assert read("]d201095060001343521726123110ABC").code == "09506000134352"


def test_gtin_widening_matches_across_widths():
    """A 14-digit scan and a 13-digit catalogue entry are the same article."""
    assert "9506000134352" in gtin_variants("09506000134352")
    assert "09506000134352" in gtin_variants("9506000134352")


def test_excel_eaten_leading_zero_is_restored():
    """Supplier CSVs lose the first digit when Excel reads a code as a number."""
    assert "0761234567890" in gtin_variants("761234567890")


def test_bad_check_digit_warns_but_still_looks_up():
    """Own-label repacks fail the checksum legitimately; refusing them would
    break a workflow that works today."""
    s = read("6009876500011")
    assert s.keys, "a code that fails its check digit must still be searchable"
    assert any("check digit" in w for w in s.warnings)


def test_sscc_is_named_not_merely_unknown():
    """A pallet label is a different mistake from an unstocked product."""
    s = read("00123456789012345675")
    assert s.code == ""
    assert any("shipping-container" in w for w in s.warnings)


def test_non_numeric_falls_through_to_text():
    """NAPPI codes and typed product names must not be mangled."""
    s = read("NAPPI7113")
    assert s.symbology == "plain"
    assert "NAPPI7113" in s.keys


def test_empty_scan_is_harmless():
    s = read("   ")
    assert s.code == "" and s.keys == []


def test_valid_gtin_classifies():
    assert valid_gtin("5000112637939")
    assert not valid_gtin("5000112637930")
    assert not valid_gtin("not-a-number")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {name}  — {e or 'assertion failed'}")
    print(f"\n{failures} failed" if failures else "\nall passed")
    sys.exit(1 if failures else 0)
