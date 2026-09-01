/** Layout audit: every real route, at every width this is used at.
 *
 *  Written after a sweep reported "29 pages, 0 faults" while the dispensary was
 *  visibly broken. Two reasons it lied, both now guarded against here:
 *
 *  1. The page list was invented. `/dispensary` is not a route — the app is
 *     mounted at `/dispense`, so the audit loaded the dashboard fallback and
 *     cheerfully declared it clean, 29 times. Every route below is asserted to
 *     render its own heading; a route that falls through is a FAILURE, not a
 *     silent pass.
 *  2. It only measured 1280px. A laptop at a high device-pixel ratio has far
 *     fewer CSS pixels than its screenshot suggests, and the faults live there.
 *
 *  Run:  node qa/layout-audit.mjs            (needs the app running on 5180)
 */
/** Widths to check. The full matrix (routes x tabs x 5 widths) takes long enough
 *  to outlive some runners, so it can be split:
 *      AUDIT_WIDTHS=900,1100  node qa/layout-audit.mjs
 *  Unset runs all five. */
export const WIDTHS = (process.env.AUDIT_WIDTHS || "900,1100,1280,1440,1680")
  .split(",").map((w) => Number(w.trim())).filter(Boolean);

export const ROUTES = [
  "/", "/dispense", "/patients", "/to-follows", "/repeats", "/compounding",
  "/register", "/deliveries", "/pos", "/shifts", "/fiscal", "/laybys",
  "/stock", "/orders", "/stock-take", "/branches", "/claiming",
  "/authorisations", "/claims-held", "/remittances", "/reconciliation",
  "/ledger", "/periods", "/reports", "/leads", "/pipeline", "/contacts/1",
  "/marketing", "/helpdesk", "/reminders", "/system", "/admin", "/profile",
];

