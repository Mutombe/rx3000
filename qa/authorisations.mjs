/** Authorisations: request one, check it, draw against it.
 *  Run against the clean pair on 5190 -> 8188, because 8177 still serves old code.
 */
export default async function run(page, ui) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);

  await page.goto(new URL("/authorisations", page.url()).href);
  await page.waitForSelector("tbody tr", { timeout: 20000 }).catch(() => {});
  out.rows = await page.locator("tbody tr").count();
  out.statuses = [...new Set(await page.locator("tbody .badge").allInnerTexts())];
  // A refusal must show why.
  const bodyText = await page.locator("tbody").innerText();
  out.showsRefusalReason = /not a covered indication|benefit|not approved/i.test(bodyText);

  // Check the first row.
  await page.getByRole("button", { name: /^check$/i }).first().click();
  await page.waitForTimeout(2500);
  out.checkToast = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 130);

  // Request a new one.
  await page.getByRole("button", { name: /request an authorisation/i }).click();
  await page.waitForTimeout(700);
  await page.locator(".modal .field").filter({ hasText: /^Policy number/ }).locator("input").fill("987654321");
  await page.locator('.modal input[placeholder="Search for a product"]').fill("Amoxicillin");
  await page.waitForTimeout(1800);
  const prod = page.locator(".modal .st-results button").first();
  if (await prod.count()) await prod.click();
  await page.locator(".modal .field").filter({ hasText: /Diagnosis/ }).locator("input").fill("E11.9");
  await page.locator(".modal textarea").fill("Chronic therapy, established patient.");
  await page.getByRole("button", { name: /send the request/i }).click();
  await page.waitForTimeout(4000);
  out.decision = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 160);
  out.rowsAfter = await page.locator("tbody tr").count();

  // Draw against an approved one if there is one.
  const draw = page.getByRole("button", { name: /^draw$/i }).first();
  out.drawOffered = await draw.count() > 0;
  if (out.drawOffered) {
    await draw.click();
    await page.waitForTimeout(900);
    out.drawBlurb = (await page.locator(".modal .muted").first().innerText()).replace(/\s+/g, " ").slice(0, 130);
    await page.locator('.modal button[type="submit"]').click();
    await page.waitForTimeout(2500);
    out.drawn = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
      .join(" | ").slice(0, 90);
  }
  return out;
}
