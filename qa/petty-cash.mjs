/** Petty cash: record a payout, see it counted against the drawer. */
export default async function run(page) {
  const out = {};
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);
  await page.goto(new URL("/shifts", page.url()).href);
  await page.waitForSelector(".card", { timeout: 20000 });
  await page.waitForTimeout(2500);

  out.sectionPresent = /Petty cash/.test(await page.locator("body").innerText());
  await page.getByRole("button", { name: /record a movement/i }).click();
  await page.waitForTimeout(600);

  // Default direction is out of the drawer, and the receipt tick only applies then.
  out.receiptTickShown = await page.locator('.pc-form input[type="checkbox"]').count() > 0;
  await page.locator(".pc-form .field").filter({ hasText: /^Amount/ }).locator("input").fill("12.50");
  await page.locator(".pc-form .field").filter({ hasText: /What it was for/ }).locator("input")
    .fill("Window cleaner, invoice 4471");
  out.buttonSaysPayout = await page.getByRole("button", { name: /record the payout/i }).count() > 0;

  // Switching to "into the drawer" must hide the receipt question.
  await page.locator(".pc-form select").first().selectOption({ label: "Into the drawer" });
  await page.waitForTimeout(400);
  out.receiptHiddenForTopUp = await page.locator('.pc-form input[type="checkbox"]').count() === 0;
  out.buttonSaysTopUp = await page.getByRole("button", { name: /record the top-up/i }).count() > 0;

  // Back to a payout and save it — this is step-up gated.
  await page.locator(".pc-form select").first().selectOption({ label: "Out of the drawer" });
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /record the payout/i }).click();
  await page.waitForTimeout(1800);
  const pw = page.locator('.modal input[type="password"]').first();
  out.stepUpAsked = await pw.count() > 0;
  if (out.stepUpAsked) {
    out.stepUpHeading = await page.locator(".modal h2").first().innerText();
    await pw.fill("admin123");
    await page.locator('.modal button[type="submit"]').click();
    await page.waitForTimeout(3000);
  }
  out.saved = (await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []))
    .join(" | ").slice(0, 110);
  const body = await page.locator("body").innerText();
  out.netShown = /Net effect on the drawer/.test(body);
  out.noReceiptFlagged = /Payouts with no receipt/.test(body);
  out.rowShowsWho = /System Administrator/.test(body);
  out.amountNegative = /-\$?12\.50|\(\$?12\.50\)|\$-12\.50/.test(body);
  return out;
}
