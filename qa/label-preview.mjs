/** The label preview, looked at rather than reasoned about.
 *
 *  Checks the things only a running browser can answer: that the fetch happens
 *  once (an inline onClose in the effect's dependency list would loop forever),
 *  that the directions actually appear on the sticker, and that nothing
 *  overflows a 70×40mm label: the size a real sticker has to be.
 */
export default async function run(page, ui) {
  const out = { steps: [] };
  const say = (s, d) => out.steps.push({ [s]: d });

  let labelCalls = 0;
  page.on("request", (r) => {
    if (/\/labels(\?|$)/.test(r.url())) labelCalls++;
  });

  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);

  // RX260801167: a script with a real dispensing behind it.
  await page.goto(new URL("/dispense?reprint=1167", page.url()).href);
  await page.waitForSelector(".lbl", { timeout: 20000 }).catch(() => {});

  const labels = await page.locator(".lbl").count();
  say("stickersRendered", labels);
  if (!labels) return { ...out, error: "no sticker rendered", snapshot: await ui.snapshot() };

  say("heading", await page.locator(".modal h2").first().innerText());
  say("summary", await page.locator(".modal .muted").first().innerText());
  say("directions", await page.locator(".lbl-dose").first().innerText());
  say("checkedBy", await page.locator(".lbl-meta span").last().innerText());

  // A sticker is a fixed physical size; text that spills off it is text the
  // patient never reads.
  const spill = await page.locator(".lbl").evaluateAll((ns) =>
    ns.filter((n) => n.scrollHeight > n.clientHeight + 1
                  || n.scrollWidth > n.clientWidth + 1).length);
  say("stickersOverflowing", spill);

  const box = await page.locator(".lbl").first().boundingBox();
  say("sizePx", box && { w: Math.round(box.width), h: Math.round(box.height) });

  // Copies must multiply the count shown, so nobody prints nine by accident.
  await page.locator(".lbl-copies input").fill("3");
  await page.waitForTimeout(400);
  say("summaryWith3Copies", await page.locator(".modal .muted").first().innerText());

  // One fetch, not one per render.
  say("labelRequests", labelCalls);

  await page.waitForTimeout(800);
  say("labelRequestsAfterSettling", labelCalls);

  return out;
}
