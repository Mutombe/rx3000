/** Claiming: batch, send, settle, and the MMAP switch.
 *  Thirteen endpoints that no screen had ever called.
 */
export default async function run(page, ui) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);

  await page.goto("http://localhost:5180/claiming");
  // Wait for content, not a container — .card is also the skeleton.
  await page.waitForSelector(".pill-tabs button", { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(2500);
  out.batchRows = await page.locator("tbody tr").count();
  out.unbatchedShown = /Waiting to be batched/i.test(await page.locator("body").innerText());

  // Create a batch from whatever is unbatched.
  const create = page.getByRole("button", { name: /create batch/i }).first();
  if (await create.count()) {
    await create.click();
    await page.waitForTimeout(1000);
    const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /create the batch/i }).first();
    out.batchConfirm = (await page.locator(".modal, .cf-box").first().innerText().catch(() => ""))
      .replace(/\s+/g, " ").slice(0, 140);
    if (await yes.count()) { await yes.click(); await page.waitForTimeout(3000); }
    out.afterCreate = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 120);
  } else {
    out.afterCreate = "nothing unbatched";
  }

  // Send the first open batch, then record a short payment against it.
  const send = page.getByRole("button", { name: /^send$/i }).first();
  if (await send.count()) {
    await send.click();
    await page.waitForTimeout(900);
    const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /send the batch/i }).first();
    if (await yes.count()) { await yes.click(); await page.waitForTimeout(2500); }
    out.sent = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 100);
  }

  const record = page.getByRole("button", { name: /record payment/i }).first();
  if (await record.count()) {
    await record.click();
    await page.waitForTimeout(900);
    const amount = page.locator('.modal input[type="number"]').first();
    out.defaultedToClaimed = await amount.inputValue();
    await amount.fill(String(Math.max(0, Number(out.defaultedToClaimed) - 25)));
    await page.waitForTimeout(400);
    out.shortWarning = await page.locator(".modal .alert.warn").innerText().catch(() => "none");
    await page.locator('.modal button[type="submit"]').first().click();
    await page.waitForTimeout(2500);
    out.settled = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 120);
  }

  // The fee-model tab: the MMAP switch.
  await page.goto("http://localhost:5180/claiming?tab=models");
  await page.waitForSelector(".fm-model", { timeout: 20000 }).catch(() => {});
  out.models = await page.locator(".fm-model").count();
  out.tierRows = await page.locator(".fm-tiers tbody tr").count();
  const mmap = page.locator(".fm-mmap input").first();
  out.mmapBefore = await mmap.isChecked().catch(() => "absent");
  if (await mmap.count()) {
    await mmap.click();
    await page.waitForTimeout(900);
    const yes = page.locator(".modal button, .cf-box button").filter({ hasText: /apply the cap|remove the cap/i }).first();
    out.mmapConfirm = (await page.locator(".modal, .cf-box").first().innerText().catch(() => ""))
      .replace(/\s+/g, " ").slice(0, 130);
    if (await yes.count()) { await yes.click(); await page.waitForTimeout(1800); }
    // Changing how claims are priced asks for a password. Answer it.
    const pw = page.locator('.modal input[type="password"]').first();
    out.stepUpAsked = await pw.count() > 0;
    if (out.stepUpAsked) {
      out.stepUpHeading = await page.locator(".modal h2").first().innerText();
      await pw.fill("admin123");
      await page.locator('.modal button[type="submit"]').first().click();
      await page.waitForTimeout(3000);
    }
    out.mmapAfter = await page.locator(".fm-mmap input").first().isChecked().catch(() => "gone");
    out.mmapToast = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 90);
  }
  return out;
}
