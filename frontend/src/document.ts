/** Documents that leave this pharmacy carrying its name.
 *
 *  A statement that goes to a wholesaler, a claim schedule that goes to a
 *  funder, a tax invoice that may be read by a revenue officer — these are not
 *  screens with the navigation hidden. They are correspondence, and a
 *  screenshot of a table with a browser header at the top is what a pharmacy
 *  hands over when its software has no opinion about printing.
 *
 *  The shape here is taken from a real supplier statement: a letterhead block
 *  and an addressed-to block side by side, a strip of labelled meta fields
 *  (date, account, amount due), the ledger itself, and an ageing strip at the
 *  foot. It repeats the header on every page, because the second page of a
 *  statement with no letterhead on it is a page that gets separated and lost.
 *
 *  Everything is inlined — the logo as a data URI, the CSS in a <style> — so
 *  the document is one file that prints identically from a browser, a saved
 *  copy, or an attachment.
 */

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
  /** The labelled strip under the addresses — date, account, amount due. */
  meta?: { label: string; value: string; strong?: boolean }[];
  columns: DocColumn[];
  rows: Record<string, unknown>[];
  /** A row printed above the body — "Balance brought forward". */
  opening?: Record<string, unknown>;
  /** Totals printed under the body. */
  totals?: Record<string, unknown>;
  /** The ageing strip: label and amount, oldest first. */
  ageing?: { label: string; value: string; strong?: boolean }[];
  /** A sentence under the table — terms, a note, what to do next. */
  note?: string;
}

const esc = (v: unknown) =>
  String(v ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));

/** The stylesheet. Written for paper first: millimetres, no colour that costs
 *  ink to no purpose, and a table that repeats its header across a page break —
 *  which `thead` does natively and almost nothing else does. */
const CSS = `
  @page { size: A4; margin: 14mm 12mm 16mm; }
  * { box-sizing: border-box; }
  body {
    margin: 0; font: 10.5px/1.45 "Helvetica Neue", Arial, sans-serif;
    color: #14141a; -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
  .doc { max-width: 186mm; margin: 0 auto; }

  /* The letterhead and the address it is going to, side by side — the shape
     of every statement anybody in this trade has ever been sent. */
  .hd { display: flex; justify-content: space-between; gap: 12mm; align-items: flex-start; }
  .hd-mark { display: flex; gap: 4mm; align-items: flex-start; }
  .hd-mark img { max-height: 18mm; max-width: 46mm; object-fit: contain; }
  .hd-name { font-size: 13px; font-weight: 700; letter-spacing: -0.01em; }
  .hd-sub, .to-lines { color: #4a4a55; }
  .hd-block { font-size: 9.5px; line-height: 1.5; }
  .to { text-align: right; min-width: 55mm; }
  .to-label {
    font-size: 8px; letter-spacing: .09em; text-transform: uppercase;
    color: #77778a; margin-bottom: 1mm;
  }
  .to-name { font-weight: 700; }

  .kind {
    margin: 7mm 0 3mm; font-size: 17px; font-weight: 700; letter-spacing: -0.02em;
  }

  /* The labelled strip. Bordered top and bottom rather than boxed: it is a
     band of facts, not a table. */
  .meta {
    display: flex; flex-wrap: wrap; gap: 6mm 10mm;
    padding: 2.5mm 0; margin-bottom: 4mm;
    border-top: 0.5pt solid #14141a; border-bottom: 0.5pt solid #d8d8e0;
  }
  .meta div { display: flex; flex-direction: column; }
  .meta dt {
    font-size: 8px; letter-spacing: .08em; text-transform: uppercase; color: #77778a;
  }
  .meta dd { margin: 0; font-size: 11px; }
  .meta .strong dd { font-weight: 700; font-size: 13px; }

  table { width: 100%; border-collapse: collapse; }
  thead { display: table-header-group; }
  tfoot { display: table-footer-group; }
  th {
    text-align: left; font-size: 8px; letter-spacing: .07em; text-transform: uppercase;
    color: #4a4a55; padding: 2mm 2mm 1.5mm; border-bottom: 0.75pt solid #14141a;
    white-space: nowrap;
  }
  td { padding: 1.6mm 2mm; border-bottom: 0.25pt solid #e6e6ec; vertical-align: top; }
  tr { page-break-inside: avoid; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  /* The brought-forward is one line or it is not a brought-forward: wrapped
     across two rows it reads as a transaction with a missing date. */
  .opening td { font-weight: 600; background: #f6f6f9; white-space: nowrap; }
  tfoot td { border-top: 0.75pt solid #14141a; border-bottom: none; font-weight: 700; padding-top: 2mm; }

  /* The ageing strip. The whole point of a statement: not what is owed, but
     how long it has been owed for. */
  .age { margin-top: 6mm; border-top: 0.5pt solid #14141a; }
  .age table { table-layout: fixed; }
  .age th { border-bottom: none; padding-bottom: 0.5mm; text-align: right; }
  .age td { border-bottom: none; text-align: right; font-variant-numeric: tabular-nums; }
  .age .strong { font-weight: 700; }

  .note { margin-top: 5mm; font-size: 9.5px; color: #4a4a55; max-width: 130mm; }
  .foot {
    margin-top: 7mm; padding-top: 2mm; border-top: 0.25pt solid #d8d8e0;
    font-size: 8.5px; color: #77778a; display: flex; justify-content: space-between; gap: 6mm;
  }
  @media screen {
    body { background: #ececed; padding: 8mm; }
    .doc { background: #fff; padding: 14mm 12mm; box-shadow: 0 2px 18px rgba(0,0,0,.14); }
  }
`;

