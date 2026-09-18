/** A forgotten till code can be cleared, by a second person, from the screen
 *  where that person is.
 *
 *      node qa/clear-a-code.mjs       # needs the dev server on :5180
 *
 *  Changing a code costs the code, which is right, and would strand anybody who
 *  had forgotten theirs if there were no way back. The way back is that a
 *  manager can take a code away, and only take it away. Nobody can choose
 *  somebody else's, because an action carrying your name has to mean that
 *  person authorised it.
 *
 *  Driven rather than asserted about, because what matters here lives between
 *  the screen and the server: that the action asks before it acts, that it
 *  needs an authorisation, and that refusing that authorisation changes
 *  nothing.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const OUT = join(ROOT, "qa", "out");
const APP = "http://localhost:5180";
mkdirSync(OUT, { recursive: true });

let bad = 0;
const check = (ok, label, extra = "") => {
  if (!ok) bad++;
  console.log(`${ok ? "ok  " : "FAIL"}  ${label}${extra ? "   " + extra : ""}`);
};

/** Read the development database directly, for the two facts the API will not
 *  give up: setting somebody else's code, and reading whether they still have
 *  one. Both are refusals by design, which is the point of the feature. */
const inDb = (code) => execFileSync("python", ["-c", `
import sys
sys.path.insert(0, r"${join(ROOT, "backend")}")
from app.database import SessionLocal
from app.models import User
from app.services import pins
from app.tenancy import unscoped
db = SessionLocal()
with unscoped():
${code}
db.close()
`], { encoding: "utf8", cwd: join(ROOT, "backend") }).trim();

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });

await page.goto(`${APP}/login`);
await page.waitForTimeout(1500);
const fields = await page.locator("input").all();
await fields[0].fill("admin");
await fields[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(3500);

const call = async (method, path, body) => page.evaluate(
  async ([m, p, b]) => {
    const r = await fetch(p, {
      method: m,
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + (localStorage.getItem("rx5000_token") || ""),
      },
      body: b ? JSON.stringify(b) : undefined,
    });
    return { status: r.status, body: await r.text() };
  }, [method, path, body ?? null]);

const me = JSON.parse((await call("GET", "/api/auth/me")).body);
await call("POST", "/api/auth/pin", { pin: "8317", password: "admin123" });

// ---- find a branch with staff, and give one of them a code to lose ---------
const estate = JSON.parse((await call("GET", "/api/hq/overview?days=1")).body);
let subject = null;
for (const b of estate.branches ?? []) {
  const list = JSON.parse(
    (await call("GET", `/api/hq/branches/${b.branch_id}/people`)).body);
  if (list.people?.length) { subject = { branch: list.branch, person: list.people[0] }; break; }
}
check(!!subject, "a branch with staff exists to test against",
      subject ? `${subject.branch}: ${subject.person.full_name}` : "none found");
if (!subject) { await browser.close(); process.exit(1); }

const who = subject.person.username;
console.log(`      fixture: ${inDb(
  `    u = db.query(User).filter(User.username == "${who}").first()\n`
  + `    u.pin_hash = pins.hash_pin("8317")\n`
  + `    u.pin_failures = 0\n    u.pin_locked_until = None\n    db.commit()\n`
  + `    print("a code set for " + u.username)`)}`);

// ---- the screen -------------------------------------------------------------
await page.goto(`${APP}/head-office?tab=people`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2500);

// The tab opens on whichever branch is first, which may have nobody on it.
const pills = page.locator(".pill-tabs").last().locator("button");
for (let i = 0; i < await pills.count(); i++) {
  await pills.nth(i).click();
  await page.waitForTimeout(1500);
  if (await page.locator("td.hq-code").count()) break;
}

check(await page.locator("table.dt")
  .filter({ has: page.locator("th", { hasText: /till code/i }) }).count() > 0,
  "the people list has a till-code column");
const cells = await page.locator("td.hq-code").count();
check(cells > 0, "and every person carries their code's state", `${cells} rows`);
check(await page.locator("td.hq-code", { hasText: /none yet/i }).count() > 0,
      "somebody without one is told so, rather than left blank");
check(!(await page.locator("body").innerText()).includes("8317"),
      "and no code is printed on the screen");
await page.screenshot({ path: join(OUT, "people-codes.png") });

// ---- clearing asks, then needs an authorisation ----------------------------
const button = page.locator("td.hq-code button").first();
check(await button.count() > 0, "a person with a code has a way to clear it");

if (await button.count()) {
  await button.click();
  await page.waitForTimeout(800);
  const ask = await page.locator(".cf-box").first().innerText().catch(() => "");
  check(/clear/i.test(ask), "it asks before it acts",
        ask.replace(/\s+/g, " ").trim().slice(0, 58));
  check(/cannot choose a code for them/i.test(ask),
        "and says plainly what a manager cannot do");
  await page.screenshot({ path: join(OUT, "clear-confirm.png") });

  await page.getByRole("button", { name: /clear the code/i }).first().click();
  await page.waitForTimeout(1500);
  const boxes = await page.locator(".su-pin .pin-box").count();
  check(boxes === 4, "and then asks for an authorisation", `${boxes} boxes`);
  await page.screenshot({ path: join(OUT, "clear-stepup.png") });

  // Refusing it must leave the code exactly where it was.
  await page.getByRole("button", { name: /^cancel$/i }).first().click();
  await page.waitForTimeout(900);
  const after = inDb(
    `    u = db.query(User).filter(User.username == "${who}").first()\n`
    + `    print("set" if u.pin_hash else "cleared")`);
  check(after === "set", "cancelling the authorisation clears nothing", after);
}

// ---- and the endpoint refuses on its own account ----------------------------
const refused = await call("DELETE", `/api/auth/pin/${me.id}`);
check(refused.status === 428, "the endpoint refuses without an authorisation",
      String(refused.status));
check(JSON.parse((await call("GET", "/api/auth/pin")).body).pin_set === true,
      "and the code survives that refusal");

await browser.close();
console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
