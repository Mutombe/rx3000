/** Documents that leave this pharmacy carrying its name.
 *
 *  A statement that goes to a wholesaler, a claim schedule that goes to a
 *  funder, a tax invoice that may be read by a revenue officer: these are not
 *  screens with the navigation hidden. They are correspondence, and a
 *  screenshot of a table with a browser header at the top is what a pharmacy
 *  hands over when its software has no opinion about printing.
 *
 *  The shape here is taken from a real supplier statement: a letterhead block
 *  and an addressed-to block side by side, a strip of labelled meta fields
 *  (date, account, amount due), the ledger itself, and an ageing strip at the
 *  foot.
 *
 *  SET LIKE EVERY OTHER PIECE OF RX5000 PAPER.
 *
 *  The schedules sheet, the shorthand sheet and the claim copy are built by
 *  reportlab through backend/app/services/brand.py; these are built by a
 *  browser. Two engines, and until now two different-looking companies: those
 *  in Manrope on navy, these in Helvetica on near-black. The palette, the type,
 *  the band across the top and the way the table is ruled are the same on both
 *  now, and the values below are the same hexes brand.py states.
 *
 *  The wordmark on this one is the PHARMACY'S, not ours. A statement to a
 *  wholesaler is the pharmacy's correspondence and carries the pharmacy's
 *  identity; what RX5000 supplies is the setting. Our own mark belongs on our
 *  own reference sheets, which is where brand.py puts it.
 *
 *  Everything is inlined, the logo as a data URI and the type as a subset woff2,
 *  so the document is one file that prints identically from a browser, a saved
 *  copy, or an attachment, with or without a line to the internet.
 */
import { claimPrintView } from "./printView";

export interface Letterhead {
  display_name?: string;
  legal_name?: string;
  registration_no?: string;
  vat_no?: string;
  tax_no?: string;
  phone?: string;
  email?: string;
  address?: string[];
  bank_name?: string;
  bank_account?: string;
  bank_branch?: string;
  document_footer?: string;
  terms?: string;
  logo?: string;
}

export interface DocColumn {
  key: string;
  label: string;
  /** Right-aligned and tabular, for money and counts. */
  numeric?: boolean;
  /** A fixed width, where the content would otherwise dictate a silly one. */
  width?: string;
}

export interface DocOptions {
  /** "Statement", "Tax invoice", "Remittance advice". */
  kind: string;
  /** Who it is addressed to: name first, then address lines. */
  to?: string[];
  /** The labelled strip under the addresses: date, account, amount due. */
  meta?: { label: string; value: string; strong?: boolean }[];
  columns: DocColumn[];
  rows: Record<string, unknown>[];
  /** A row printed above the body: "Balance brought forward". */
  opening?: Record<string, unknown>;
  /** Totals printed under the body. */
  totals?: Record<string, unknown>;
  /** The ageing strip: label and amount, oldest first. */
  ageing?: { label: string; value: string; strong?: boolean }[];
  /** A sentence under the table: terms, a note, what to do next. */
  note?: string;
}

const esc = (v: unknown) =>
  String(v ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));

/** The stylesheet. Written for paper first: millimetres, and a table that
 *  repeats its header across a page break, which `thead` does natively and
 *  almost nothing else does.
 *
 *  THE BAND AND THE FOOT REPEAT, AND THERE IS ONLY ONE WAY TO MAKE THEM.
 *
 *  A statement runs to three pages more often than it runs to one, and page
 *  three with no letterhead on it is the page that gets separated and lost. The
 *  obvious way to repeat it, a `position: fixed` band sitting in the page
 *  margin, does not work: a printing browser lays fixed elements out once, and
 *  what it actually produced was the letterhead at the FOOT of page one,
 *  printed over the closing balance. It looked right in the window, because a
 *  window has no page two.
 *
 *  `display: table-header-group` is the one mechanism that genuinely repeats,
 *  so the whole document is one table: the band is its `thead`, the foot is its
 *  `tfoot`, and everything else is the single cell in between. The ledger is a
 *  table nested in that cell and repeats its own column headings the same way.
 *  Verified on paper rather than on screen by qa/document-look.mjs, which
 *  prints it through chromium and writes a PNG of every page. */
