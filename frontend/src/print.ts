import { Label, Sale } from "./types";
import { money } from "./api";

/** Open a print window with standalone HTML — keeps thermal/label output
 *  independent of the app's screen styling. */
function printHtml(title: string, css: string, body: string) {
  const win = window.open("", "_blank", "width=420,height=640");
  if (!win) {
    alert("Please allow pop-ups for this site to print.");
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
         <tr><td>Patient portion</td><td class="r">${money(sale.claim.patient_liable)}</td></tr>
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
  /* The printed sticker. Kept in step with the preview in styles.css on purpose:
     a preview that does not match what the printer produces is worse than no
     preview, because somebody signs off on the screen and the roll disagrees.

     Millimetres throughout. A thermal label is a physical object and points
     drift between browsers; millimetres do not. */
  @page { size: 58mm 42mm; margin: 0; }
  body { margin: 0; color: #111; font-family: Arial, Helvetica, sans-serif; }

  .label {
    width: 58mm; height: 42mm; padding: 3.4mm 3.6mm; box-sizing: border-box;
    display: flex; flex-direction: column;
    font-size: 7.6pt; line-height: 1.3;
    page-break-after: always; overflow: hidden;
  }
  .label:last-child { page-break-after: auto; }

  .top { display: flex; align-items: baseline; justify-content: space-between; gap: 2mm; padding-bottom: 1.2mm; }
  .patient { font-weight: bold; font-size: 9pt; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .price { font-size: 7.6pt; color: #444; white-space: nowrap; }

  .drug { display: flex; flex-direction: column; padding-bottom: 1.4mm; }
  .med { font-weight: bold; font-size: 10.5pt; line-height: 1.15; }
  .form { font-size: 7pt; color: #555; }

  /* The line the sticker exists for. */
  .dose {
    padding: 1.8mm 0; font-size: 11pt; font-weight: bold; line-height: 1.32;
    border-top: 0.35mm solid #111; border-bottom: 0.35mm solid #111;
  }

  /* Printed on a monochrome thermal head the tint renders as a light stipple,
     which still reads as a band rather than as another paragraph. */
  .warn {
    margin-top: 1.4mm; padding: 1.1mm 1.4mm;
    background: #f3efe4; border-left: 0.7mm solid #a8873f;
    font-size: 6.9pt; font-weight: bold; line-height: 1.28; color: #4a3c17;
    text-transform: uppercase;
  }

  .audit {
    margin-top: 1.8mm; padding-top: 1.4mm; border-top: 0.2mm solid rgba(17,17,17,0.28);
    font-size: 6.6pt; color: #333;
  }
  .audit .row { display: flex; gap: 2.2mm; flex-wrap: wrap; margin-bottom: 0.5mm; }
  .audit .pair { display: inline-flex; align-items: baseline; gap: 1.1mm; white-space: nowrap; }
  .audit i { font-style: normal; font-size: 5.9pt; text-transform: uppercase; letter-spacing: 0.06em; color: #777; font-weight: bold; }
  .audit b { font-weight: 500; }
  .audit .mono { font-family: "Courier New", monospace; font-size: 6.4pt; }

  .foot {
    margin-top: auto; padding-top: 1.6mm; border-top: 0.2mm solid rgba(17,17,17,0.28);
    display: flex; flex-direction: column; font-size: 6.4pt; color: #444;
  }
  .foot b { font-size: 7.4pt; color: #111; text-transform: uppercase; }
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
export function printLabels(labels: Label[], copies = 1) {
  if (labels.length === 0) return;
  const sheet = Array.from({ length: Math.max(1, copies) }, () => labels).flat();
  const body = sheet
    .map(
      (l) => `
      <div class="label">
        <div class="top">
          <span class="patient">${esc(l.patient_name)}</span>
          ${l.line_total > 0 ? `<span class="price">${esc(l.line_total.toFixed(2))}</span>` : ""}
        </div>
        <div class="drug">
          <span class="med">${esc(l.product_name)} ${esc(l.strength)}</span>
          <span class="form">${esc([l.dosage_form, l.quantity ? `Qty ${l.quantity}` : ""].filter(Boolean).join(" · "))}</span>
        </div>
        <div class="dose">${esc(l.dosage_instructions)}</div>
        ${l.warnings ? `<div class="warn">${esc(l.warnings)}</div>` : ""}
        <div class="audit">
          <div class="row">
            <span class="pair"><i>Batch</i> <b class="mono">${esc(l.batch_number || "not recorded")}</b></span>
            ${l.expiry_date ? `<span class="pair"><i>Exp</i> <b class="mono">${esc(String(l.expiry_date))}</b></span>` : ""}
          </div>
          <div class="row">
            <span class="pair"><i>Script</i> <b class="mono">${esc(l.rx_number)}</b></span>
            <span class="pair"><i>Item</i> <b>${l.item_number} of ${l.item_count}</b></span>
          </div>
          <div class="row">
            <span class="pair"><i>Checked</i> <b>${esc(l.dispensed_by || "not recorded")}</b></span>
            <span class="pair"><i>On</i> <b>${new Date(l.dispensed_at).toLocaleString("en-ZA")}</b></span>
          </div>
          ${l.doctor_name ? `<div class="row"><span class="pair"><i>Prescriber</i> <b>${esc(l.doctor_name)}${l.doctor_practice_no ? ` ${esc(l.doctor_practice_no)}` : ""}</b></span></div>` : ""}
          ${l.repeats_remaining > 0 ? `<div class="row"><span class="pair"><i>Repeats</i> <b>${l.repeats_remaining} left</b></span></div>` : ""}
        </div>
        <div class="foot">
          <b>${esc(l.pharmacy_name)}</b>
          <span>${esc([l.pharmacy_address, l.pharmacy_phone].filter(Boolean).join("  ·  ")
            || (l.pharmacy_reg_no ? `Reg ${l.pharmacy_reg_no}` : ""))}</span>
        </div>
      </div>`,
    )
    .join("");
  printHtml("Dispensing labels", LABEL_CSS, body);
}