const AUDIT = () => {
  const de = document.documentElement;
  const r = {
    heading: document.querySelector("main h1")?.textContent?.trim().slice(0, 40) ?? null,
    spillsOutsideTable: [],
    pageScrollsSideways: Math.max(0, de.scrollWidth - de.clientWidth),
    slicedControls: [], crushedCells: [], lowContrast: [], unpagedTables: [],
    clippedActionCells: [],
  };

  // --- a control severed by something that clips ---
  for (const el of document.querySelectorAll("main button, main a.btn")) {
    const b = el.getBoundingClientRect();
    if (!b.width || !b.height) continue;
    let n = el.parentElement, hit = null, scrollable = false;
    while (n && n !== document.body) {
      const cs = getComputedStyle(n);
      // A scrollable ancestor ends the search: whatever sits outside it is
      // reachable by scrolling, which is the guard this app deliberately uses
      // for wide tables. Walking past it found `.shell`'s `overflow: hidden`
      // several levels up and called a scrollable table's buttons severed.
      if (["auto", "scroll"].includes(cs.overflowX)) { scrollable = true; break; }
      if (["hidden", "clip"].includes(cs.overflowX)) {
        const box = n.getBoundingClientRect();
        const lost = Math.max(0, b.right - box.right) + Math.max(0, box.left - b.left);
        if (lost > 1) { hit = { lost: Math.round(lost), by: n.tagName + "." + (n.className || "").toString().split(" ")[0] }; break; }
      }
      n = n.parentElement;
    }
    // Only when nothing between here and the page can scroll. A control past the
    // right edge of a table that scrolls is reachable; a control past the right
    // edge of the page with nothing to scroll is lost.
    if (!hit && !scrollable && b.right > de.clientWidth + 1)
      hit = { lost: Math.round(b.right - de.clientWidth), by: "viewport" };
    if (hit) r.slicedControls.push({ label: (el.textContent || "").trim().slice(0, 20), ...hit });
  }

  // --- a value wrapped into a tower ---
  //
  // Counted from the text's own client rects, one per rendered line. The
  // obvious measure — the cell's height divided by its line-height — is the
  // ROW's height, set by whatever the tallest cell in that row happens to be,
  // so a single stacked cell made every plain cell beside it look crushed. That
  // reported 400 faults on a page and sent me looking for a wrap that was not
  // happening.
  for (const td of document.querySelectorAll("main td")) {
    if (td.children.length) continue;              // stacked renders are deliberate
    const text = (td.textContent || "").trim();
    if (!text) continue;
    const range = document.createRange();
    range.selectNodeContents(td);
    // Distinct top offsets, not rect count. getClientRects() returns one rect
    // per text box, and adjacent text nodes on the SAME line each get their own
    //, so counting rects reported "2 of 2" in a 160px cell as three lines.
    const tops = new Set([...range.getClientRects()].map((x) => Math.round(x.top)));
    const lines = tops.size;
    if (lines >= 3) r.crushedCells.push({ text: text.slice(0, 24), lines });
  }

  // --- content painted outside the table it belongs to ---
  //
  // The fault this check exists for: an action column carrying prose as well as
  // buttons had `overflow: visible`, so "Nobody home, gate locked" ran past the
  // table's white background and onto the page. Nothing else here caught it —
  // the text was not clipped, not wrapped and not off-screen, it was simply
  // somewhere it had no business being.
  for (const table of document.querySelectorAll("main table")) {
    const t = table.getBoundingClientRect();
    for (const cell of table.querySelectorAll("td, th")) {
      const c = cell.getBoundingClientRect();
      const past = Math.round(Math.max(0, c.right - t.right - 1) + Math.max(0, t.left - c.left - 1));
      if (past > 0) {
        r.spillsOutsideTable.push({ text: (cell.textContent || "").trim().slice(0, 26), past });
        continue;
      }
      // A child only spills if its cell lets it. Inside a cell that clips, a
      // wide child is painted clipped however wide its box measures — reporting
      // it as a spill is measuring the box instead of the pixels, again.
      const cellClips = ["hidden", "clip", "auto", "scroll"].includes(getComputedStyle(cell).overflowX);
      if (cellClips) continue;
      for (const kid of cell.children) {
        const k = kid.getBoundingClientRect();
        if (!k.width) continue;
        const out = Math.round(Math.max(0, k.right - t.right - 1));
        if (out > 0) r.spillsOutsideTable.push({ text: (kid.textContent || "").trim().slice(0, 26), past: out });
      }
    }
  }

  // --- a column of buttons narrower than its buttons ---
  //
  // This rendered as three dots at the end of the row: a CSS ellipsis, which
  // reads as a "more actions" menu and cannot be clicked, because it is not an
  // element. The fix is always to widen the column, never to hide the marker.
  for (const td of document.querySelectorAll("main td.actions, main td.lb-actions")) {
    if (!td.querySelector("button, a.btn")) continue;
    if (td.scrollWidth > td.clientWidth + 1) {
      r.clippedActionCells.push({
        needs: td.scrollWidth, has: Math.round(td.clientWidth),
        buttons: [...td.querySelectorAll("button")].map((b) => (b.textContent || "").replace(/\s+/g, " ").trim()).slice(0, 3),
      });
    }
  }

  // --- a list with no way to page it ---
  for (const t of document.querySelectorAll("table")) {
    const rows = t.querySelectorAll("tbody tr").length;
    if (rows <= 60) continue;
    const scope = t.closest("section, .card, main") || document;
    if (!scope.querySelector(".pager, .dt-pager, .pagination")) r.unpagedTables.push(rows);
  }

  // --- contrast, with translucent layers composited ---
  const parse = (c) => { const m = (c || "").match(/[\d.]+/g) || []; return { r: +m[0] || 0, g: +m[1] || 0, b: +m[2] || 0, a: m[3] === undefined ? 1 : +m[3] }; };
  const over = (f, b) => ({ r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1 });
  const lum = (c) => { const t = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return .2126 * t(c.r) + .7152 * t(c.g) + .0722 * t(c.b); };
  // A gradient is a background too. Reading only `background-color` saw
  // `rgba(0,0,0,0)` on a gradient-filled avatar, fell through to the white card
  // behind it and reported white-on-white — a ratio of 1.0 for text that was
  // genuinely poor but not invisible. The lightest stop is the worst case for
  // light text, so that is what gets measured.
  const lightestStop = (image) => {
    const stops = (image || "").match(/rgba?\([^)]*\)/g);
    if (!stops || !stops.length) return null;
    return stops.map(parse).reduce((a, b) => (lum(a) >= lum(b) ? a : b));
  };
  // An ancestor only counts as background if it is actually behind the element.
  // A label positioned outside its parent's box — `top: -20px` on a chart bar,
  // say — is painted on whatever is behind the PARENT, not on the parent. Taking
  // the DOM ancestry literally measured white axis labels against the dark bar
  // they sit above and called a legible 6.5:1 label a 2.34 failure.
  const behind = (ancestor, box) => {
    const a = ancestor.getBoundingClientRect();
    const cx = box.left + box.width / 2, cy = box.top + box.height / 2;
    return cx >= a.left - 0.5 && cx <= a.right + 0.5 && cy >= a.top - 0.5 && cy <= a.bottom + 0.5;
  };
  /* html, then body, then white as the last resort — the same order the browser
     resolves the canvas background in. */
  const pageGround = () => {
    for (const el of [de, document.body]) {
      if (!el) continue;
      const b = parse(getComputedStyle(el).backgroundColor);
      if (b.a > 0) return over(b, { r: 255, g: 255, b: 255, a: 1 });
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const bgOf = (el) => {
    const box = el.getBoundingClientRect();
    const stack = []; let e = el;
    while (e && e !== de) {
      if (e !== el && !behind(e, box)) { e = e.parentElement; continue; }
      const cs = getComputedStyle(e);
      const grad = lightestStop(cs.backgroundImage);
      if (grad) stack.push(grad);
      const b = parse(cs.backgroundColor);
      if (b.a > 0) stack.push(b);
      e = e.parentElement;
    }
    /* The ground under everything is the page's own background, read rather
       than assumed.

       This used to start at opaque white. In dark mode that composited light
       text against a white ground it is never painted on, and reported #f3f3f6
       body copy, which measures 15.8:1 where it actually sits — as a 1.11
       failure. Twelve of them, all fictional. A measurement with a constant
       baked into it is a claim about the theme it was written in. */
    let base = pageGround();
    for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base);
    return base;
  };
  for (const e of [...document.querySelectorAll("main *")].slice(0, 500)) {
    if (e.children.length || !(e.textContent || "").trim()) continue;
    const cs = getComputedStyle(e);
    if (cs.visibility === "hidden" || cs.opacity === "0" || !e.getBoundingClientRect().width) continue;
    const bg = bgOf(e), fg = over(parse(cs.color), bg);
    const ratio = (Math.max(lum(fg), lum(bg)) + .05) / (Math.min(lum(fg), lum(bg)) + .05);
    const size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    if (ratio < need) r.lowContrast.push({ text: (e.textContent || "").trim().slice(0, 24), ratio: +ratio.toFixed(2), need });
  }
  return r;
};