const CSS = `
  @page { size: A4; margin: 12mm 12mm 11mm; }
  * { box-sizing: border-box; }
  :root {
    /* brand.py states these same values for the sheets reportlab builds. */
    --ink: #032153;      /* the wordmark's navy: the name, and the rule under
                            a table header */
    --navy: #12306b;     /* the lighter navy beside it: what the document is */
    --body: #16161d;     /* near-black, because this is worked from, not read */
    --soft: #4a4956;
    --faint: #8a8a99;
    --rule: #d5dae6;     /* hairlines, tinted toward the navy */
    --tint: #f2f4f9;     /* the alternate row */
  }
  body {
    margin: 0; color: var(--body);
    font: 400 10.5px/1.5 "Manrope", "Segoe UI", system-ui, Arial, sans-serif;
    font-feature-settings: "kern" 1, "liga" 1;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }

  /* ---- the sheet, whose header and footer repeat ------------------------- */
  .sheet { width: 100%; border-collapse: collapse; }
  .sheet > thead { display: table-header-group; }
  .sheet > tfoot { display: table-footer-group; }
  .sheet > thead > tr > td,
  .sheet > tfoot > tr > td,
  .sheet > tbody > tr > td { padding: 0; background: none; border: none; }

  /* ---- the band, on every page ------------------------------------------ */
  .band {
    display: flex; align-items: flex-end; justify-content: space-between;
    gap: 10mm; padding-bottom: 2.6mm; margin-bottom: 6mm;
    border-bottom: 0.8pt solid var(--rule);
  }
  .band-mark { display: flex; align-items: flex-end; gap: 3.5mm; min-width: 0; }
  .band-mark img { max-height: 11mm; max-width: 52mm; object-fit: contain; }
  /* A running head, not a second wordmark. The name is set large once, in the
     letterhead below; up here it is doing the job a running head does in a
     book, which is to say whose page this is on page three. Set like the
     other labels on the sheet so it reads as furniture rather than as the
     same name printed twice at two sizes. */
  .band-name {
    font-weight: 600; font-size: 8px; letter-spacing: .1em;
    text-transform: uppercase; color: var(--soft); white-space: nowrap;
    padding-bottom: 0.4mm;
  }
  .band-of { text-align: right; white-space: nowrap; }
  .band-kind {
    font-weight: 700; font-size: 10px; letter-spacing: .07em;
    text-transform: uppercase; color: var(--navy);
  }
  .band-stamp { font-size: 8px; color: var(--faint); margin-top: 0.8mm; }

  /* ---- who it is from, and who it is to --------------------------------- */
  .hd {
    display: flex; justify-content: space-between; gap: 12mm;
    align-items: flex-start; padding-top: 1mm;
  }
  .hd-name {
    font-weight: 800; font-size: 19px; line-height: 1.15;
    letter-spacing: -0.025em; color: var(--ink);
  }
  .hd-sub { color: var(--soft); font-size: 9px; line-height: 1.55; margin-top: 1mm; }
  .to { text-align: right; min-width: 52mm; }
  .to-label {
    font-weight: 600; font-size: 7.6px; letter-spacing: .1em;
    text-transform: uppercase; color: var(--faint); margin-bottom: 1.2mm;
  }
  .to-name { font-weight: 700; font-size: 11.5px; color: var(--body); }
  .to-lines { color: var(--soft); font-size: 9px; line-height: 1.55; }

  /* ---- the labelled strip ----------------------------------------------- */
  /* Bordered top and bottom rather than boxed: it is a band of facts, not a
     table. The navy hairline over it ties it to the rule under the band. */
  .meta {
    display: flex; flex-wrap: wrap; gap: 5mm 11mm;
    padding: 2.8mm 0; margin: 6mm 0 5mm;
    border-top: 0.8pt solid var(--ink); border-bottom: 0.5pt solid var(--rule);
  }
  .meta div { display: flex; flex-direction: column; gap: 0.6mm; }
  .meta dt {
    font-weight: 600; font-size: 7.6px; letter-spacing: .09em;
    text-transform: uppercase; color: var(--faint);
  }
  .meta dd { margin: 0; font-size: 11px; font-variant-numeric: tabular-nums; }
  .meta .strong dd { font-weight: 700; font-size: 14px; color: var(--ink); }

  /* ---- the ledger -------------------------------------------------------- */
  /* Scoped to the ledger, so the sheet's own furniture rows above are not
     given a header rule and a row tint as well. */
  /* A tint on alternate rows rather than a rule under each one, which is what
     brand.table_style does on the sheets reportlab builds: thirty ruled rows
     is a timetable, and a tint still lets the eye carry one row across the
     page. */
  .ledger { width: 100%; border-collapse: collapse; }
  .ledger thead { display: table-header-group; }
  .ledger th {
    text-align: left; font-weight: 600; font-size: 7.6px; letter-spacing: .08em;
    text-transform: uppercase; color: var(--faint);
    padding: 2mm 2mm 1.6mm; border-bottom: 0.9pt solid var(--ink);
    white-space: nowrap;
  }
  .ledger td { padding: 1.9mm 2mm; vertical-align: top; }
  .ledger tbody tr:nth-child(even) td { background: var(--tint); }
  .ledger tbody tr.totals td { background: none; }
  .ledger tr { page-break-inside: avoid; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  /* The brought-forward is one line or it is not a brought-forward: wrapped
     across two rows it reads as a transaction with a missing date. */
  .ledger .opening td {
    font-weight: 600; white-space: nowrap; color: var(--navy);
    background: none; border-bottom: 0.5pt solid var(--rule);
  }
  /* The totals are the last row of the body, not a table-footer-group.
     A footer group is repeated at the bottom of every page by the same rule
     that usefully repeats the column headings at the top of every page, which
     on a statement means "Closing balance 30,925.55" printed at the foot of
     page one, where it is not the closing balance and is not 30,925.55 yet. */
  .ledger tr.totals td {
    border-top: 0.9pt solid var(--ink); background: none;
    font-weight: 700; font-size: 11.5px; color: var(--ink); padding-top: 2.4mm;
  }

  /* ---- the ageing strip -------------------------------------------------- */
  /* The whole point of a statement: not what is owed, but how long it has been
     owed for. Given the tint as a block, so it reads as one figure in parts. */
  .age {
    margin-top: 7mm; padding: 3mm 3mm 2.6mm; background: var(--tint);
    border-left: 2.4pt solid var(--ink);
  }
  .age-label {
    font-weight: 600; font-size: 7.6px; letter-spacing: .09em;
    text-transform: uppercase; color: var(--faint); margin-bottom: 1.6mm;
  }
  .age table { table-layout: fixed; width: 100%; border-collapse: collapse; }
  .age th {
    border-bottom: none; padding: 0 2mm 0.8mm; text-align: right;
    font-weight: 600; font-size: 7.6px; letter-spacing: .08em;
    text-transform: uppercase; color: var(--soft);
  }
  .age td {
    background: none; text-align: right; padding: 0 2mm;
    font-size: 11px; font-variant-numeric: tabular-nums;
  }
  .age .strong { font-weight: 700; color: var(--ink); font-size: 12.5px; }

  .note {
    margin-top: 6mm; font-size: 9.5px; line-height: 1.6; color: var(--soft);
    max-width: 128mm;
  }

  /* ---- the foot, on every page ------------------------------------------ */
  .foot {
    display: flex; justify-content: space-between; gap: 6mm;
    margin-top: 8mm; padding-top: 2mm; border-top: 0.5pt solid var(--rule);
    font-size: 8px; color: var(--faint);
  }

  /* On screen it is a sheet of paper on a desk, because most of these are read
     in the window before anybody decides whether to print them at all. */
  @media screen {
    body { background: #e9eaee; padding: 10mm; }
    .doc {
      background: #fff; max-width: 210mm; margin: 0 auto;
      padding: 12mm 12mm 11mm; box-shadow: 0 2px 20px rgba(3, 33, 83, .16);
    }
  }
`;

