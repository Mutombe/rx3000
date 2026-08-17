/** Dosage shorthand in the dispensary: type `1 t tds pc`, get the sentence. */
export default async function run(page, ui) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);

  await page.goto(new URL("/dispense", page.url()).href);
  await page.waitForTimeout(3000);

  // Add a product so a script line with a directions field exists.
  const productSearch = page.locator('input[placeholder*="medicine" i], input[placeholder*="product" i]').first();
  out.foundProductSearch = await productSearch.count() > 0;
  if (!out.foundProductSearch) return { ...out, snapshot: (await ui.snapshot()).slice(0, 1200) };
  await productSearch.fill("Amoxicillin");
  await page.waitForTimeout(2000);
  // Results are clickable divs (.product-pick), not buttons — a button selector
  // matched nothing and the script line was never added.
  const first = page.locator(".product-pick").first();
  out.resultsFound = await first.count();
  if (out.resultsFound) { await first.click(); await page.waitForTimeout(1500); }

  const sig = page.locator(".sig input").first();
  out.sigFieldPresent = await sig.count() > 0;
  if (!out.sigFieldPresent) return { ...out, snapshot: (await ui.snapshot()).slice(0, 1200) };

  // The codes panel.
  await page.getByRole("button", { name: /^codes$/i }).first().click();
  await page.waitForTimeout(1200);
  out.bookOpened = await page.locator(".sig-book").count() > 0;
  out.codeCount = await page.locator(".sig-book button").count();
  out.categories = await page.locator(".sig-book h5").allInnerTexts();
  await page.getByRole("button", { name: /hide codes/i }).first().click();

  // Shorthand expands when the field is left.
  await sig.fill("1 t tds pc");
  await sig.blur();
  await page.waitForTimeout(2000);
  out.expandedTo = await sig.inputValue();
  out.undoOffered = await page.locator(".sig-note").innerText().catch(() => "none");

  // Ordinary English must pass through untouched.
  await sig.fill("One tablet at night");
  await sig.blur();
  await page.waitForTimeout(1800);
  out.plainEnglishKept = await sig.inputValue();
  return out;
}
