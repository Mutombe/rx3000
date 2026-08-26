/** Does the interaction screen run itself, and does it gate the dispense?
 *
 *  Three things being checked, all of which the button-driven version failed:
 *  it runs without anybody pressing anything, it catches a new line against the
 *  patient's own dispensing history rather than only within the basket, and a
 *  major finding stops the dispense button until it is acknowledged.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const page = await b.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = [];
page.on("pageerror", (e) => errs.push(e.message.slice(0, 140)));
await page.goto("http://localhost:5180/login");
await page.waitForTimeout(1000);
const inp = await page.locator("input").all();
await inp[0].fill("admin"); await inp[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(2600);

await page.goto("http://localhost:5180/dispense", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2500);

const out = { steps: [] };

// The patient whose history holds fluoxetine.
// The picker offers results as `.product-pick` divs; typing alone selects
// nobody, and a test that only types is testing its own patience.
const patientBox = page.locator('input[placeholder*="atient" i]').first();
await patientBox.fill(process.env.PATIENT_SURNAME || "Ncube");
await page.waitForTimeout(1600);
const firstPatient = page.locator(".product-pick").first();
await firstPatient.click();
await page.waitForTimeout(900);
out.steps.push(`patient selected: ${(await page.locator(".pt-card, .patient-card").count()) > 0
  || !(await patientBox.count())}`);

// Add tramadol, which interacts with the fluoxetine already on file.
const productBox = page.locator('input[placeholder*="prescription medicines" i]').first();
await productBox.fill("Tramadol");
await page.waitForTimeout(1600);
const hit = page.locator(".product-pick").filter({ hasText: "Tramadol" }).first();
if (await hit.count()) { await hit.click(); await page.waitForTimeout(1800); }

out.panelAppeared = await page.locator(".ix").count() > 0;
out.isMajor = await page.locator(".ix.ix-major").count() > 0;
out.headline = (await page.locator(".ix-head").innerText().catch(() => "")).replace(/\s+/g, " ");
out.findings = await page.locator(".ix-row").allInnerTexts().then((a) => a.map((t) => t.replace(/\s+/g, " ")));
out.coverageShown = await page.locator(".ix-coverage").count() > 0;
const dispense = page.locator("button", { hasText: /^Dispense \d/ }).first();
out.dispenseDisabledBeforeAck = await dispense.count() ? await dispense.isDisabled() : null;
// Everything else the dispense gate wants, so the acknowledgement is the only
// variable. Without this the button stays disabled for a missing pharmacist
// initial and the test reports the interaction gate as broken.
const initials = page.locator('input[placeholder*="e.g. TM" i]').first();
if (await initials.count()) { await initials.fill("TM"); await page.waitForTimeout(400); }
out.dispenseDisabledWithInitialsButNoAck = await dispense.isDisabled();

if (await page.locator(".ix-ack input").count()) {
  await page.locator(".ix-ack input").check();
  await page.waitForTimeout(500);
  out.dispenseEnabledAfterAck = (await dispense.isDisabled()) === false;
}
// And that removing the acknowledgement closes the gate again.
if (out.dispenseEnabledAfterAck) {
  await page.locator(".ix-ack input").uncheck();
  await page.waitForTimeout(400);
  out.reDisabledWhenAckRemoved = await dispense.isDisabled();
}
await page.screenshot({ path: "qa/out/interaction-screen.png" });
await b.close();
console.log(JSON.stringify({ ...out, pageErrors: errs }, null, 1));