/** The band across the top, repeated on every page.
 *
 *  It carries the pharmacy's mark and what the document is, because those are
 *  the two things somebody holding page three needs and neither of them is on
 *  page three otherwise.
 */
function band(head: Letterhead, o: DocOptions): string {
  // The stamp is the one fact that identifies this document among others of
  // its kind: the account it is for, or failing that the date on it.
  const stamp = o.meta?.find((m) => !m.strong)?.value ?? "";
  return `<div class="band">
    <div class="band-mark">
      ${head.logo ? `<img src="${esc(head.logo)}" alt="">` : ""}
      <div class="band-name">${esc(head.display_name || "")}</div>
    </div>
    <div class="band-of">
      <div class="band-kind">${esc(o.kind)}</div>
      ${stamp ? `<div class="band-stamp">${esc(stamp)}</div>` : ""}
    </div>
  </div>`;
}

/** The foot, or a rule and nothing.
 *
 *  An empty bordered strip at the foot of a page is not a neutral absence: it
 *  reads as a field somebody forgot to fill in, on a document going to a
 *  supplier. A pharmacy that has not entered its bank details gets the name it
 *  does have, which is what the foot is for.
 */
function foot(head: Letterhead): string {
  const bank = head.bank_name
    ? `${head.bank_name} · ${head.bank_account ?? ""} ${head.bank_branch ?? ""}`.trim()
    : "";
  const left = head.document_footer || head.legal_name || head.display_name || "";
  if (!left && !bank) return "";
  return `<div class="foot">
    <span>${esc(left)}</span>
    <span>${esc(bank)}</span>
  </div>`;
}

/** Everything about the pharmacy that is not its name. */
function fromLines(head: Letterhead): string[] {
  return [
    head.legal_name && head.legal_name !== head.display_name ? head.legal_name : "",
    ...(head.address ?? []),
    head.phone ? `Tel ${head.phone}` : "",
    head.email ?? "",
    head.registration_no ? `Reg ${head.registration_no}` : "",
    head.vat_no ? `VAT ${head.vat_no}` : "",
  ].filter(Boolean) as string[];
}

