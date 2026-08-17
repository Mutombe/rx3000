export default async function run(page, ui) {
  await ui.fill((await ui.snapshot()).match(/@(e\d+) textbox/)[1], "admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(3500);
  await page.goto(new URL("/pos", page.url()).href);
  await page.waitForTimeout(2000);

  // Capture inside the page, so nothing depends on console forwarding.
  return await page.evaluate(async () => {
    const captured = [];
    const real = console.error;
    console.error = (...a) => { captured.push(a.map(String).join(" ")); real(...a); };
    const mod = await import("/src/api.ts");
    let shown = "";
    try { await mod.api.get("/api/no-such-thing"); } catch (e) { shown = e.message; }
    console.error = real;
    const rx = captured.filter((l) => l.includes("[RX3000]"));
    return {
      shownToUser: shown,
      consoleCaptured: rx.length,
      consoleLine: rx[0] ?? "(nothing logged)",
      // The technical detail must be in the console and NOT on screen.
      pathInConsole: rx.some((l) => l.includes("/api/no-such-thing")),
      pathInMessage: shown.includes("/api/no-such-thing"),
      statusInMessage: shown.includes("404"),
    };
  });
}
