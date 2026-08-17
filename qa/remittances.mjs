/** Remittances: shortfalls, advices, and importing one. */
export default async function run(page, ui) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);

  await page.goto(new URL("/remittances", page.url()).href);
  await page.waitForSelector(".pill-tabs button", { timeout: 20000 });
  await page.waitForTimeout(2500);

  out.tabLabel = await page.locator(".pill-tabs button").first().innerText();
  out.shortfallRows = await page.locator("tbody tr").count();
  const summary = await page.locator(".card .muted").first().innerText().catch(() => "");
  out.summary = summary.replace(/\s+/g, " ").slice(0, 120);
  // The scheme's reason must be readable next to the decision.
  out.reasonShown = await page.locator("tbody tr td").nth(6).innerText().catch(() => "none");
  // And our old pollution must be gone from it.
  out.reasonPolluted = /\|/.test(await page.locator("tbody").innerText().catch(() => ""));

  // Write one off.
  const off = page.getByRole("button", { name: /write off/i }).first();
  if (await off.count()) {
    await off.click();
    await page.waitForTimeout(900);
    const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /write it off/i }).first();
    out.writeOffConfirm = (await page.locator(".modal, .cf-box").first().innerText().catch(() => ""))
      .replace(/\s+/g, " ").slice(0, 150);
    if (await yes.count()) { await yes.click(); await page.waitForTimeout(2500); }
    out.afterWriteOff = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 90);
    out.rowsAfter = await page.locator("tbody tr").count();
  }

  // Advices tab
  await page.getByRole("button", { name: /^advices$/i }).click();
  await page.waitForTimeout(1500);
  out.adviceRows = await page.locator("tbody tr").count();

  // Import an advice.
  await page.getByRole("button", { name: /^import$/i }).click();
  await page.waitForTimeout(1200);
  await page.locator('input[placeholder*="PSMAS"]').fill("PSMAS_ZW");
  await page.locator('input[placeholder*="printed"]').fill("QA-ADVICE-001");
  await page.locator("textarea").fill(
    "claim_reference,amount_claimed,amount_paid,reason_code\nQA-CLAIM-1,100.00,80.00,LEVY");
  await page.getByRole("button", { name: /import the advice/i }).click();
  await page.waitForTimeout(3000);
  out.imported = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 120);
  return out;
}