function recordFaults(faults, key, route, a, headings) {
  const f = {};
  if (route !== "/" && a.heading === headings["/"]) f.fellThroughToDashboard = a.heading;
  if (a.pageScrollsSideways) f.pageScrollsSideways = a.pageScrollsSideways;
  if (a.slicedControls.length) f.slicedControls = a.slicedControls.slice(0, 3);
  if (a.crushedCells.length) f.crushedCells = { count: a.crushedCells.length, worst: Math.max(...a.crushedCells.map((c) => c.lines)) };
  if (a.unpagedTables.length) f.unpagedTables = a.unpagedTables;
  if (a.clippedActionCells.length) f.clippedActionCells = { count: a.clippedActionCells.length, worst: a.clippedActionCells[0] };
  if (a.spillsOutsideTable.length) f.spillsOutsideTable = { count: a.spillsOutsideTable.length, worst: a.spillsOutsideTable.slice(0, 3) };
  if (a.lowContrast.length) f.lowContrast = a.lowContrast.slice(0, 3);
  if (Object.keys(f).length) faults[key] = f;
}

export default async function run(page) {
  /* Dark mode is audited, not assumed.
     `AUDIT_THEME=dark` sets the same key the application writes, before the first
     navigation, so the inline script in index.html paints dark on the very first
     frame. The contrast check is alpha- and gradient-composited, so it measures
     what is actually on screen rather than what the token says, which is the
     only way to catch a chip that inverted and a label that did not. */
  const theme = process.env.AUDIT_THEME;
  if (theme === "dark" || theme === "light") {
    await page.addInitScript((t) => {
      try { localStorage.setItem("rx5000_theme", t); } catch { /* ignore */ }
    }, theme);
  }
  await page.goto("http://localhost:5180/login");
  await page.waitForTimeout(900);
  const inputs = await page.locator("input").all();
  await inputs[0].fill("admin"); await inputs[1].fill("admin123");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(2800);

  const faults = {};
  const headings = {};
  let checks = 0;

  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w, height: 1000 });
    for (const route of ROUTES) {
      await page.goto("http://localhost:5180" + route, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1500);

      // Every tab, not just the one that happens to open first.
      //
      // A delivery failure reason painted straight off the edge of its table and
      // onto the page background for as long as this file has existed, because
      // it only appears on the "Failed" tab and nothing ever clicked it. The
      // default tab of a tabbed page is a sample of one, and the emptiest one at
      // that — "To go out" held zero rows while "Failed" held fourteen.
      const tabs = await page.evaluate(() =>
        [...document.querySelectorAll(".pill-tabs button, [role=tab]")].map((b, i) => i));
      const panels = tabs.length ? tabs : [null];

      for (const tabIndex of panels) {
        if (tabIndex !== null && tabIndex > 0) {
          await page.evaluate((i) => {
            const b = [...document.querySelectorAll(".pill-tabs button, [role=tab]")][i];
            if (b) b.click();
          }, tabIndex);
          await page.waitForTimeout(1200);
        }
        const a = await page.evaluate(AUDIT);
        checks++;
        if (tabIndex === null || tabIndex === 0) headings[route] = a.heading;
        const label = tabIndex === null || tabIndex === 0 ? route : `${route}#tab${tabIndex}`;
        recordFaults(faults, `${w}px ${label}`, route, a, headings);
      }
    }
  }
  return { checksRun: checks, combinationsWithFaults: Object.keys(faults).length, faults };
}
