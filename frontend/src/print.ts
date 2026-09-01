import { Label, Sale } from "./types";
import { money } from "./api";
import { toast } from "./components/Toast";

/** Open a print window with standalone HTML — keeps thermal/label output
 *  independent of the app's screen styling. */
function printHtml(title: string, css: string, body: string) {
  const win = window.open("", "_blank", "width=420,height=640");
  if (!win) {
    // A toast, not `alert`. This fires exactly when somebody is standing at a
    // counter waiting for a receipt, and a native box freezes the whole
    // application until it is dismissed, so the till stops responding at the
    // one moment it must not.
    toast.error("The print window was blocked. Allow pop-ups for this site "
                + "and print again.");
    return;
  }
  win.document.write(
    `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title>` +
      `<style>${css}</style></head><body>${body}</body></html>`,
  );
  win.document.close();
  win.focus();

  // Wait for any artwork to decode before printing, otherwise the logo can come
  // out blank. Falls back to a fixed delay if an image never resolves.
  const images = Array.from(win.document.images);
  const ready = Promise.all(
    images.map((img) =>
      img.complete
        ? Promise.resolve()
        : new Promise<void>((resolve) => {
            img.onload = () => resolve();
            img.onerror = () => resolve();
          }),
    ),
  );
  const timeout = new Promise<void>((resolve) => setTimeout(resolve, 1500));

  Promise.race([ready, timeout]).then(() => {
    setTimeout(() => {
      win.print();
      win.close();
    }, 150);
  });
}

const RECEIPT_CSS = `
  @page { size: 80mm auto; margin: 4mm; }
  body { font-family: "Courier New", monospace; font-size: 12px; width: 72mm; margin: 0; color: #000; }
  .c { text-align: center; }
  .r { text-align: right; }
  h1 { font-size: 15px; margin: 0 0 2px; }
  .sub { font-size: 10px; margin-bottom: 6px; }
  hr { border: none; border-top: 1px dashed #000; margin: 6px 0; }
  table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
  td { padding: 1px 0; vertical-align: top; }
  .tot { font-weight: bold; font-size: 13px; }
  .foot { font-size: 10px; margin-top: 8px; text-align: center; }
  .logo { width: 13mm; height: 13mm; object-fit: contain; margin-bottom: 1mm; }
`;

export function printReceipt(
  sale: Sale,
  // No default. This used to read "RX3000 Pharmacy", which printed the name of
  // the software on the receipt of every pharmacy that bought it.
  pharmacyName: string,
  regNo = "",
  branchName = "",
) {
  const when = new Date(sale.created_at).toLocaleString("en-ZA");
  const lines = sale.items
    .map(
      (i) =>
        `<tr><td>${i.quantity} x ${i.description}</td><td class="r">${money(i.line_total)}</td></tr>`,
    )
    .join("");

  const claim = sale.claim
    ? `<hr><table>
         <tr><td>Medical aid claim</td><td class="r">${sale.claim.claim_number}</td></tr>
         <tr><td>Status</td><td class="r">${sale.claim.status.toUpperCase()}</td></tr>
         <tr><td>Scheme paid</td><td class="r">${money(sale.claim.amount_approved)}</td></tr>
         <tr><td>Shortfall</td><td class="r">${money(sale.claim.patient_liable)}</td></tr>
       </table>`
    : "";

  const loyalty =
    sale.loyalty_points_earned || sale.loyalty_points_redeemed
      ? `<hr><table>
           ${sale.loyalty_points_redeemed ? `<tr><td>Points redeemed</td><td class="r">-${money(sale.loyalty_points_redeemed)}</td></tr>` : ""}
           ${sale.loyalty_points_earned ? `<tr><td>Points earned</td><td class="r">${sale.loyalty_points_earned} pts</td></tr>` : ""}
         </table>`
      : "";

  printHtml(
    `Receipt ${sale.sale_number}`,
    RECEIPT_CSS,
    `<div class="c"><img class="logo" src="${window.location.origin}/logo.png" alt="">
       <h1>${pharmacyName}</h1>
       <div class="sub">${branchName ? `${branchName}<br>` : ""}${regNo ? `Reg. ${regNo}<br>` : ""}Tax Invoice</div></div>
     <table>
       <tr><td>Invoice</td><td class="r">${sale.sale_number}</td></tr>
       <tr><td>Date</td><td class="r">${when}</td></tr>
       ${branchName ? `<tr><td>Branch</td><td class="r">${branchName}</td></tr>` : ""}
       ${sale.patient ? `<tr><td>Patient</td><td class="r">${sale.patient.first_name} ${sale.patient.last_name}</td></tr>` : ""}
     </table>
     <hr>
     <table>${lines}</table>
     <hr>
     <table>
       <tr><td>Subtotal (excl. VAT)</td><td class="r">${money(sale.subtotal)}</td></tr>
       <tr><td>VAT</td><td class="r">${money(sale.vat_amount)}</td></tr>
       <tr class="tot"><td>TOTAL</td><td class="r">${money(sale.total)}</td></tr>
       <tr><td>Paid by</td><td class="r">${sale.payment_method.replace("_", " ")}</td></tr>
       ${sale.payment_method === "cash" ? `<tr><td>Tendered</td><td class="r">${money(sale.amount_tendered)}</td></tr><tr><td>Change</td><td class="r">${money(sale.change_due)}</td></tr>` : ""}
     </table>
     ${loyalty}
     ${claim}
     <div class="foot">Thank you for your business.<br>Goods remain the property of ${pharmacyName}<br>until paid in full.</div>`,
  );
}

