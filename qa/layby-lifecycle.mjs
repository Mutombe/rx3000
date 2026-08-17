/** Lay-bys: raise, pay, hand over. Five endpoints no screen had called.
 *  Also checks the minimum-deposit warning fires before the server refuses.
 */
export default async function run(page, ui) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);

  await page.goto("http://localhost:5180/laybys");
  await page.waitForSelector(".pill-tabs button", { timeout: 20000 });
  await page.waitForTimeout(1500);
  // Scope to the listing card: the raise modal contains its own table, and
  // "tbody tr" counted those too.
  const listRows = () => page.locator(".card .cu-scroll tbody tr").count();
  out.openRows = await listRows();

  await page.getByRole("button", { name: /raise a lay-by/i }).click();
  await page.waitForTimeout(600);

  // Customer
  await page.locator('.modal input[placeholder="Search by name"]').fill("Nomsa");
  await page.waitForTimeout(1800);
  out.patientResults = await page.locator(".modal .st-results button").count();
  await page.locator(".modal .st-results button").first().click();
  await page.waitForTimeout(400);

  // Goods
  await page.locator('.modal input[placeholder="Search for a product"]').fill("Paracetamol");
  await page.waitForTimeout(1800);
  await page.locator(".modal .st-results button").first().click();
  await page.waitForTimeout(500);
  out.lineAdded = await page.locator(".lb-lines tr").count();

  // The deposit field by its label. The first number input in this modal is the
  // line quantity, so .first() was setting the wrong box entirely.
  const depositBox = page.locator(".modal .field").filter({ hasText: /Deposit taken now/ })
    .locator("input").first();
  await depositBox.fill("1");
  await page.waitForTimeout(500);
  out.minimumWarning = await page.locator(".modal .alert.warn").innerText().catch(() => "none");

  // Pay the full minimum instead.
  const totalText = await page.locator(".lb-lines b").last().innerText();
  const totalNum = Number(totalText.replace(/[^0-9.]/g, ""));
  await depositBox.fill(String((totalNum * 0.25).toFixed(2)));
  await page.waitForTimeout(400);
  out.warningGoneAtQuarter = await page.locator(".modal .alert.warn").count() === 0;

  await page.getByRole("button", { name: /raise the lay-by/i }).click();
  await page.waitForTimeout(3000);
  out.raised = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 160);
  out.rowsAfter = await listRows();

  // Pay off the balance, then hand over.
  const take = page.getByRole("button", { name: /take payment/i }).first();
  if (await take.count()) {
    await take.click();
    await page.waitForTimeout(800);
    out.payDefault = await page.locator('.modal input[type="number"]').first().inputValue();
    out.payModalTitle = await page.locator(".modal h2").innerText();
    await page.locator('.modal button[type="submit"]').click();
    await page.waitForTimeout(2500);
    out.paid = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 120);
  }
  const hand = page.getByRole("button", { name: /hand over/i }).first();
  out.handOverOffered = await hand.count() > 0;
  if (out.handOverOffered) {
    await hand.click();
    await page.waitForTimeout(900);
    const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /hand over the goods/i }).first();
    if (await yes.count()) { await yes.click(); await page.waitForTimeout(2500); }
    out.completed = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 140);
  }
  return out;
}
