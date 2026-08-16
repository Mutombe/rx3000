/** The whole offline story, driven as a cashier would.
 *
 *      node <skill-dir>/browser.mjs http://localhost:5180 --script qa/offline-sale.mjs
 *
 *  Online first so the catalogue caches, then the server is cut, then a cash
 *  sale is taken and held, then the line comes back and the queue drains. The
 *  point of the last step is the one that is easy to get wrong: the sale must
 *  arrive exactly once, however many times the till retried it.
 */
export default async function run(page, ui) {
  const out = {};

  await ui.fill((await ui.snapshot()).match(/@(e\d+) textbox/)[1], "admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(3500);

  // ---- online: let the catalogue cache itself
  await page.goto("http://localhost:5180/pos");
  await page.waitForSelector(".scan-input", { timeout: 20000 });
  await page.waitForTimeout(6000);
  out.cached = await page.evaluate(async () => {
    const db = await new Promise((res, rej) => {
      const r = indexedDB.open("rx3000-offline", 1);
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    return await new Promise((res) => {
      const r = db.transaction("products", "readonly").objectStore("products").count();
      r.onsuccess = () => res(r.result);
      r.onerror = () => res(-1);
    });
  });

  const salesBefore = await page.evaluate(async () => {
    const r = await fetch("/api/pos/sales?limit=1", {
      headers: { Authorization: "Bearer " + localStorage.getItem("rx3000_token") },
    });
    return (await r.json())[0]?.id ?? null;
  });
  out.latestSaleIdBefore = salesBefore;

  // ---- cut the line
  await page.route("**/api/health", (r) => r.abort());
  await page.waitForTimeout(7000);
  out.bannerOffline = await page.locator(".conn-banner").innerText().catch(() => "NO BANNER");

  // ---- scan from the local catalogue and take cash
  await page.locator(".scan-input").fill("6009876500011");
  await page.locator(".scan-input").press("Enter");
  await page.waitForTimeout(2500);
  out.cartOffline = await page.locator("table").first().innerText().catch(() => "");

  const tender = page.locator('input[type="number"]').last();
  if (await tender.count()) await tender.fill("100");
  const pay = page.locator("button", { hasText: /complete|charge|pay|checkout/i }).first();
  out.foundPayButton = await pay.count();
  if (await pay.count()) {
    await pay.click();
    await page.waitForTimeout(3000);
  }
  out.toastsAfterSale = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".toast")).map((t) => t.textContent.trim()));
  out.queued = await page.evaluate(async () => {
    const db = await new Promise((res) => {
      const r = indexedDB.open("rx3000-offline", 1);
      r.onsuccess = () => res(r.result);
    });
    return await new Promise((res) => {
      const r = db.transaction("queue", "readonly").objectStore("queue").count();
      r.onsuccess = () => res(r.result);
      r.onerror = () => res(-1);
    });
  });

  // ---- line returns; the queue must drain, exactly once
  await page.unroute("**/api/health");
  await page.waitForTimeout(12000);
  out.queueAfterReconnect = await page.evaluate(async () => {
    const db = await new Promise((res) => {
      const r = indexedDB.open("rx3000-offline", 1);
      r.onsuccess = () => res(r.result);
    });
    return await new Promise((res) => {
      const r = db.transaction("queue", "readonly").objectStore("queue").count();
      r.onsuccess = () => res(r.result);
      r.onerror = () => res(-1);
    });
  });
  out.bannerAfter = await page.locator(".conn-banner").innerText().catch(() => "(none)");

  out.newSales = await page.evaluate(async (before) => {
    const r = await fetch("/api/pos/sales?limit=10", {
      headers: { Authorization: "Bearer " + localStorage.getItem("rx3000_token") },
    });
    const rows = await r.json();
    return rows.filter((s) => before === null || s.id > before)
      .map((s) => ({ id: s.id, number: s.sale_number, total: s.total }));
  }, salesBefore);

  return out;
}
