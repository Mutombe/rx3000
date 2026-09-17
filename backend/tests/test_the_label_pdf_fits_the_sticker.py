"""The label PDF fits the sticker it is drawn for.

The label that goes to a real label printer is now a small PDF handed to the
printer's own Windows driver. That is what makes one layout work on a Zebra, a
TSC and anything else a pharmacy buys: the driver knows the printer's language,
so we never have to.

It also means the failure mode moved. A driver clips silently, so a label that
wants more room than the sticker has does not look broken — it looks finished,
with the footer missing. The photograph that started this had exactly that
shape, and nobody could see it without printing one.

This renders the real layout, off the real module, and measures what the content
wants against what the paper has. It asserts a measurement rather than an
appearance, because appearance is what hid it.

WHAT IT CANNOT SEE. Text is measured with a canvas where there is one, and node
has none, so this runs on the estimate instead — deliberately the generous one,
but still an estimate. It is a guard against the layout growing, not a
guarantee of the last millimetre. `qa/label-pdf-look.mjs` measures the same
layout in a browser with the real font metrics, and draws it, which is what to
run when the layout is being changed on purpose.

Needs node and the project's own esbuild, both of which the frontend build
already requires. Skips rather than fails where they are missing, so a backend
checkout without node installed does not report a fault in the label.

  python tests/test_the_label_pdf_fits_the_sticker.py
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src" / "labelPdf.ts"
ESBUILD = ROOT / "frontend" / "node_modules" / "esbuild" / "lib" / "main.js"

#: The sticker the layout is drawn for, and the ones a pharmacy might load.
#: The last is deliberately too small: a checker that only ever passes is not
#: telling anybody anything.
SIZES = [(58, 42), (76, 51), (58, 30)]

#: Long where labels are long. A sample of short fields proves nothing about
#: the labels that overflow, and the long ones are the whole problem.
LABEL = {
    "patient_name": "Munanawashe Chamburuka-Matoveru",
    "rx_number": "RX260900015",
    "product_name": "BLOCPAIN (ACECLOFENAC 100/PARACET 500MG)",
    "strength": "", "dosage_form": "Tablet", "quantity": 30,
    "dosage_instructions": ("TAKE ONE TABLET ONCE A DAY AFTER FOOD WHEN "
                            "REQUIRED FOR PAIN AND INFLAMMATION."),
    "warnings": "", "schedule": 4, "schedule_code": "PP",
    "batch_number": "OPENING", "manufacturer": "",
    "expiry_date": "2028-09-17",
    "doctor_name": "Maboreke Dr", "doctor_practice_no": "106770",
    "dispensed_by": "Vanesa Tokonyai", "dispensed_at": "2026-09-17T14:22:09",
    "pharmacy_name": "CareXpress Pharmacy",
    "pharmacy_address": "114 Samora Machel Avenue, Harare",
    "pharmacy_phone": "0732 307 400",
    "branch_code": "CX-CHI", "branch_name": "CareXpress Chinamano",
    "branch_address": "114 Samora Machel Avenue, Harare",
    "branch_phone": "0732 307 400",
    "item_number": 1, "item_count": 2,
}

RUNNER = r"""
import { labelPdf, labelHeightMm, labelPlacement } from "%SRC%";
const label = %LABEL%;
const out = [];
for (const [wide, tall] of %SIZES%) {
  const sticker = { wide, tall };
  const pdf = labelPdf(label, sticker);
  const text = Buffer.from(pdf).toString("latin1");
  out.push({
    wide, tall,
    wants: labelHeightMm(label, sticker),
    lines: labelPlacement(label, sticker).length,
    bytes: pdf.length,
    isPdf: text.startsWith("%PDF-") && text.trimEnd().endsWith("%%EOF"),
    // Every field a label is read for has to be somewhere in the file.
    has: {
      medicine: text.includes("BLOCPAIN"),
      directions: text.includes("TAKE ONE TABLET"),
      patient: text.includes("Munanawashe"),
      shop: text.includes("CareXpress Chinamano"),
      street: text.includes("Samora Machel"),
      phone: text.includes("0732 307 400"),
      classification: text.includes("PP"),
    },
  });
}
console.log(JSON.stringify(out));
"""


def run() -> None:
    node = shutil.which("node")
    if not node or not ESBUILD.exists():
        print("skip  node or esbuild is not installed; nothing to render with")
        return

    work = pathlib.Path(tempfile.mkdtemp(prefix="label-pdf-"))
    bundle = work / "labelPdf.mjs"
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
        RUNNER.replace("%SRC%", bundle.as_uri())
              .replace("%LABEL%", json.dumps(LABEL))
              .replace("%SIZES%", json.dumps(SIZES)),
        encoding="utf-8")
    said = subprocess.run([node, str(runner)], check=True, capture_output=True, text=True)
    results = json.loads(said.stdout)

    by_size = {(r["wide"], r["tall"]): r for r in results}

    # The sticker the layout is drawn for. This is the one that must fit.
    home = by_size[(58, 42)]
    assert home["isPdf"], "what came out is not a PDF file"
    print(f"ok    it is a PDF, {home['bytes']} bytes, {home['lines']} lines of text")

    for field, there in home["has"].items():
        assert there, f"the label does not carry the {field}"
    print("ok    the medicine, directions, patient, shop, street, phone and "
          "classification are all in it")

    assert home["wants"] <= 42, (
        f"the label wants {home['wants']:.1f}mm of a 42mm sticker. The driver "
        "clips, so the bottom would be missing and nothing would say so.")
    print(f"ok    it fits 58 x 42mm: wants {home['wants']:.1f}mm of 42mm")

    bigger = by_size[(76, 51)]
    assert bigger["wants"] <= 51, f"it wants {bigger['wants']:.1f}mm of 51mm"
    # A wider sticker fits more on a line, so it needs less height, not more.
    assert bigger["wants"] <= home["wants"], (bigger["wants"], home["wants"])
    print(f"ok    and a wider roll needs less of it: {bigger['wants']:.1f}mm of 51mm")

    # And the measurement is capable of saying no.
    small = by_size[(58, 30)]
    assert small["wants"] > 30, (
        "a 58 x 30mm sticker was reported as fitting this label, which means "
        "the measurement cannot detect overflow and proves nothing above")
    print(f"ok    a 58 x 30mm sticker is reported as too small "
          f"({small['wants']:.1f}mm needed), so the check can fail")

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