const LABEL_CSS = `
  /* The printed sticker, modelled on a real one.
     Kept in step with the preview in styles.css on purpose: a preview that does
     not match what the printer produces is worse than no preview, because
     somebody signs off on the screen and the roll disagrees.

     Millimetres throughout. A thermal label is a physical object and points
     drift between browsers; millimetres do not.

     ---

     **Everything now fits, and none of it is dropped.**

     An earlier version of this file cut batch, expiry, the prescriber and the
     price because forty-two real labels all overflowed — the worst needed 79mm
     of a 42mm sticker. That was the right call against that layout. It was the
     wrong conclusion about the label: a dispensed sticker from any Zimbabwean
     counter carries all of it, on the same size of paper.

     The room came from the layout, not from the paper:

       * the patient's name was a bold heading of its own, costing a full line
         at 8.4pt. On a real label the patient sits inside the audit block on
         the same line as the timestamp, which is also where a dispenser looks
         for it.
       * the directions were 9.6pt bold with 1.2mm padding and two rules. Real
         labels set them in condensed monospace, which fits about a third more
         characters per line and is what a patient reads at arm's length.
       * one rule instead of two, and the footer's rule removed.

     What it must carry, and why each is not optional:

       batch + expiry   a recall starts with a batch number, and the only copy
                        the patient has is this sticker
       who dispensed    the pharmacist is accountable for the hand-over
       when             to the second, because two dispensings of the same item
                        on one day are told apart by nothing else
       prescriber       who to telephone about the script
       Rx no + item     which item of how many, so four boxes can be checked
       branch           the shop that handed it over, with its address, its
                        telephone number and its code — on a chain this is not
                        head office, and it is the number the patient rings

     qa/label-fits.mjs measures the real markup at the real size and fails on a
     single pixel of overflow, so this cannot quietly drift back. */
  @page { size: 58mm 42mm; margin: 0; }
  body { margin: 0; color: #111; font-family: Arial, Helvetica, sans-serif; }

  .label {
    width: 58mm; height: 42mm; padding: 1.8mm 2.2mm; box-sizing: border-box;
    display: flex; flex-direction: column;
    font-size: 6pt; line-height: 1.16;
    page-break-after: always; overflow: hidden;
  }
  .label:last-child { page-break-after: auto; }

  /* The medicine, with what it cost at the right. One line, truncated rather
     than wrapped: a second line here costs the directions a line, and a
     medicine is recognised from its first half. */
  .med {
    display: flex; align-items: baseline; gap: 1.5mm;
    font-weight: bold; font-size: 7.6pt; line-height: 1.1;
  }
  .med .name { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .med .price { flex: 0 0 auto; font-size: 6.8pt; }

  /* The line the sticker exists for, and the only one allowed to grow.
     Monospace because that is what a dispensing label uses and because it fits
     more per line than Arial at the same legibility. */
  .dose {
    flex: 1 1 auto; min-height: 0; overflow: hidden;
    margin-top: 0.5mm; padding-bottom: 1mm;
    font-family: "Courier New", monospace;
    font-size: 7.4pt; font-weight: bold; line-height: 1.2;
    text-transform: uppercase;
    border-bottom: 0.3mm solid #111;
  }

  /* Printed on a monochrome thermal head the tint renders as a light stipple,
     which still reads as a band rather than as another paragraph. */
  .warn {
    flex: 0 0 auto;
    margin-top: 0.6mm; padding: 0.5mm 1mm;
    background: #f3efe4; border-left: 0.5mm solid #a8873f;
    font-size: 5.4pt; font-weight: bold; line-height: 1.15; color: #4a3c17;
    text-transform: uppercase;
    max-height: 4.4mm; overflow: hidden;
  }

  /* The audit block. Five short lines, each one thing somebody has to be able
     to read off the box without opening the system. */
  .audit {
    flex: 0 0 auto; margin-top: 0.8mm;
    font-size: 5.9pt; line-height: 1.24; color: #111;
  }
  .audit div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .audit .who { font-weight: bold; }

  /* The shop that handed it over. Bold name, then address and telephone: a
     patient holding a box and a question needs these on the sticker, not in a
     system somebody else can log into. */
  .foot {
    flex: 0 0 auto; margin-top: 0.8mm;
    font-size: 5.9pt; line-height: 1.2; color: #111;
  }
  .foot b {
    display: block; font-size: 6.4pt; font-weight: bold;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .foot div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
`;