/** The footer, or nothing at all.
 *
 *  An empty bordered strip at the foot of a page is not a neutral absence — it
 *  reads as a field somebody forgot to fill in, on a document going to a
 *  supplier. A pharmacy that has not entered its bank details should get a page
 *  that simply ends.
 */
function foot(head: Letterhead): string {
  const bank = head.bank_name
    ? `${head.bank_name} · ${head.bank_account ?? ""} ${head.bank_branch ?? ""}`.trim()
    : "";
  if (!bank && !head.document_footer) return "";
  return `<div class="foot">
    <span>${esc(head.document_footer || "")}</span>
    <span>${esc(bank)}</span>
  </div>`;
}

function headBlock(head: Letterhead): string {
  const lines = [
    head.legal_name && head.legal_name !== head.display_name ? head.legal_name : "",
    ...(head.address ?? []),
    head.phone ? `Tel ${head.phone}` : "",
    head.email ?? "",
    head.registration_no ? `Reg ${head.registration_no}` : "",
    head.vat_no ? `VAT ${head.vat_no}` : "",
  ].filter(Boolean);
  return `
    <div class="hd-mark">
      ${head.logo ? `<img src="${esc(head.logo)}" alt="">` : ""}
      <div class="hd-block">
        <div class="hd-name">${esc(head.display_name || "")}</div>
        <div class="hd-sub">${lines.map(esc).join("<br>")}</div>
      </div>
    </div>`;
}

/** The whole document, as one self-contained HTML file. */
export function renderDocument(head: Letterhead, o: DocOptions): string {
  const cell = (row: Record<string, unknown>, c: DocColumn) =>
    `<td class="${c.numeric ? "num" : ""}">${esc(row[c.key])}</td>`;

  const body = o.rows.map(
    (r) => `<tr>${o.columns.map((c) => cell(r, c)).join("")}</tr>`).join("");

  const ageing = o.ageing?.length
    ? `<div class="age"><table>
         <tr>${o.ageing.map((a) => `<th>${esc(a.label)}</th>`).join("")}</tr>
         <tr>${o.ageing.map((a) =>
             `<td class="${a.strong ? "strong" : ""}">${esc(a.value)}</td>`).join("")}</tr>
       </table></div>`
    : "";

  return `<!doctype html><html><head><meta charset="utf-8">
<title>${esc(o.kind)}${o.to?.[0] ? ` — ${esc(o.to[0])}` : ""}</title>
<style>${CSS}</style></head><body><div class="doc">
  <div class="hd">
    ${headBlock(head)}
    ${o.to?.length ? `<div class="to">
      <div class="to-label">To</div>
      <div class="to-name">${esc(o.to[0])}</div>
      <div class="to-lines hd-block">${o.to.slice(1).map(esc).join("<br>")}</div>
    </div>` : ""}
  </div>

  <div class="kind">${esc(o.kind)}</div>

  ${o.meta?.length ? `<div class="meta">${o.meta.map((m) => `
    <div class="${m.strong ? "strong" : ""}">
      <dt>${esc(m.label)}</dt><dd>${esc(m.value)}</dd>
    </div>`).join("")}</div>` : ""}

  <table>
    <thead><tr>${o.columns.map((c) =>
      `<th class="${c.numeric ? "num" : ""}"${c.width ? ` style="width:${c.width}"` : ""}>${esc(c.label)}</th>`
    ).join("")}</tr></thead>
    <tbody>
      ${o.opening ? `<tr class="opening">${o.columns.map((c) => cell(o.opening!, c)).join("")}</tr>` : ""}
      ${body}
    </tbody>
    ${o.totals ? `<tfoot><tr>${o.columns.map((c) => cell(o.totals!, c)).join("")}</tr></tfoot>` : ""}
  </table>

  ${ageing}
  ${o.note ? `<p class="note">${esc(o.note)}</p>` : ""}

  ${foot(head)}
</div></body></html>`;
}

/** Open it in a window and offer the print dialog.
 *
 *  A window rather than an iframe: the reader can read it, scroll it, decide
 *  not to print it, and save it as a PDF from the same dialog — which is what
 *  most of these are actually for.
 */
export function printDocument(head: Letterhead, o: DocOptions) {
  const w = window.open("", "_blank", "width=900,height=1000");
  if (!w) return;
  w.document.write(renderDocument(head, o));
  w.document.close();
  // Waits for the logo, which is a data URI and therefore usually already
  // decoded — but "usually" prints a blank letterhead often enough to matter.
  w.onload = () => setTimeout(() => w.print(), 120);
}
