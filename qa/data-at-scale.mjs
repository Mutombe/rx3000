/** Does the layout survive data it was not designed for?
 *
 *      node <skill-dir>/browser.mjs http://localhost:5180 --script qa/data-at-scale.mjs
 *
 *  Two failure modes, checked separately because they are fixed differently.
 *
 *  ONE VALUE TOO BIG. A 173-character product name is written into the catalogue
 *  and every listed screen is measured. The name must clip to one line with the
 *  whole value on the title attribute, the row must not grow taller, and the page
 *  must not scroll sideways: a wide table scrolls inside its own box instead.
 *
 *  What this caught when it was first run:
 *
 *    - Nothing overflowed and nothing looked wrong, because
 *      `html { overflow-x: hidden }` was hiding sideways scroll. The symptom was
 *      row height: the long name wrapped to three lines and made its row three
 *      times taller than its neighbours.
 *    - A `max-width` on a block inside a `<td>` did nothing: with
 *      `table-layout: auto` the browser sizes the column to its content and
 *      ignores a descendant's max-width. The table went from 956px to 1863px
 *      while the row height held, which is the failure that looks like a fix.
 *    - With fixed layout, columns divided equally: a product name got the same
 *      95px as a quantity. Pinning numbers in pixels then over-subscribed the
 *      table and squeezed two columns to 25px. Weighted shares plus a declared
 *      minimum width, below which the container scrolls, is what actually held.
 *    - At a 118px minimum, "$5,665,724.00" still clipped. Numbers have to be
 *      legible at any magnitude, so the minimum is 136px.
 *
 *  TOO MANY ROWS. Every size parameter is clamped server-side, so no screen can
 *  ask for the table. Checked by requesting an absurd page and counting what
 *  comes back.
 */
const PAGES = ["/stock", "/patients", "/laybys", "/branches", "/remittances"];
const LONG = "Paracetamol 500mg film-coated tablets, blister pack of twenty-four, "
  + "manufactured under licence for the Southern African regional market, "
  + "batch-tracked, cold-chain exempt XXL";

export default async function run(page) {
  const out = { value: {}, collection: {} };

  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForSelector(".topbar", { timeout: 25000 });

  // ---- bound the collection -------------------------------------------------
  out.collection = await page.evaluate(async () => {
    const token = localStorage.getItem("rx3000_token");
    const ask = async (url) => {
      const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      const d = await r.json();
      return Array.isArray(d) ? d.length : (d.items?.length ?? d.results?.length ?? null);
    };
    return {
      productsAsked100k: await ask("/api/products?limit=100000"),
      pagedAsked5k: await ask("/api/products/paged?per_page=5000"),
      patientsAsked999: await ask("/api/patients?q=a&limit=999"),
    };
  });

  // ---- bound the value -----------------------------------------------------
  for (const path of PAGES) {
    await page.goto(new URL(path, page.url()).href);
    await page.waitForTimeout(2600);
    out.value[path] = await page.evaluate(() => {
      const rows = [...document.querySelectorAll("tbody tr")];
      const heights = rows.map((r) => Math.round(r.getBoundingClientRect().height));
      const clipped = [...document.querySelectorAll(".clip")];
      return {
        rows: rows.length,
        // A ragged table is the tell. Equal heights mean nothing wrapped.
        rowHeights: [...new Set(heights)].slice(0, 4),
        pageScrollsSideways:
          document.documentElement.scrollWidth > document.documentElement.clientWidth,
        clippedCells: clipped.length,
        clippedWithoutTooltip: clipped.filter(
          (n) => n.scrollWidth > n.clientWidth + 1 && !n.getAttribute("title")).length,
        // Overflow that nobody asked for. A cell holding a `.clip` overflows by
        // design, that is the guard working, so counting those as faults made
        // the check report 25 problems on a page with none. Only unguarded
        // overflow counts.
        strayOverflow: [...document.querySelectorAll("td, .card")]
          .filter((n) => n.scrollWidth > n.clientWidth + 1
            && !n.querySelector(".clip")
            // A card holding a scroll box is meant to be wider inside than out;
            // that is where the scroll was deliberately put.
            && !n.querySelector(".cu-scroll, .dt-scroll, .age-scroll, .rr-scroll")).length,
      };
    });
  }
  return out;
}