/** The whole document, as one self-contained HTML file.
 *
 *  `fontCss` is the embedded face. It is passed in rather than imported so a
 *  session that never prints never loads 57kB of woff2, and so a document
 *  still renders, in whatever the machine has, if that load fails.
 */
export function renderDocument(head: Letterhead, o: DocOptions,
                               fontCss = ""): string {
  const cell = (row: Record<string, unknown>, c: DocColumn) =>
    `<td class="${c.numeric ? "num" : ""}">${esc(row[c.key])}</td>`;

  const body = o.rows.map(
    (r) => `<tr>${o.columns.map((c) => cell(r, c)).join("")}</tr>`).join("");

  const ageing = o.ageing?.length
    ? `<div class="age">
         <div class="age-label">Ageing</div>
         <table>
           <tr>${o.ageing.map((a) => `<th>${esc(a.label)}</th>`).join("")}</tr>
           <tr>${o.ageing.map((a) =>
               `<td class="${a.strong ? "strong" : ""}">${esc(a.value)}</td>`).join("")}</tr>
         </table>
       </div>`
    : "";

  // One table for the whole sheet, because its thead is the only thing a
  // printing browser repeats on page two. See the note above the stylesheet.
  return `<!doctype html><html><head><meta charset="utf-8">
<title>${esc(o.kind)}${o.to?.[0] ? `: ${esc(o.to[0])}` : ""}</title>
<style>${fontCss}${CSS}</style></head><body><div class="doc">
<table class="sheet">
<thead><tr><td>${band(head, o)}</td></tr></thead>
<tfoot><tr><td>${foot(head)}</td></tr></tfoot>
<tbody><tr><td>

  <div class="hd">
    <div>
      <div class="hd-name">${esc(head.display_name || "")}</div>
      <div class="hd-sub">${fromLines(head).map(esc).join("<br>")}</div>
    </div>
    ${o.to?.length ? `<div class="to">
      <div class="to-label">To</div>
      <div class="to-name">${esc(o.to[0])}</div>
      <div class="to-lines">${o.to.slice(1).map(esc).join("<br>")}</div>
    </div>` : ""}
  </div>

  ${o.meta?.length ? `<div class="meta">${o.meta.map((m) => `
    <div class="${m.strong ? "strong" : ""}">
      <dt>${esc(m.label)}</dt><dd>${esc(m.value)}</dd>
    </div>`).join("")}</div>` : `<div style="height:6mm"></div>`}

  <table class="ledger">
    <thead><tr>${o.columns.map((c) =>
      `<th class="${c.numeric ? "num" : ""}"${c.width ? ` style="width:${c.width}"` : ""}>${esc(c.label)}</th>`
    ).join("")}</tr></thead>
    <tbody>
      ${o.opening ? `<tr class="opening">${o.columns.map((c) => cell(o.opening!, c)).join("")}</tr>` : ""}
      ${body}
      ${o.totals ? `<tr class="totals">${o.columns.map((c) => cell(o.totals!, c)).join("")}</tr>` : ""}
    </tbody>
  </table>

  ${ageing}
  ${o.note ? `<p class="note">${esc(o.note)}</p>` : ""}

</td></tr></tbody>
</table>
</div></body></html>`;
}

/** The embedded type, fetched once per session and only if something prints. */
let fontOnce: Promise<string> | null = null;
function docFont(): Promise<string> {
  if (!fontOnce) {
    fontOnce = import("./docFont")
      .then((m) => m.DOC_FONT)
      // A document set in the machine's own sans is worse than one set in
      // Manrope, and far better than a print button that does nothing.
      .catch(() => "");
  }
  return fontOnce;
}

/** Open it in a window and offer the print dialog.
 *
 *  A window rather than an iframe: the reader can read it, scroll it, decide
 *  not to print it, and save it as a PDF from the same dialog, which is what
 *  most of these are actually for.
 */
export function printDocument(head: Letterhead, o: DocOptions) {
  // Claimed synchronously, inside the click that asked for it. A window opened
  // after an await has lost the gesture and is a pop-up as far as the browser
  // is concerned, which is a print button that silently does nothing. The font
  // is a promise, so the place to print is taken first and written into after.
  //
  // `reader: true` because these are read before they are printed. Where a
  // window is refused, which is every till running the desktop shell, this now
  // falls back to a frame instead of returning silently as it used to.
  const view = claimPrintView({ reader: true });
  if (!view) return;
  // Waits for the logo and the embedded face, which are both data URIs and
  // therefore usually already decoded, but "usually" prints a blank letterhead
  // often enough to matter.
  docFont().then(
    (fontCss) => view.write(renderDocument(head, o, fontCss)),
    () => view.cancel(),
  );
}
