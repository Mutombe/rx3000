export default async function run(page, ui) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);
  await page.goto("http://localhost:5180/shifts");
  await page.waitForTimeout(2500);

  out.buttons = (await ui.snapshot()).split("\n").filter((l) => /button/.test(l));

  // Count something, then commit.
  const boxes = page.locator(".cu-grid input, .cu-coin input, table input[type=number]");
  out.countBoxes = await boxes.count();
  if (out.countBoxes) await boxes.first().fill("5");

  const commit = page.getByRole("button", { name: /commit|finish|cash.?up|count/i }).first();
  out.commitLabel = await commit.innerText().catch(() => "none");
  await commit.click();
  await page.waitForTimeout(1200);

  // A confirm dialog may stand in the way.
  const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /yes|commit|confirm|count/i }).first();
  if (await yes.count()) { out.confirmed = await yes.innerText(); await yes.click(); }
  await page.waitForTimeout(3000);

  const text = await page.locator("body").innerText();
  out.reconciliationShown = /Counted|Difference|drawer/i.test(text);
  out.runLabel = await page.locator(".cu-run").innerText().catch(() => "absent");

  const showBtn = page.getByRole("button", { name: /invoices in this run/i });
  out.invoiceButton = await showBtn.count() > 0;
  if (out.invoiceButton) {
    await showBtn.click();
    await page.waitForTimeout(2500);
    out.runListRendered = await page.locator(".cu-run-list").count() > 0;
    out.runListText = await page.locator(".cu-run-list p").innerText().catch(() => "none");
  }
  return out;
}
