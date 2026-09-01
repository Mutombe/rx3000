/** Branches: edit the record, view stock, transfer, receive. */
export default async function run(page) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);
  await page.goto(new URL("/branches", page.url()).href);
  await page.waitForSelector("tbody tr", { timeout: 20000 }).catch(() => {});
  out.branches = await page.locator("tbody tr").count();
  const text = await page.locator("tbody").innerText();
  out.flagsMissingPharmacist = /nobody named/.test(text);
  out.tableText = text.replace(/\s+/g, " ").slice(0, 160);

  // Set a responsible pharmacist: a field the API accepted and no screen offered.
  await page.getByRole("button", { name: /^edit$/i }).first().click();
  await page.waitForTimeout(700);
  const rp = page.locator(".modal input").filter({ hasNot: page.locator("[type=number]") });
  await page.locator('.modal input[placeholder*="accountable"]').fill("T. Moyo (PCZ 4471)");
  await page.locator(".modal .field").filter({ hasText: /^City/ }).locator("input").fill("Harare");
  await page.locator('.modal button[type="submit"]').click();
  await page.waitForTimeout(2500);
  out.saved = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 90);
  out.pharmacistNowShown = /T\. Moyo/.test(await page.locator("tbody").innerText());

  // Branch stock, with the group total.
  await page.getByRole("button", { name: /^stock$/i }).first().click();
  await page.waitForTimeout(2500);
  out.stockRows = await page.locator(".card:last-of-type tbody tr").count();
  out.stockHeaders = await page.locator(".card:last-of-type th").allInnerTexts();

  // Transfer, then receive it.
  await page.getByRole("button", { name: /transfer stock/i }).click();
  await page.waitForTimeout(700);
  // From the branch that actually holds the stock. Picking by index sent from
  // Bulawayo, which holds none, and the server rightly refused.
  const selects = page.locator(".modal select");
  await selects.first().selectOption({ label: "Main branch" });
  await page.waitForTimeout(500);
  await selects.last().selectOption({ label: "Bulawayo" });
  await page.locator('.modal input[placeholder="Search for a product"]').fill("Paracetamol");
  await page.waitForTimeout(1800);
  const pick = page.locator(".modal .st-results button").first();
  if (await pick.count()) await pick.click();
  await page.getByRole("button", { name: /send it/i }).click();
  await page.waitForTimeout(3000);
  out.transferred = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 150);
  out.inTransitShown = /In transit/.test(await page.locator("body").innerText());

  const rec = page.getByRole("button", { name: /confirm arrival/i }).first();
  out.receiveOffered = await rec.count() > 0;
  if (out.receiveOffered) {
    await rec.click();
    await page.waitForTimeout(900);
    const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /confirm it arrived/i }).first();
    out.receiveConfirm = (await page.locator(".modal, .cf-box").first().innerText().catch(() => ""))
      .replace(/\s+/g, " ").slice(0, 150);
    if (await yes.count()) { await yes.click(); await page.waitForTimeout(2500); }
    out.received = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 80);
  }
  return out;
}
