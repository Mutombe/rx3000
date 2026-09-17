"""A script's barcode decodes as that script, and not as something else.

MCAZ expects a dispensed script to carry a barcode. What it encodes is the Rx
number, which is the identity this system already issues.

The failure worth guarding is not a barcode that fails to print. It is one that
prints, looks entirely correct, and decodes as a different script — or as
nothing. Both have happened here already: the stop pattern was written with six
elements instead of seven, so every symbol was missing its final bar. It
measured correctly, it drew correctly, and no scanner on earth could read it.
Looking at it proved nothing.

So this checks the encoder against the specification rather than against its own
output: the check digit, the symbol widths for a known string, and the shape of
the start and stop patterns. Those are the three things that were wrong or could
be.

The stronger check is `qa/barcode-reads.mjs`, which draws the symbol and has the
application's own scanner read it back. That needs a browser and the wasm
decoder; this needs neither, so it can run anywhere the rest of the suite does.

  python tests/test_script_barcodes_decode.py
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src" / "code128.ts"
ESBUILD = ROOT / "frontend" / "node_modules" / "esbuild" / "lib" / "main.js"

RUNNER = """
import { code128Bars, code128Rects, code128Width } from "%SRC%";
const out = {};
for (const text of %CASES%) {
  out[text] = {
    bars: code128Bars(text),
    rects: code128Rects(text).length,
    width: code128Width(text),
  };
}
console.log(JSON.stringify(out));
"""

CASES = ["RX260900015", "A", ""]


def run() -> None:
    node = shutil.which("node")
    if not node or not ESBUILD.exists():
        print("skip  node or esbuild is not installed; nothing to encode with")
        return

    work = pathlib.Path(tempfile.mkdtemp(prefix="code128-"))
    bundle = work / "code128.mjs"
    build = work / "build.mjs"
    build.write_text(f"""
      const esbuild = await import({json.dumps(ESBUILD.as_uri())});
      await (esbuild.default ?? esbuild).build({{
        entryPoints: [{json.dumps(str(SRC))}], bundle: true, format: "esm",
        platform: "node", outfile: {json.dumps(str(bundle))}, logLevel: "silent",
      }});
    """, encoding="utf-8")
    subprocess.run([node, str(build)], check=True, capture_output=True)

    runner = work / "run.mjs"
    runner.write_text(
        RUNNER.replace("%SRC%", bundle.as_uri()).replace("%CASES%", json.dumps(CASES)),
        encoding="utf-8")
    said = subprocess.run([node, str(runner)], check=True, capture_output=True, text=True)
    got = json.loads(said.stdout)

    assert got[""]["width"] == 0, "an empty string encoded to something"
    print("ok    nothing encodes to nothing, rather than to a stray symbol")

    bars = got["A"]["bars"]
    # quiet | start B | 'A' | check | stop | quiet
    assert bars[0] == 10 and bars[-1] == 10, f"the quiet zones are missing: {bars[:2]}"
    print("ok    it carries a quiet zone at each end, which a scanner reads as part of it")

    # Start B is 211214, and it comes straight after the leading quiet zone.
    assert bars[1:7] == [2, 1, 1, 2, 1, 4], f"start B is wrong: {bars[1:7]}"
    print("ok    it starts with Start B (211214)")

    # The stop is SEVEN elements — 2331112 — and the seventh is the bar that
    # tells a scanner the symbol has ended. Six of them decodes as nothing.
    stop = bars[-8:-1]
    assert stop == [2, 3, 3, 1, 1, 1, 2], f"the stop pattern is wrong: {stop}"
    print("ok    and ends with the full seven element stop (2331112)")

    # 'A' is ASCII 65, so its Set B value is 65 - 32 = 33, and symbol 33 is
    # 111323. Worked from the specification rather than read back off this code.
    letter = bars[7:13]
    assert letter == [1, 1, 1, 3, 2, 3], f"the symbol for 'A' is wrong: {letter}"
    print("ok    'A' encodes as symbol 33 (111323)")

    # The check is (start + value x position) mod 103 = (104 + 33) mod 103 = 34,
    # and symbol 34 is 131123.
    check = bars[13:19]
    assert check == [1, 3, 1, 1, 2, 3], f"the check digit symbol is wrong: {check}"
    print("ok    the check digit is the one the specification gives: 34 for 'A'")

    # Every bar the caller is handed has to be a bar. The rectangles are taken
    # from alternate entries, and a stop pattern of the wrong length flips that
    # alternation so the trailing quiet zone is drawn as ink.
    rx = got["RX260900015"]
    assert rx["rects"] == (len(rx["bars"]) - 1) // 2, (rx["rects"], len(rx["bars"]))
    print(f"ok    {rx['rects']} bars drawn from {len(rx['bars'])} elements, "
          "so the alternation holds and the quiet zone stays white")

    shutil.rmtree(work, ignore_errors=True)


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
