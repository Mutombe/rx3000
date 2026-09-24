/** What goes to a Zebra is a whole label, on every roll a pharmacy might load.
 *
 *  The label is drawn to a canvas at the printer's own resolution and sent as a
 *  one-bit picture, so the sticker on the roll is the sticker on the screen.
 *  That also means the failures are the ones a picture has: a label built at
 *  the wrong size for the roll, a drawing that came out empty, or bytes the
 *  printer cannot parse.
 *
 *  None of those announce themselves. A canvas clips at its own edge, so a
 *  label whose drawing goes wrong does not overflow — it comes out blank, and a
 *  printer given a blank graphic prints a blank sticker and reports success.
 *  Given malformed ZPL it prints nothing and reports nothing. The label layout
 *  is edited often, which is exactly the sort of change that does this quietly.
 *
 *  So: render the real label through the real renderer, at every resolution and
 *  roll size a pharmacy here plausibly has, and check that
 *
 *    - the raster is the size the paper is, to the dot,
 *    - there is ink on it, and it is not a solid black rectangle,
 *    - the job opens with ^XA and closes with ^XZ,
 *    - and every byte is printable ASCII, because ZPL is a text protocol and a
 *      smart quote out of a product name would end the field early.
 *
 *  Run by exit code. Nought is a pass.
 */
import { execFileSync } from "node:child_process";
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FRONT = path.join(ROOT, "frontend");
const WORK = fs.mkdtempSync(path.join(os.tmpdir(), "rx-zpl-"));

/** A label with every field filled in. Invented: no pharmacy's data is used to
 *  test, and a test that needs a real patient is a test nobody can run. */
const LABEL = {
  patient_name: "Tendai Mukoma", patient_id_number: "", rx_number: "RX-2026-004417",
  product_name: "AMOXICILLIN TRIHYDRATE", strength: "500MG", dosage_form: "Capsule",
  quantity: 21,
  dosage_instructions: "TAKE ONE CAPSULE THREE TIMES A DAY AFTER FOOD FOR SEVEN DAYS",
  warnings: "COMPLETE THE COURSE", schedule: 4, schedule_code: "PP",
  batch_number: "AMX-4471", manufacturer: "Varichem Pharmaceuticals",
  expiry_date: "2028-03-31", repeats_remaining: 0, next_repeat_date: null,
  doctor_name: "Dr N Chirwa", doctor_practice_no: "0412337",
  dispensed_by: "S. Adams", dispensed_at: "2026-09-24T12:00:00Z",
  pharmacy_name: "Demo Pharmacy", pharmacy_reg_no: "", pharmacy_address: "",
  pharmacy_phone: "", item_number: 1, item_count: 2, unit_price: 0, line_total: 0,
  branch_code: "HRE1", branch_name: "Demo Pharmacy Avondale",
  branch_address: "12 King George Road, Avondale, Harare",
  branch_phone: "+263 242 335 118", branch_reg_no: "", dispensing_id: 1,
};

/** The rolls and resolutions worth proving, and why each one is here. */
const CASES = [
  { say: "58x42 at 203dpi, the common roll", paper: { wide: 58, tall: 42 }, dpi: 203 },
  { say: "58x42 at 300dpi, the model above", paper: { wide: 58, tall: 42 }, dpi: 300 },
  { say: "100x50, a wide roll", paper: { wide: 100, tall: 50 }, dpi: 203 },
  { say: "38x25, the smallest in use", paper: { wide: 38, tall: 25 }, dpi: 203 },
  { say: "a script with no number, so no bars",
    paper: { wide: 58, tall: 42 }, dpi: 203, label: { ...LABEL, rx_number: "" } },
  { say: "a medicine name longer than the sticker",
    paper: { wide: 58, tall: 42 }, dpi: 203,
    label: { ...LABEL, product_name: "SODIUM CHLORIDE COMPOUND INTRAVENOUS INFUSION BP",
             strength: "0.9% 1000ML" } },
];

