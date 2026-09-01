"""Do the two ESC/POS renderers still produce the same bytes?

There are two, and there have to be: the desktop shell prints from TypeScript
so a pharmacy downloads one thing, and the device agent prints from Python so a
till with hardware and no desktop app still works. Two renderers of the same
document is exactly the arrangement that drifts, and the document here is a
dispensing label: a legal record with a batch number on it.

So they are compared byte for byte, on input chosen to exercise the parts that
are easy to get subtly wrong: bold, double height, centring, and right
alignment, which has to pad by hand because a double-height glyph is also
double-wide and the printer's own margin disagrees with ours.

    python qa/escpos-match.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LINES = [
    {"text": "AMOXICILLIN 500MG", "bold": True},
    {"text": "TAKE ONE TWICE A DAY", "bold": True, "double": True},
    {"text": "centre me", "align": "centre"},
    {"text": "right me", "align": "right"},
    {"text": "Batch: A43566", "feed": 1},
    {"text": "Muller & Co"},
]
WIDTH = 32


def typescript_bytes() -> str:
    """Bundle the front end's renderer and run it under node."""
    out = ROOT / "qa" / "out" / "escpos.mjs"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["npx", "--yes", "esbuild", "src/escpos.ts", "--bundle", "--format=esm",
         f"--outfile={out}"],
        cwd=ROOT / "frontend", check=True, capture_output=True, shell=True)
    script = (
        f"const m = await import({json.dumps(out.as_uri())});\n"
        f"const lines = {json.dumps(LINES)};\n"
        f"console.log(Buffer.from(m.render(lines, {WIDTH}, true)).toString('hex'));\n"
    )
    # Through a file rather than `-e`: the shell mangles the quoting on Windows
    # and node then reads an empty program and exits successfully, which looks
    # exactly like a renderer that produced nothing at all.
    runner = out.with_name("escpos-run.mjs")
    runner.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(runner)],
                            capture_output=True, text=True, shell=True)
    lines = result.stdout.strip().splitlines()
    if result.returncode != 0 or not lines:
        raise SystemExit("the TypeScript renderer would not run:\n"
                         + (result.stderr[:400] or result.stdout[:400] or "(no output)"))
    return lines[-1]


def python_bytes() -> str:
    sys.path.insert(0, str(ROOT / "device-agent"))
    from printing import CUT, ReceiptPrinter          # noqa: E402

    printer = ReceiptPrinter("label")
    printer.width = WIDTH
    payload = printer._render(LINES) + b"\n\n\n" + CUT
    return payload.hex()


def main() -> int:
    ts = typescript_bytes()
    py = python_bytes()
    if ts == py:
        print(f"ok   both renderers produce the same {len(ts) // 2} bytes")
        return 0

    print("THE TWO ESC/POS RENDERERS DISAGREE")
    print(f"  typescript : {ts}")
    print(f"  python     : {py}")
    for i in range(0, max(len(ts), len(py)), 2):
        a, b = ts[i:i + 2], py[i:i + 2]
        if a != b:
            print(f"  first difference at byte {i // 2}: "
                  f"typescript {a or '--'} vs python {b or '--'}")
            break
    return 1


if __name__ == "__main__":
    sys.exit(main())
