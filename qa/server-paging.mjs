/** Server paging: totals, page moves, debounced search, and the page reset. */
export default async function run(page) {
  const out = {};
  const calls = [];
  page.on("request", (r) => {
    if (/\/paged\?/.test(r.url())) calls.push(r.url().split("/api")[1]);
  });

  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForSelector(".topbar", { timeout: 25000 });

  await page.goto(new URL("/authorisations", page.url()).href);
  await page.waitForSelector("tbody tr", { timeout: 25000 });
  await page.waitForTimeout(1500);
  out.firstPageRows = await page.locator("tbody tr").count();
  out.pagerText = (await page.locator(".pagination, [class*=pagin]").first().innerText()
    .catch(() => "none")).replace(/\s+/g, " ").slice(0, 80);

  // Next page keeps the table on screen and changes the rows.
  const firstRef = await page.locator("tbody tr td").first().innerText();
  const next = page.getByRole("button", { name: /next/i }).first();
  if (await next.count()) {
    await next.click();
    await page.waitForTimeout(2000);
    out.secondPageRows = await page.locator("tbody tr").count();
    out.rowsChanged = (await page.locator("tbody tr td").first().innerText()) !== firstRef;
  }

  // Typing sends one request when it settles, not one per keystroke.
  const before = calls.length;
  await page.locator(".page-search").first().fill("");
  await page.locator(".page-search").first().type("AUTH-8VMK", { delay: 60 });
  await page.waitForTimeout(2200);
  out.requestsWhileTyping = calls.length - before;
  out.searchRows = await page.locator("tbody tr").count();
  out.backToPageOne = /page=1/.test(calls[calls.length - 1] ?? "");
  out.lastCall = calls[calls.length - 1];
  return out;
}
