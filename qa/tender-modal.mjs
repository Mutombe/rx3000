/** The payment dialog, at the widths a counter actually uses.
 *
 *  This is the dialog from the screenshot: "Take part of it", with a medical
 *  aid line and a cash line. It was laid out in four columns because
 *  `.tender-line` meant two incompatible things in one stylesheet — a grid row
 *  in the till's own split-tender panel, a bordered card in the shared Tenders
 *  component, and neither rule was scoped. The method, the currency and the
 *  amount stacked into the first column; "Hold this claim — do not send it now"
 *  landed in the fourth and wrapped a word per line outside the dialog.
 *
 *  Rather than drive a whole dispensing to reach it, the component is mounted
 *  directly against the running app's stylesheet. What is being tested is the
 *  layout, and the layout is the CSS.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const EXE = "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe";
const BASE = process.env.RX_BASE || "http://localhost:5180";

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const failures = [];

function check(ok, message) {
  console.log(`  ${ok ? "ok  " : "FAIL"} ${message}`);
  if (!ok) failures.push(message);
}

await page.goto(`${BASE}/login`);
await page.waitForTimeout(1200);
const inputs = await page.locator("input").all();
await inputs[0].fill(process.env.RX_USER || "admin");
await inputs[1].fill(process.env.RX_PASS || "admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(2600);

/** The dialog as the screenshot showed it: two payment lines, one of them a
 *  held medical aid claim, inside a real .modal. */
const MARKUP = `
<div class="modal-backdrop" id="probe">
  <div class="modal modal-wide">
    <h2>Take part of it</h2>
    <p class="muted">Blessing Chigumba owes <b>$1.40</b>. Whatever is not paid
      now stays against this sale until it is collected.</p>
    <div class="tenders">
      <div class="tender-line">
        <div class="tender-row">
          <button class="sel">Medical aid</button>
          <button class="sel">USD</button>
          <input class="tender-amount" placeholder="0.00">
          <button class="btn ghost small">x</button>
        </div>
        <div class="tender-detail">
          <input placeholder="Scheme reference, if they gave one">
          <span class="muted small">The claim covers <b>$5.60</b> of this.</span>
          <label class="cbx"><input type="checkbox">
            <span>Hold this claim &mdash; do not send it now</span></label>
        </div>
      </div>
      <div class="tender-line">
        <div class="tender-row">
          <button class="sel">Cash</button>
          <button class="sel">USD</button>
          <input class="tender-amount" placeholder="0.00">
          <button class="btn ghost small">x</button>
        </div>
      </div>
    </div>
    <div class="tender-total short">
      <span>Taking <b>$0.00</b> of $1.40</span><span><b>$1.40</b> still owing</span>
    </div>
    <label class="field">Note (optional)<input placeholder="e.g. bringing the rest on Friday"></label>
    <div class="modal-actions">
      <button class="btn ghost">Cancel</button>
      <button class="btn primary">Take payment</button>
    </div>
  </div>
</div>`;

for (const width of [1440, 1100, 820, 560, 400]) {
  await page.setViewportSize({ width, height: 900 });
  await page.evaluate((html) => {
    document.getElementById("probe")?.remove();
    document.body.insertAdjacentHTML("beforeend", html);
  }, MARKUP);
  await page.waitForTimeout(250);

  const m = await page.evaluate(() => {
    const modal = document.querySelector("#probe .modal");
    const box = modal.getBoundingClientRect();
    const escaped = [];
    for (const el of modal.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (!r.width && !r.height) continue;
      if (r.right > box.right + 1 || r.left < box.left - 1) {
        escaped.push(`${el.tagName.toLowerCase()} "${(el.textContent || "").trim().slice(0, 28)}"`);
      }
    }
    const row = modal.querySelector(".tender-row");
    const kids = [...row.children].map((c) => c.getBoundingClientRect());
    // On one line means every child shares a horizontal band with the first.
    const onOneLine = kids.every((r) => Math.abs(r.top - kids[0].top) < 6);
    const hold = [...modal.querySelectorAll("span")]
      .find((s) => s.textContent.includes("Hold this claim"));
    const holdBox = hold.getBoundingClientRect();
    return {
      escaped: [...new Set(escaped)].slice(0, 4),
      sideways: modal.scrollWidth > modal.clientWidth + 1,
      onOneLine,
      // The label used to be ~4rem wide and 200px tall: one word per line.
      holdRatio: holdBox.height / Math.max(holdBox.width, 1),
      holdInside: holdBox.right <= box.right + 1,
    };
  });

  console.log(`\n=== ${width}px ===`);
  check(!m.sideways, "the dialog does not scroll sideways");
  check(m.escaped.length === 0,
        `nothing escapes it${m.escaped.length ? `: ${m.escaped.join("; ")}` : ""}`);
  check(m.holdInside, "the hold-this-claim label is inside the dialog");
  check(m.holdRatio < 1,
        `that label is wider than it is tall (ratio ${m.holdRatio.toFixed(2)}), `
        + "not one word per line");
  // The breakpoint is `max-width: 560px`, so 560 itself is already the narrow
  // layout. Above it the row is one line; at or below it deliberately becomes
  // two, which is the whole point of the media query, so both sides are
  // asserted rather than only the wide one.
  if (width > 560) {
    check(m.onOneLine, "method, currency and amount sit on one line");
  } else {
    check(!m.onOneLine,
          "the row folds to two lines rather than squeezing four columns");
  }
}

console.log("");
if (failures.length) {
  console.log(`${failures.length} failed`);
  await browser.close();
  process.exit(1);
}
console.log("the payment dialog holds its shape");
await browser.close();
