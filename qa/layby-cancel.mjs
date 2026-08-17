/** The cancel path: fee, step-up, refund, and stock back on the shelf. */
export default async function run(page) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);
  await page.goto(new URL("/laybys", page.url()).href);
  await page.waitForSelector(".pill-tabs button", { timeout: 20000 });

  // Raise one to cancel.
  await page.getByRole("button", { name: /raise a lay-by/i }).click();
  await page.waitForTimeout(600);
  await page.locator('.modal input[placeholder="Search by name"]').fill("Nomsa");
  await page.waitForTimeout(1700);
  await page.locator(".modal .st-results button").first().click();
  await page.locator('.modal input[placeholder="Search for a product"]').fill("Paracetamol");
  await page.waitForTimeout(1700);
  await page.locator(".modal .st-results button").first().click();
  const depositBox = page.locator(".modal .field").filter({ hasText: /Deposit taken now/ })
    .locator("input").first();
  await depositBox.fill("150");
  await page.getByRole("button", { name: /raise the lay-by/i }).click();
  await page.waitForTimeout(3000);

  await page.getByRole("button", { name: /^cancel$/i }).first().click();
  await page.waitForTimeout(900);
  const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /cancel the lay-by/i }).first();
  out.cancelConfirm = (await page.locator(".modal, .cf-box").first().innerText().catch(() => ""))
    .replace(/\s+/g, " ").slice(0, 150);
  if (await yes.count()) { await yes.click(); await page.waitForTimeout(1200); }

  // Fee dialog
  out.feeAsked = (await page.locator(".modal").innerText().catch(() => ""))
    .replace(/\s+/g, " ").slice(0, 150);
  const feeBox = page.locator('.modal input[type="number"]').first();
  if (await feeBox.count()) {
    await feeBox.fill("10");
    await page.waitForTimeout(400);
    out.refundLine = await page.locator(".modal .small").innerText().catch(() => "none");
    await page.getByRole("button", { name: /continue/i }).click();
    await page.waitForTimeout(1500);
  }

  // Step-up
  const pw = page.locator('.modal input[type="password"]').first();
  out.stepUpAsked = await pw.count() > 0;
  if (out.stepUpAsked) {
    out.stepUpHeading = await page.locator(".modal h2").first().innerText();
    await pw.fill("admin123");
    await page.locator('.modal button[type="submit"]').click();
    await page.waitForTimeout(3000);
  }
  out.result = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 180);
  return out;
}
