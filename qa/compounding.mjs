/** Compounding: costing, schedule inheritance, and making one up. */
export default async function run(page) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);
  await page.goto("http://localhost:5190/compounding");
  await page.waitForSelector("tbody tr", { timeout: 20000 }).catch(() => {});
  out.formulae = await page.locator("tbody tr").count();

  // Open the first formula: costing should appear with the inherited schedule.
  await page.locator("tbody .btn.ghost").first().click();
  await page.waitForTimeout(2500);
  out.scheduleBadge = await page.locator(".cu-head .badge").innerText().catch(() => "none");
  out.scheduleSource = await page.locator(".card .muted").last().innerText().catch(() => "none");
  out.ingredientRows = await page.locator(".card table tbody tr").count();
  out.costFooter = (await page.locator("tfoot").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 120);

  // Doubling the batches must change the cost.
  const batch = page.locator('.field input[type="number"]').first();
  const before = await page.locator("tfoot").innerText();
  await batch.fill("2");
  await page.waitForTimeout(2500);
  const after = await page.locator("tfoot").innerText();
  out.costChangedWithBatches = before !== after;
  out.costAtTwo = after.replace(/\s+/g, " ").slice(0, 100);

  // Make it up — the confirmation must name the schedule for a controlled one.
  await batch.fill("1");
  await page.waitForTimeout(2000);
  const make = page.getByRole("button", { name: /make it up/i }).first();
  out.canPrepare = await make.isEnabled().catch(() => false);
  if (out.canPrepare) {
    await make.click();
    await page.waitForTimeout(900);
    out.confirmText = (await page.locator(".modal, .cf-box").first().innerText().catch(() => ""))
      .replace(/\s+/g, " ").slice(0, 220);
    const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /make it up/i }).first();
    if (await yes.count()) { await yes.click(); await page.waitForTimeout(3000); }
    out.prepared = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 140);
  }
  return out;
}
