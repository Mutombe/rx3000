/** The stock take: open, count blind, close with a second person.
 *  Six endpoints that no screen had ever called.
 *
 *  Counts Paracetamol at its true on-hand (19307) so that closing posts a zero
 *  variance — the close path is exercised without moving anybody's stock.
 */
export default async function run(page, ui) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);

  await page.goto("http://localhost:5180/stock-take");
  await page.waitForSelector(".card h3", { timeout: 20000 });
  await page.waitForTimeout(1200);

  const openBtn = page.getByRole("button", { name: /open a stock take/i });
  out.startedClean = await openBtn.count() > 0;
  if (out.startedClean) { await openBtn.click(); await page.waitForTimeout(2500); }
  out.reference = await page.locator(".cu-head h3").innerText().catch(() => "none");

  // Search must not reveal quantities.
  await page.locator('input[placeholder*="Name"]').fill("Paracetamol");
  await page.waitForTimeout(1800);
  const resultsText = await page.locator(".st-results").innerText().catch(() => "");
  out.resultsShown = resultsText.split("\n").length;
  out.searchLeaksQuantity = /\b19307\b|on hand/i.test(resultsText);

  await page.locator(".st-results button").first().click();
  await page.waitForTimeout(700);
  out.pickedShown = await page.locator(".st-picked b").innerText().catch(() => "none");
  // Before entering anything, the expected figure must not be on the page.
  out.expectedVisibleBeforeCount = /19307/.test(await page.locator("body").innerText());

  await page.locator('input[type="number"]').first().fill("19307");
  await page.getByRole("button", { name: /record the count/i }).click();
  await page.waitForTimeout(2500);
  out.afterCount = await page.locator(".st-note").innerText().catch(() => "none");
  out.tableRows = await page.locator("tbody tr").count();

  // Closing needs a second person: stocktake.close forbids self-approval.
  await page.getByRole("button", { name: /close and adjust stock/i }).click();
  await page.waitForTimeout(1000);
  const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /close and adjust/i }).first();
  out.closeConfirm = (await page.locator(".modal, .cf-box").first().innerText().catch(() => ""))
    .replace(/\s+/g, " ").slice(0, 150);
  if (await yes.count()) { await yes.click(); await page.waitForTimeout(2000); }

  const approver = page.locator('.modal input').first();
  out.askedForApprover = (await page.locator(".modal").innerText().catch(() => ""))
    .replace(/\s+/g, " ").slice(0, 170);
  if (await approver.count()) {
    await approver.fill("pharmacist");
    await page.locator('.modal input[type="password"]').fill("pharm123");
    await page.locator('.modal button[type="submit"]').click();
    await page.waitForTimeout(3000);
  }
  out.afterClose = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 140);
  out.backToStart = await page.getByRole("button", { name: /open a stock take/i }).count() > 0;
  return out;
}