/** Escape anything that came from the database before it becomes markup.
 *
 *  Names and directions are free text typed by staff. A product called
 *  "Vitamin C <500mg>" or a patient named "Smith & Sons" silently swallowed the
 *  rest of the line when interpolated raw, and a label that prints half a dose
 *  instruction is worse than one that fails to print.
 */
function esc(v: unknown): string {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Send labels to the printer.
 *
 *  `copies` exists because one dispensing often spans several boxes and each
 *  needs its own sticker. Repeating whole sets rather than consecutive
 *  duplicates keeps a patient's items together when they come off the printer.
 */
/** The markup for a sheet of labels, without printing it.
 *
 *  Split out so the overflow check can render the real thing at the real size.
 *  The sticker clips what does not fit, so a label that is too tall does not look
 *  broken — it looks finished with the bottom missing, which is the worst way for
 *  a dispensing label to fail. Measuring it is the only way to know. */
/** A dispensing timestamp, to the second.
 *
 *  Two dispensings of the same item on the same day are told apart by nothing
 *  else, so the seconds are not decoration — they are what a query about "the
 *  one from Tuesday afternoon" is answered with.
 */
function stamp(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const day = when.toLocaleDateString("en-GB",
    { day: "2-digit", month: "short", year: "2-digit" });
  const time = when.toLocaleTimeString("en-GB", { hour12: false });
  return `${day} ${time}`;
}

/** A date as a pharmacy writes it on a box: 31/03/2028. */
function shortDate(iso: string | null): string {
  if (!iso) return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  return when.toLocaleDateString("en-GB",
    { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function labelSheetHtml(labels: Label[], copies = 1): string {
  const sheet = Array.from({ length: Math.max(1, copies) }, () => labels).flat();
  const body = sheet
    .map((l) => {
      // Batch and expiry together, or neither. "Batch: — Exp: —" is a line of
      // punctuation that costs the directions a line and tells nobody anything;
      // stock received before batches were recorded genuinely has neither.
      const batchLine = [
        l.batch_number ? `Batch: ${esc(l.batch_number)}` : "",
        l.expiry_date ? `Exp: ${esc(shortDate(l.expiry_date))}` : "",
      ].filter(Boolean).join("  ");

      // The patient and the moment it was handed over, on one line, which is
      // where a real label puts them, and it saves the heading a whole line.
      const whoLine = [esc(l.patient_name), esc(stamp(l.dispensed_at))]
        .filter(Boolean).join("  ");

      // Which item of how many, so a patient carrying four boxes can tell
      // whether one is missing.
      const refLine = [
        l.rx_number ? `RxNo: ${esc(l.rx_number)}` : "",
        l.item_count > 1 ? `Item: ${l.item_number} of ${l.item_count}` : "",
        l.doctor_practice_no ? `Prof# ${esc(l.doctor_practice_no)}` : "",
        l.branch_code ? `[${esc(l.branch_code)}]` : "",
      ].filter(Boolean).join("  ");

      const qty = [
        l.quantity ? `${l.quantity}${l.dosage_form ? " " + esc(l.dosage_form) : ""}` : "",
        l.line_total ? `x${l.line_total.toFixed(2)}` : "",
      ].filter(Boolean).join("  ");

      return `
      <div class="label">
        <div class="med">
          <span class="name">${esc(l.product_name)} ${esc(l.strength)}</span>
          <span class="price">${qty}</span>
        </div>
        <div class="dose">${esc(l.dosage_instructions)}</div>
        ${l.warnings ? `<div class="warn">${esc(l.warnings)}</div>` : ""}
        <div class="audit">
          ${batchLine ? `<div>${batchLine}</div>` : ""}
          <div class="who">${whoLine}</div>
          ${l.dispensed_by ? `<div>Dispensed by: ${esc(l.dispensed_by)}</div>` : ""}
          ${l.doctor_name ? `<div>Doc. ${esc(l.doctor_name)}</div>` : ""}
          ${refLine ? `<div>${refLine}</div>` : ""}
        </div>
        <div class="foot">
          <b>${esc(l.branch_name || l.pharmacy_name)}</b>
          ${l.branch_address || l.pharmacy_address
            ? `<div>${esc(l.branch_address || l.pharmacy_address)}</div>` : ""}
          ${l.branch_phone || l.pharmacy_phone
            ? `<div>${esc(l.branch_phone || l.pharmacy_phone)}</div>` : ""}
        </div>
      </div>`;
    })
    .join("");
  return `<style>${LABEL_CSS}</style>${body}`;
}

/** The labels as a standalone document, for showing what will be printed.
 *
 *  Rendered into an iframe by the preview so that the sticker on screen and the
 *  sticker on the roll are the same markup and the same stylesheet, not two
 *  designs that agree today. `LabelSheet` drew its own once; the layouts drifted
 *  apart at the first change, which is a preview that lies, and somebody signs
 *  off on the screen while the printer disagrees.
 */
export function labelPreviewDoc(labels: Label[]): string {
  return `<!doctype html><html><head><meta charset="utf-8">` +
    `<style>${LABEL_CSS}` +
    // Stacked with a gap so the edges of each sticker are visible on screen.
    // The printer gets one per page and never sees this.
    `.label { page-break-after: auto; margin: 0 auto 3mm; ` +
    `box-shadow: 0 0 0 1px rgba(0,0,0,0.25); background: #fff; }` +
    `body { background: transparent; padding: 2mm 0; }` +
    `</style></head><body>` +
    labelSheetHtml(labels).replace(/^<style>[\s\S]*?<\/style>/, "") +
    `</body></html>`;
}

export function printLabels(labels: Label[], copies = 1) {
  if (labels.length === 0) return;
  const sheet = Array.from({ length: Math.max(1, copies) }, () => labels).flat();
  printHtml("Dispensing labels", LABEL_CSS,
            labelSheetHtml(sheet).replace(/^<style>[\s\S]*?<\/style>/, ""));
}
