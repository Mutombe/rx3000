/** Does the till lock fire where it should, and stay quiet where it should not?
 *
 *  The complaint that prompted this: a PIN prompt every five minutes on a
 *  back-office machine nobody else touches. That is how a lock gets switched
 *  off, and then the till it was written for is unlocked all day too.
 *
 *  `?lockAfter=` shortens the idle wait so this takes seconds rather than five
 *  minutes. It can only ever make the lock fire sooner, so there is nothing to
 *  gain by setting it in the field.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
const unhandled = [];
page.on("pageerror", (e) => unhandled.push(e.message.slice(0, 90)));
page.on("console", (m) => {
  const t = m.text();
  if (/unhandled failure|till is locked/i.test(t)) unhandled.push(t.slice(0, 110));
});

await page.goto("http://localhost:5180/login");
await page.waitForTimeout(900);
const i = await page.locator("input").all();
await i[0].fill("admin"); await i[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(2500);

// The admin's PIN has to exist or nothing locks at all; that guard is separate
// and correct, so it is set up rather than worked around.
await page.evaluate(async () => {
  const token = localStorage.getItem("rx5000_token") || localStorage.getItem("rx3000_token");
  await fetch("/api/auth/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ pin: "4913", password: "admin123" }),
  });
});

const rows = [];
for (const [route, expected] of [["/reports", "quiet"], ["/patients", "quiet"],
                                 ["/ledger", "quiet"], ["/register", "locks"],
                                 ["/dispense", "locks"]]) {
  await page.goto(`http://localhost:5180${route}?lockAfter=1200`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  await page.mouse.move(640, 500);          // one movement, then leave it alone
  await page.waitForTimeout(3200);
  const locked = (await page.locator(".lock, .lock-bar").count()) > 0;
  rows.push({ route, expected, actual: locked ? "locks" : "quiet",
              ok: (locked ? "locks" : "quiet") === expected ? "yes" : "NO" });
}

// And that dismissing a lock does not log an unhandled failure.
await page.goto("http://localhost:5180/register?lockAfter=1200", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3400);
const notNow = page.locator("button", { hasText: "Not now" });
let dismissed = "no prompt appeared";
if (await notNow.count()) {
  await notNow.click();
  await page.waitForTimeout(900);
  dismissed = (await page.locator(".lock-bar").count()) > 0
    ? "dismissed to a banner" : "dismissed, no banner";
}
await b.close();
console.table(rows);
console.log("after Not now:", dismissed);
console.log(unhandled.length ? `UNHANDLED: ${unhandled.join(" | ")}` : "no unhandled failures");