function bundle() {
  const entry = path.join(WORK, "entry.ts");
  fs.writeFileSync(entry,
    `import { labelZpl, rasterise } from ${JSON.stringify(path.join(FRONT, "src", "labelZpl.ts"))};\n` +
    `(window as any).RX = { labelZpl, rasterise };\n`);
  const out = path.join(WORK, "zpl.js");
  // The real executable, not the .bin shim: a .cmd cannot be spawned without a
  // shell on Windows, and a shell here would mean quoting temporary paths.
  const win = process.platform === "win32";
  const exe = path.join(FRONT, "node_modules", "@esbuild",
                        win ? "win32-x64/esbuild.exe" : "linux-x64/bin/esbuild");
  execFileSync(fs.existsSync(exe) ? exe : "npx",
               fs.existsSync(exe)
                 ? [entry, "--bundle", `--outfile=${out}`, "--format=iife", "--log-level=error"]
                 : ["esbuild", entry, "--bundle", `--outfile=${out}`, "--format=iife",
                    "--log-level=error"],
               { cwd: FRONT, stdio: ["ignore", "ignore", "inherit"], shell: !fs.existsSync(exe) });
  return out;
}

const faults = [];
const script = bundle();
const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228"
    + "/chrome-headless-shell-win64/chrome-headless-shell.exe",
});
try {
  const page = await browser.newPage();
  await page.setContent("<!doctype html><meta charset=utf-8><body></body>");
  await page.addScriptTag({ path: script });
  // The faces have to be loaded before anything is measured or drawn, or the
  // label is laid out in a fallback font and the answer changes run to run.
  await page.evaluate(() => document.fonts.ready);

  for (const c of CASES) {
    const label = c.label ?? LABEL;
    const got = await page.evaluate(([label, paper, dpi]) => {
      const zpl = window.RX.labelZpl(label, paper, dpi);
      const r = window.RX.rasterise(label, paper, dpi);
      let black = 0;
      for (const row of r.rows) {
        for (const byte of row) black += (byte.toString(2).match(/1/g) || []).length;
      }
      return {
        width: r.width, height: r.height, black, bytes: zpl.length,
        opens: zpl.startsWith("^XA"), closes: zpl.trimEnd().endsWith("^XZ"),
        odd: (zpl.match(/[^\x20-\x7E\n]/g) || []).slice(0, 3),
      };
    }, [label, c.paper, c.dpi]);

    const wide = Math.round(c.paper.wide * c.dpi / 25.4);
    const tall = Math.round(c.paper.tall * c.dpi / 25.4);
    if (got.width !== wide || got.height !== tall) {
      faults.push(`${c.say}: built ${got.width}x${got.height} dots for paper that `
                + `is ${wide}x${tall}.`);
    }
    // How much of the sticker is burned. A dispensing label is dense text and
    // a barcode, which lands near a tenth of the paper.
    //
    // Nought is the failure that matters: the canvas clips at its own edge, so
    // a label whose drawing goes wrong does not overflow, it comes out blank.
    // A printer given a blank graphic prints a blank sticker and reports
    // success, and the first person to notice is holding an unlabelled box.
    //
    // The ceiling catches the other direction, a threshold or a fill colour
    // inverted, which prints a solid black sticker and empties the ribbon.
    const ink = got.black / (got.width * got.height);
    if (ink < 0.02) {
      faults.push(`${c.say}: ${(ink * 100).toFixed(1)}% of the sticker is inked, `
                + `which is a blank label. It will print, and say it printed.`);
    } else if (ink > 0.40) {
      faults.push(`${c.say}: ${(ink * 100).toFixed(1)}% of the sticker is inked, `
                + `which is not a label but a black rectangle.`);
    }
    if (!got.opens || !got.closes) {
      faults.push(`${c.say}: the job does not open with ^XA and close with ^XZ, `
                + `so the printer will wait for the rest of it.`);
    }
    if (got.odd.length) {
      faults.push(`${c.say}: ${got.odd.length} byte(s) outside printable ASCII `
                + `(${got.odd.map((c) => JSON.stringify(c)).join(", ")}). ZPL is `
                + `text and these end a field early.`);
    }
    if (!faults.length || !faults[faults.length - 1].startsWith(c.say)) {
      console.log(`  ok  ${c.say.padEnd(42)} ${got.width}x${got.height} dots, `
                + `${(got.bytes / 1024).toFixed(1)}KB, `
                + `${(got.black / (got.width * got.height) * 100).toFixed(1)}% inked`);
    }
  }
} finally {
  await browser.close();
  fs.rmSync(WORK, { recursive: true, force: true });
}

if (faults.length) {
  console.log("\nA Zebra would not get a whole label.\n");
  for (const f of faults) console.log(`    ${f}`);
  console.log("\n  The label is drawn by labelPlacement and rasterised by "
            + "labelZpl.ts.\n  This is the only place it is checked, because a "
            + "thermal printer prints\n  whatever it is given and says nothing "
            + "about what it could not read.");
  process.exit(1);
}
console.log("\nEvery roll gets a whole label, and every job is ZPL a printer can read.");
