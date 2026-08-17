/** The fiscalisation screen: does it render, and does the day actually cycle?
 *  Nine endpoints had no screen at all before this, so nothing here had ever been
 *  exercised through a browser.
 */
export default async function run(page, ui) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);

  await page.goto(new URL("/fiscal", page.url()).href);
  await page.waitForSelector(".fs-route", { timeout: 20000 }).catch(() => {});

  const body = await page.locator("body").innerText();
  out.route = await page.locator(".fs-route").innerText().catch(() => "absent");
  out.whoFiles = /Who files/i.test(body);
  out.chainStated = /receipts verify|chain breaks/i.test(body);
  out.closedDaysRows = await page.locator("tbody tr").count();

  // The day must cycle. Whichever state it is in, do the other thing.
  const openBtn = page.getByRole("button", { name: /open the trading day/i });
  const closeBtn = page.getByRole("button", { name: /close the day/i });
  out.startedWith = (await openBtn.count()) ? "no open day" : "a day open";

  if (await openBtn.count()) {
    await openBtn.click();
    await page.waitForTimeout(2500);
    out.afterOpen = await page.locator(".fs-daynum").innerText().catch(() => "no day number");
  }

  // Now close it, confirming the dialog, and check the Z-report lands.
  const close2 = page.getByRole("button", { name: /close the day/i });
  if (await close2.count()) {
    await close2.click();
    await page.waitForTimeout(1000);
    const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /close the day/i }).first();
    out.confirmShown = await yes.count() > 0;
    if (out.confirmShown) {
      out.confirmText = await page.locator(".modal, .cf-box").first().innerText()
        .then((t) => t.replace(/\s+/g, " ").slice(0, 160));
      await yes.click();
      await page.waitForTimeout(3000);
    }
    out.afterClose = /No day is open/i.test(await page.locator("body").innerText());
    out.toast = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => [])).join(" | ").slice(0, 120);
  }

  out.overflow = await page.locator(".card").evaluateAll(
    (ns) => ns.filter((n) => n.scrollWidth > n.clientWidth + 1).length);
  return out;
}
