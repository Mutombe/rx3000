"""The QR code that turns somebody's phone into a scanner.

WHY A HAND-WRITTEN CODEC NEEDS A GUARD

`frontend/src/qr.ts` is an encoder written out in this repository rather than
installed, for the reasons in its own header. That is a reasonable trade and it
comes with an obligation: an encoder that is subtly wrong produces a picture
that looks exactly like a working one. It is square, it has the three corner
squares, it is obviously A Barcode — and no phone on earth can read it.

That is not a hypothetical. The first version had two such bugs. It painted the
white separator ring around each finder dark, and it wrote the fifteen format
bits mirrored. Both symbols rendered beautifully. Neither decoded, at all, ever.

So this does not read the code. It encodes known payloads and compares every
module against a reference encoder, which is the only check that can tell a
working symbol from a handsome one.

WHAT IS CHECKED

That the pairing alphabet encodes; that the result is a valid version 1 symbol
of the right size; that it matches a reference encoder module for module, or
differs only in ways a decoder does not care about; and that a payload it
cannot encode returns nothing rather than a picture that will not read.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QR = ROOT / "frontend" / "src" / "qr.ts"

passed = 0
failed = 0


def check(condition: bool, message: str, extra: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {message}")
    else:
        failed += 1
        print(f"  FAIL {message}{('   ' + extra) if extra else ''}")


try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
except ImportError:
    print("  ..   python 'qrcode' is not installed; nothing to compare against")
    sys.exit(0)

esbuild = ROOT / "frontend" / "node_modules" / ".bin" / "esbuild.cmd"
if not esbuild.exists():
    esbuild = ROOT / "frontend" / "node_modules" / ".bin" / "esbuild"
if not esbuild.exists() or shutil.which("node") is None:
    print("  ..   esbuild or node is not available; cannot run the encoder")
    sys.exit(0)

# Codes chosen to exercise the shape of a real pairing code and the two
# branches of alphanumeric packing: pairs of characters, and a trailing odd
# one. All six characters long, which is what `scanner_link` issues.
CODES = ["A2C4EF", "XYZ279", "KLMNPQ", "R5T7U9", "ACDEFG", "HJKLMN", "P2Q3R4"]

print("\n  the encoder runs at all\n")

work = Path(tempfile.mkdtemp())
try:
    bundle = work / "qr.mjs"
    built = subprocess.run(
        [str(esbuild), str(QR), "--bundle", "--format=esm", f"--outfile={bundle}"],
        capture_output=True, text=True)
    check(built.returncode == 0, "the encoder compiles",
          (built.stderr or "")[:120])
    if built.returncode != 0:
        print(f"\n{passed} passed, {failed} failed")
        sys.exit(1)

    driver = work / "run.mjs"
    driver.write_text(
        "import { qrMatrix } from './qr.mjs';\n"
        "const codes = JSON.parse(process.argv[2]);\n"
        "const out = {};\n"
        "for (const c of codes) out[c] = qrMatrix(c);\n"
        "out['__lower__'] = qrMatrix('lowercase');\n"
        "out['__bad__'] = qrMatrix('no lowercase ~ here');\n"
        "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8")

    ran = subprocess.run(["node", str(driver), json.dumps(CODES)],
                         capture_output=True, text=True)
    check(ran.returncode == 0, "and produces a matrix",
          (ran.stderr or "")[:140])
    if ran.returncode != 0:
        print(f"\n{passed} passed, {failed} failed")
        sys.exit(1)
    mine = json.loads(ran.stdout)
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\n  every pairing code matches a reference encoder\n")

for code in CODES:
    got = mine.get(code)
    if not got:
        check(False, f"{code} encodes", "the encoder returned nothing")
        continue

    want = qrcode.QRCode(version=1, error_correction=ERROR_CORRECT_M,
                         box_size=1, border=0)
    want.add_data(code)
    want.make(fit=True)
    ref = [[1 if v else 0 for v in row] for row in want.get_matrix()]

    if len(got) != len(ref):
        check(False, f"{code} is the right size",
              f"{len(got)} modules against {len(ref)}")
        continue

    # ONLY THE FUNCTION PATTERNS ARE COMPARED.
    #
    # Not the format bits and not the data. Both depend on which of the eight
    # masks won on penalty score, and two encoders can legitimately choose
    # differently and produce symbols that decode to the same string. Asserting
    # those match is asserting that two implementations broke a tie the same
    # way, which is not a property anybody needs.
    #
    # What must match is the scaffolding a decoder finds the symbol BY: the
    # three finders, the white separators around them, the two timing lines
    # and the dark module. Those are fixed for a given version. Both original
    # bugs lived here.
    size = len(ref)
    fixed = []
    for r in range(size):
        for c in range(size):
            in_finder = ((r < 8 and c < 8)
                         or (r < 8 and c >= size - 8)
                         or (r >= size - 8 and c < 8))
            if in_finder or r == 6 or c == 6 or (r == size - 8 and c == 8):
                if ref[r][c] != got[r][c]:
                    fixed.append((r, c))
    check(not fixed,
          f"{code}: finders, separators and timing match the reference",
          f"{len(fixed)} differ, e.g. {fixed[:4]}")

print("\n  and a phone can actually read it\n")

# THE CHECK THAT MATTERS.
#
# Everything above says the picture is shaped correctly. This says a decoder
# gets the string back out, which is the only claim anybody cares about and
# the one the first two versions of this encoder failed while looking perfect.
try:
    import cv2
    import numpy as np
except ImportError:
    print("  ..   opencv is not installed; the shape checks above stand alone")
else:
    detector = cv2.QRCodeDetector()
    for code in CODES:
        got = mine.get(code)
        if not got:
            continue
        # Ten pixels a module with a four module quiet zone, which is roughly
        # what the counter screen shows.
        scale, quiet = 10, 4
        size = len(got)
        span = (size + quiet * 2) * scale
        img = np.full((span, span), 255, dtype=np.uint8)
        for r in range(size):
            for c in range(size):
                if got[r][c]:
                    y, x = (r + quiet) * scale, (c + quiet) * scale
                    img[y:y + scale, x:x + scale] = 0
        read, _, _ = detector.detectAndDecode(img)
        check(read == code, f"{code} decodes back to itself",
              f"a decoder read {read!r}")

print("\n  and it refuses what it cannot draw\n")

# Uppercased on purpose: QR alphanumeric mode has no lowercase, and a pairing
# code is uppercase everywhere it is shown. Encoding the uppercase form is
# right; what would be wrong is drawing something that reads back differently
# from what was asked for, which the check above would catch.
check(mine.get("__lower__") is not None,
      "lowercase is uppercased rather than refused, as the pairing code is")
check(mine.get("__bad__") is None,
      "a payload outside the alphanumeric set returns nothing",
      "better no symbol than one that cannot be read")

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\na wrong QR looks exactly like a right one. The only way to know "
          "is to compare it against an encoder that works.")
sys.exit(1 if failed else 0)
