/** The VAT return, opened from the period it belongs to. */
export default async function run(page) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);
  await page.goto("http://localhost:5190/periods");
  await page.waitForSelector("tbody tr", { timeout: 20000 });
  await page.waitForTimeout(1200);
  out.periods = await page.locator("tbody tr").count();

  // The open period first: its return must carry the server's warning.
  await page.getByRole("button", { name: /vat return/i }).first().click();
  await page.waitForTimeout(2500);
  out.dialogTitle = await page.locator(".modal h2").innerText().catch(() => "none");
  out.warning = await page.locator(".modal .alert.warn").innerText().catch(() => "none");
  out.figures = (await page.locator(".modal table").innerText().catch(() => ""))
    .replace(/\s+/g, " ").slice(0, 200);
  await page.getByRole("button", { name: /^close$/i }).last().click();
  await page.waitForTimeout(600);

  // A closed period should produce a return with no warning.
  const rows = await page.locator("tbody tr").all();
  for (const r of rows) {
    const status = await r.innerText();
    if (/locked|closed/i.test(status)) {
      await r.getByRole("button", { name: /vat return/i }).click();
      await page.waitForTimeout(2500);
      out.closedTitle = await page.locator(".modal h2").innerText().catch(() => "none");
      out.closedWarning = await page.locator(".modal .alert.warn").count();
      out.closedFigures = (await page.locator(".modal table").innerText().catch(() => ""))
        .replace(/\s+/g, " ").slice(0, 160);
      break;
    }
  }
  return out;
}
