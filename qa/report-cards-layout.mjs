/** Does any report card's text escape its own box? */
export default async function run(page, ui) {
  await ui.fill((await ui.snapshot()).match(/@(e\d+) textbox/)[1], "admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(3500);
  await page.goto("http://localhost:5180/reports");
  await page.waitForSelector(".rc-item", { timeout: 20000 });
  await page.waitForTimeout(1500);

  return await page.evaluate(() => {
    const cards = [...document.querySelectorAll(".rc-item")];
    const overflowing = [];
    let minH = 1e9, maxH = 0;
    for (const card of cards) {
      const box = card.getBoundingClientRect();
      minH = Math.min(minH, box.height);
      maxH = Math.max(maxH, box.height);
      for (const child of card.children) {
        const c = child.getBoundingClientRect();
        // More than a pixel outside the card in any direction is an escape.
        if (c.bottom > box.bottom + 1 || c.right > box.right + 1 || c.left < box.left - 1) {
          overflowing.push({
            card: card.querySelector(".rc-item-title")?.textContent?.trim(),
            spillBottom: Math.round(c.bottom - box.bottom),
            spillRight: Math.round(c.right - box.right),
          });
        }
      }
    }
    // Cards must also not sit on top of each other.
    const boxes = cards.map((c) => c.getBoundingClientRect());
    let overlaps = 0;
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        if (a.left < b.right - 1 && b.left < a.right - 1 &&
            a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps++;
      }
    return {
      cards: cards.length,
      overflowing: overflowing.slice(0, 6),
      overflowCount: overflowing.length,
      overlappingPairs: overlaps,
      cardHeights: { min: Math.round(minH), max: Math.round(maxH) },
      pageScrollsSideways: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    };
  });
}
