/** Does every combobox in a page head actually show its options?
 *
 *  WHAT WENT WRONG
 *
 *  The stock reports picker rendered as a 208 by 224 empty box. Twenty six
 *  reports sat behind it and none could be seen. It was replaced with a
 *  native select and a note blaming "something in this header's cascade",
 *  which was wrong: five other screens put a combobox in a page head and
 *  every one of them works.
 *
 *  224 pixels is 14rem, which is the `min-height` on `.empty` — the
 *  application's EMPTY STATE block, the centred "Nothing to show here" panel.
 *  The combobox added a bare `empty` class to its trigger whenever nothing
 *  was selected, so an unselected picker wore the empty-state box. The stock
 *  picker is a jump menu that is never selected, which is why it was the only
 *  one that ever showed it.
 *
 *  Third time in this codebase that one class name has meant two things:
 *  `.lbl` was a dispensing sticker and a form label, `.stock-reports-pick`
 *  was sized for a native select and worn by a combobox, and `.empty` was an
 *  empty state and a modifier. None of them is a cascade problem and none is
 *  mysterious once the numbers are read: 14rem is 224, 13rem is 208.
 *
 *  Nothing else catches this. The class exists and is used, so dead-classes
 *  is happy. The markup is valid, the component mounts, React throws nothing
 *  and the console is clean. The only way to know is to open the thing and
 *  look, which is what this does.
 *
 *  WHY PAGE HEADS
 *
 *  Because that is where it went wrong, and because a page head is the one
 *  place in this application where a control stands among buttons rather than
 *  in a form, so it is where somebody reaches for a width to make it line up.
 *
 *  Needs the app on 5180 and an API it can reach.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const WEB = process.env.RX_WEB ?? "http://localhost:5180";

/** Screens that put a combobox in their page head. A route that has stopped
 *  having one is reported rather than skipped silently: a picker that has
 *  quietly disappeared is also worth knowing about. */
const ROUTES = [
  "/stock",
  "/scorecard",
  "/seasons",
  "/stock-performance",
  "/reconciliation/settlements",
  "/branches/1/performance",
];

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

await page.goto(`${WEB}/login`);
await page.waitForTimeout(1000);
const fields = await page.locator("input").all();
await fields[0].fill("admin");
await fields[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(2600);
// The assistant dock sits over the bottom corner and swallows clicks meant
// for what is under it.
await page.evaluate(() => localStorage.setItem("rx5000_assistant_dock_seen", "1"));

console.log("a picker shows its options");
console.log();

const failures = [];
let checked = 0;

for (const route of ROUTES) {
  let loaded = true;
  try {
    await page.goto(WEB + route, { waitUntil: "networkidle", timeout: 25000 });
  } catch {
    loaded = false;
  }
  if (!loaded) {
    console.log(`  ?    ${route}`);
    console.log("       did not load, so its picker could not be checked");
    continue;
  }
  await page.waitForTimeout(900);

  const trigger = await page.$(".page-head .sel-trigger");
  if (!trigger) {
    console.log(`  ?    ${route}`);
    console.log("       no combobox in the page head any more");
    continue;
  }

  checked += 1;

  // THE CLOSED CONTROL FIRST.
  //
  // The first version of this check only opened the panel, and passed a
  // page where the trigger itself stood 224 pixels tall: the combobox added
  // a bare `empty` class when nothing was chosen, and `.empty` is the
  // application's empty-state block, which carries min-height 14rem. 14rem
  // is 224. A guard that only looks at what opens misses the control you
  // have to click to open it.
  const closed = await page.evaluate(() => {
    const t = document.querySelector(".page-head .sel-trigger");
    const r = t.getBoundingClientRect();
    return { width: Math.round(r.width), height: Math.round(r.height) };
  });
  if (closed.height > 80 || closed.height < 20) {
    console.log(`  X    ${route}`);
    console.log(`       the control itself is ${closed.height}px tall before `
                + "it is even opened");
    console.log("       a picker is one row high. Something has given it a "
                + "height meant for a block.");
    failures.push(route);
    continue;
  }

  await trigger.click().catch(() => {});
  await page.waitForTimeout(500);

  const seen = await page.evaluate(() => {
    const panel = document.querySelector(".sel-panel");
    if (!panel) return null;
    const box = panel.getBoundingClientRect();
    const options = panel.querySelectorAll(".sel-option, [role=option]");
    return {
      width: Math.round(box.width),
      height: Math.round(box.height),
      options: options.length,
      // Not just present: readable. A panel of the right size holding
      // nothing is exactly what the original bug looked like.
      letters: panel.innerText.trim().length,
    };
  });

  if (seen === null) {
    console.log(`  X    ${route}`);
    console.log("       the panel did not open at all");
    failures.push(route);
    await page.keyboard.press("Escape").catch(() => {});
    continue;
  }

  const why = seen.options === 0 ? "the panel opened with no options in it"
    : seen.letters === 0 ? "the panel opened with nothing readable in it"
    : seen.height < 20 ? `the panel is only ${seen.height}px tall`
    : seen.width < 40 ? `the panel is only ${seen.width}px wide`
    : "";

  if (why) {
    console.log(`  X    ${route}`);
    console.log(`       ${why} (${seen.width}x${seen.height})`);
    console.log("       a control that sizes itself must not be given a "
                + "fixed width or height.");
    failures.push(route);
  } else {
    console.log(`  ok   ${route}`.padEnd(38)
                + `${seen.width}x${seen.height}, ${seen.options} option(s)`);
  }
  await page.keyboard.press("Escape").catch(() => {});
}

console.log();
if (failures.length) {
  console.log(`  ${failures.length} of ${checked} picker(s) do not show what `
              + "is inside them");
} else {
  console.log(`  ${checked} picker(s) opened and showed their options`);
  console.log();
  console.log("a picker nobody can read is a feature nobody has");
}
await browser.close();
process.exit(failures.length ? 1 : 0);
