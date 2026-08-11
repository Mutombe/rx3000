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

export function printReceipt(sale: Sale, pharmacyName = "RX3000 Pharmacy", regNo = "") {
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
       <div class="sub">${regNo ? `Reg. ${regNo}<br>` : ""}Tax Invoice</div></div>
     <table>
       <tr><td>Invoice</td><td class="r">${sale.sale_number}</td></tr>
       <tr><td>Date</td><td class="r">${when}</td></tr>
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
  @page { size: 70mm 40mm; margin: 2mm; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 8.5px; margin: 0; color: #000; }
  .label { width: 66mm; height: 36mm; padding: 2mm; border: 1px solid #000; box-sizing: border-box;
           page-break-after: always; overflow: hidden; }
  .label:last-child { page-break-after: auto; }
  .pharmacy { font-size: 8px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.3px; }
  .patient { font-size: 11px; font-weight: bold; margin: 1mm 0 0.5mm; }
  .med { font-size: 10.5px; font-weight: bold; }
  .dose { font-size: 10px; margin: 0.7mm 0; }
  .warn { font-size: 7.5px; font-style: italic; border-top: 1px solid #000; padding-top: 0.6mm; margin-top: 0.6mm; }
  .meta { font-size: 7px; display: flex; justify-content: space-between; margin-top: 0.6mm; }
  .sched { font-size: 7.5px; font-weight: bold; }
`;

export function printLabels(labels: Label[]) {
  if (labels.length === 0) return;
  const body = labels
    .map(
      (l) => `
      <div class="label">
        <div class="pharmacy">${l.pharmacy_name}${l.pharmacy_reg_no ? ` &nbsp;·&nbsp; Reg ${l.pharmacy_reg_no}` : ""}</div>
        <div class="patient">${l.patient_name}</div>
        <div class="med">${l.product_name} ${l.strength} ${l.dosage_form ? `(${l.dosage_form})` : ""} &nbsp;— &nbsp;Qty ${l.quantity}</div>
        <div class="dose">${l.dosage_instructions}</div>
        ${l.warnings ? `<div class="warn">${l.warnings}</div>` : ""}
        <div class="meta">
          <span>${l.rx_number} · ${new Date(l.dispensed_at).toLocaleDateString("en-ZA")}</span>
          <span>${l.dispensed_by}</span>
        </div>
        <div class="meta">
          <span>${l.batch_number ? `Batch ${l.batch_number}` : ""}${l.expiry_date ? ` · Exp ${l.expiry_date}` : ""}</span>
          <span class="sched">${l.schedule > 0 ? `S${l.schedule}` : ""}${l.repeats_remaining > 0 ? ` · ${l.repeats_remaining} repeat(s) left` : ""}</span>
        </div>
      </div>`,
    )
    .join("");
  printHtml("Dispensing labels", LABEL_CSS, body);
}
