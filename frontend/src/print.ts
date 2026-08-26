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
     drift between browsers; millimetres do not.

     ---

     **It has to fit on one label.** The previous design did not, and because the
     overflow was hidden it did not look broken — it looked finished with the
     bottom missing. Measured across forty-two real labels, every one of them
     overflowed: the shortest needed 61mm of a 42mm sticker and the worst needed
     79mm. What got cut was the end: the pharmacy name, the date, the script
     number. A dispensing label that silently loses its footer is worse than one
     that is obviously wrong.

     So the sticker now carries what a sticker is for, and the rest lives where
     it is actually looked up:

       kept    patient, medicine and strength, the directions, warnings,
               the pharmacy, the date, the script number
       dropped batch and expiry (in the stock register, and in the recall
               trace, which is where anybody looks for them), the prescriber
               (on the script), repeats left (the patient asks), the price
               (on the receipt)

     qa/label-fits.mjs measures the real markup at the real size and fails on a
     single pixel of overflow, so this cannot quietly drift back. */
  @page { size: 58mm 42mm; margin: 0; }
  body { margin: 0; color: #111; font-family: Arial, Helvetica, sans-serif; }

  .label {
    width: 58mm; height: 42mm; padding: 2.2mm 2.6mm; box-sizing: border-box;
    display: flex; flex-direction: column;
    font-size: 7pt; line-height: 1.22;
    page-break-after: always; overflow: hidden;
  }
  .label:last-child { page-break-after: auto; }

  /* One line, and it truncates rather than wrapping: a second line here costs
     the directions a line, and the name is recognised from its first half. */
  .patient {
    font-weight: bold; font-size: 8.4pt; line-height: 1.15;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }

  .med {
    font-weight: bold; font-size: 9.2pt; line-height: 1.12; margin-top: 0.6mm;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .form { font-size: 6.4pt; color: #555; }

  /* The line the sticker exists for, and the one that is allowed to grow.
     Everything above and below it is fixed, so a long direction takes the room
     rather than pushing the footer off the label. */
  .dose {
    flex: 1 1 auto; min-height: 0; overflow: hidden;
    margin-top: 1.2mm; padding: 1.2mm 0;
    font-size: 9.6pt; font-weight: bold; line-height: 1.24;
    border-top: 0.3mm solid #111; border-bottom: 0.3mm solid #111;
  }

  /* Printed on a monochrome thermal head the tint renders as a light stipple,
     which still reads as a band rather than as another paragraph. */
  .warn {
    flex: 0 0 auto;
    margin-top: 1mm; padding: 0.8mm 1.2mm;
    background: #f3efe4; border-left: 0.6mm solid #a8873f;
    font-size: 6.2pt; font-weight: bold; line-height: 1.2; color: #4a3c17;
    text-transform: uppercase;
    max-height: 7mm; overflow: hidden;
  }

  /* One footer line, not five audit rows. The pharmacy is a legal requirement on
     a dispensed label; the date and the script number are what somebody quotes
     back on the telephone. */
  /* Two lines, not one row sharing a width.
     Side by side, a long script number squeezed the pharmacy name until it
     ellipsed to "RX5000 Phar…" — and the dispensing pharmacy is a legal
     requirement on the label while the reference is a convenience. Stacked, the
     name gets the full width and the reference cannot take it. */
  .foot {
    flex: 0 0 auto;
    margin-top: 1mm; padding-top: 0.9mm;
    border-top: 0.2mm solid rgba(17,17,17,0.3);
    display: flex; flex-direction: column; gap: 0.2mm;
    font-size: 6.2pt; color: #444;
  }
  .foot b {
    font-size: 6.6pt; color: #111; font-weight: bold; line-height: 1.15;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .foot .mono {
    font-family: "Courier New", monospace; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
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
export function labelSheetHtml(labels: Label[], copies = 1): string {
  const sheet = Array.from({ length: Math.max(1, copies) }, () => labels).flat();
  const body = sheet
    .map(
      (l) => `
      <div class="label">
        <div class="patient">${esc(l.patient_name)}</div>
        <div class="med">${esc(l.product_name)} ${esc(l.strength)}</div>
        <div class="form">${esc([l.dosage_form, l.quantity ? `Qty ${l.quantity}` : "",
                                 l.item_count > 1 ? `${l.item_number} of ${l.item_count}` : ""]
                                .filter(Boolean).join(" · "))}</div>
        <div class="dose">${esc(l.dosage_instructions)}</div>
        ${l.warnings ? `<div class="warn">${esc(l.warnings)}</div>` : ""}
        <div class="foot">
          <b>${esc(l.pharmacy_name)}</b>
          <span class="mono">${esc(l.rx_number)} · ${new Date(l.dispensed_at).toLocaleDateString("en-ZA")}</span>
        </div>
      </div>`,
    )
    .join("");
  return `<style>${LABEL_CSS}</style>${body}`;
}

export function printLabels(labels: Label[], copies = 1) {
  if (labels.length === 0) return;
  const sheet = Array.from({ length: Math.max(1, copies) }, () => labels).flat();
  printHtml("Dispensing labels", LABEL_CSS,
            labelSheetHtml(sheet).replace(/^<style>[\s\S]*?<\/style>/, ""));
}
