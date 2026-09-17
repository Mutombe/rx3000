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
  // A receipt that must not say what the medicines were.
  //
  // A dispensing slip carries somebody's health on it, and one handed across a
  // counter in a queue discloses it to whoever is standing there. The choice is
  // made at the dispensary before anything prints and travels on the sale, so a
  // cashier who never met the patient still honours it.
  //
  // What is withheld is the NAMES. The count, the totals, the tax and the
  // invoice number all print, because it is a tax invoice and because the
  // pharmacy can reconstruct the lines from the number when it has to.
  const discreet = !!(sale as { receipt_private?: boolean }).receipt_private;
  const itemCount = sale.items.reduce((n, i) => n + (i.quantity || 0), 0);
  const lines = discreet
    ? [`<tr><td>${itemCount} item${itemCount === 1 ? "" : "s"} dispensed</td>`
       + `<td class="r">${money(sale.items.reduce((n, i) => n + (i.line_total || 0), 0))}</td></tr>`
       + `<tr><td colspan="2" class="sub">Itemised copy on request</td></tr>`]
    : sale.items
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
         at 8.4pt. It sits inside the audit block now, which is where a
         dispenser looks for it, with the time it was handed over on the line
         under it rather than butted against it.
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
  /* THE STICKER DECIDES THE PAGE, NOT THIS FILE.

     It said a fixed 58mm by 42mm, which is one roll. Print that onto a sticker of
     any other size and Chrome centres the small page inside the big one, so the
     label came out with a band of white above the medicine and another below
     the telephone — a third of the sticker spent on nothing, and the text
     shrunk to fit the part that was left.

     Size auto takes whatever paper the printer says it has, and the label fills
     it. A pharmacy that changes its roll changes nothing here. */
  @page { size: auto; margin: 0; }
  body { margin: 0; color: #111; font-family: Arial, Helvetica, sans-serif; }

  .label {
    width: 100%; height: 100vh; padding: 1.3mm 2mm; box-sizing: border-box;
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
    font-weight: bold; font-size: 6.9pt; line-height: 1.08;
  }
  /* The medicine's name, in full, wrapping onto as many lines as it needs.
     It was clipped with an ellipsis on one line, which printed
     "SODIUM CHLORIDE 0.9% 1000M" on a real label — the strength losing its last
     letter, and 1000M is not a unit. This is the line a patient reads to know
     what is in the box, so it is the last thing on the sticker allowed to be
     shortened, and break-word so a name longer than the sticker breaks rather
     than running off the edge. */
  .med .name {
    flex: 1 1 auto; min-width: 0;
    white-space: normal; overflow-wrap: break-word; word-break: break-word;
    line-height: 1.15;
  }
  .med { align-items: flex-start; }
  .med .price { flex: 0 0 auto; font-size: 6.8pt; }

  /* The line the sticker exists for, and the only one allowed to grow.
     Monospace because that is what a dispensing label uses and because it fits
     more per line than Arial at the same legibility. */
  .dose {
    flex: 1 1 auto; min-height: 0; overflow: hidden;
    margin-top: 0.5mm; padding-bottom: 0.4mm;
    font-family: "Courier New", monospace;
    font-size: 6.8pt; font-weight: bold; line-height: 1.16;
    text-transform: uppercase;
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
    flex: 0 0 auto; margin-top: 0.5mm;
    font-size: 5.9pt; line-height: 1.22; color: #111;
  }
  .audit div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .audit .who { font-weight: bold; }
  .audit .when { color: #333; }

  /* The shop that handed it over. Bold name, then address and telephone: a
     patient holding a box and a question needs these on the sticker, not in a
     system somebody else can log into. */
  .foot {
    flex: 0 0 auto; margin-top: 0.5mm;
    font-size: 5.9pt; line-height: 1.2; color: #111;
  }
  .sched {
    flex: 0 0 auto; align-self: center; margin-left: 1mm; padding: 0 0.7mm;
    border: 0.25mm solid #111; border-radius: 0.6mm;
    font-size: 5.6pt; font-weight: bold; vertical-align: 0.4mm;
  }
  .foot b {
    display: block; font-size: 6.4pt; font-weight: bold;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .foot div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  /* The shop, then the street, then the number. The name carries the weight of
     a heading without being bigger than the telephone line, which is the one
     thing read in a hurry. The street is allowed to wrap onto a second line
     rather than lose its town to an ellipsis. */
  .foot-who { font-weight: bold; font-size: 6.1pt; }
  .foot-where {
    font-size: 5.6pt; color: #333;
    white-space: normal; overflow: visible; text-overflow: clip;
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
        l.batch_number ? `Batch. ${esc(l.batch_number)}` : "",
        l.expiry_date ? `Exp. ${esc(shortDate(l.expiry_date))}` : "",
      ].filter(Boolean).join("  ");

      // Who made it, on its own line: sharing with the batch cost both of them
      // their ends — "Batch: VX-4471 Exp: 31/03/2028 Mfr: Varichem Pharm…" —
      // and a manufacturer truncated to a syllable answers nobody's question.
      const madeBy = l.manufacturer ? `Mfr. ${esc(l.manufacturer)}` : "";

      // The patient on their own line, and when it was handed over under it.
      //
      // They shared a line to save one. What that actually produced was
      // "Samuel Matoveru 17 Sept 26 14:22:09", where the name runs straight
      // into a date with nothing between them but a gap — and the name is the
      // one thing on the sticker somebody checks before handing the bag over.
      const whoLine = esc(l.patient_name);
      const whenLine = esc(stamp(l.dispensed_at));

      // Which item of how many, so a patient carrying four boxes can tell
      // whether one is missing.
      const refLine = [
        l.rx_number ? `RxNo. ${esc(l.rx_number)}` : "",
        l.item_count > 1 ? `Item. ${l.item_number} of ${l.item_count}` : "",
        l.doctor_practice_no ? `Prof# ${esc(l.doctor_practice_no)}` : "",
        l.branch_code ? `[${esc(l.branch_code)}]` : "",
      ].filter(Boolean).join("  ");

      // How much is in the box, and not what it cost. A price on a sticker that
      // goes into somebody's bag tells the patient nothing they need and tells
      // anybody who sees it what they paid. Money belongs on the receipt.
      const qty = l.quantity
        ? `${l.quantity}${l.dosage_form ? " " + esc(l.dosage_form) : ""}`
        : "";

      return `
      <div class="label">
        ${/* The schedule sits outside the name, which truncates: put inside
              it, an S4 on a long medicine name was the first thing to be cut
              off, and the schedule is the one word on the line that must not
              be. */ ""}
        <div class="med">
          <span class="name">${esc(l.product_name)} ${esc(l.strength)}</span>
          ${/* The classification the law here uses, not the internal ordinal.
                This printed "S4" on a box handed over in Harare, where a
                schedule 4 medicine is a PP — a South African classification on
                a Zimbabwean pharmacy's own sticker. Falls back to the old form
                only for a label built before the code existed. */ ""}
          ${l.schedule
            ? `<span class="sched">${esc(l.schedule_code || `S${l.schedule}`)}</span>` : ""}
          <span class="price">${qty}</span>
        </div>
        <div class="dose">${esc(l.dosage_instructions)}</div>
        ${l.warnings ? `<div class="warn">${esc(l.warnings)}</div>` : ""}
        <div class="audit">
          ${batchLine ? `<div>${batchLine}</div>` : ""}
          ${madeBy ? `<div>${madeBy}</div>` : ""}
          ${whoLine ? `<div class="who">${whoLine}</div>` : ""}
          ${whenLine ? `<div class="when">${whenLine}</div>` : ""}
          ${l.dispensed_by ? `<div>Dispensed by. ${esc(l.dispensed_by)}</div>` : ""}
          ${l.doctor_name ? `<div>Doc. ${esc(l.doctor_name)}</div>` : ""}
          ${refLine ? `<div>${refLine}</div>` : ""}
        </div>
        <div class="foot">
          ${/* WHOSE PHARMACY DISPENSED THIS, then how to reach them.

                The name and the street were taken off to save three lines on a
                small sticker, on the reasoning that the bag already says it.
                A bag is not what a patient still has at ten at night, and a box
                that cannot say where it came from is a box nobody can query or
                return. The shop that handed it over goes first, its street
                under it, and the number to ring in bold beneath both — read in
                that order because that is the order the questions come in.

                The branch's own details where it has them, the pharmacy's where
                it does not, so a single-shop pharmacy that never filled in a
                branch record still prints something true. */ ""}
          ${(l.branch_name || l.pharmacy_name)
            ? `<div class="foot-who">${esc(l.branch_name || l.pharmacy_name)}</div>` : ""}
          ${(l.branch_address || l.pharmacy_address)
            ? `<div class="foot-where">${esc(l.branch_address || l.pharmacy_address)}</div>` : ""}
          ${(l.branch_phone || l.pharmacy_phone)
            ? `<b>Tel: ${esc(l.branch_phone || l.pharmacy_phone)}</b>` : ""}
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

/** Why this label may not print, or "" when it may.
 *
 *  A medicine label names its batch and its expiry, or it does not go on a box:
 *  those two lines are what a recall is traced by. The server decides and says
 *  why; this applies the same rule when it has not, so an older server cannot
 *  let a label out that a newer one would refuse.
 */
export function labelRefusal(l: Label): string {
  if (l.printable === false) return l.blocked_reason || "This label can't be printed.";
  if (!l.batch_number) return "No batch on this line, and a medicine label must name its batch.";
  if (!l.expiry_date) return `Batch ${l.batch_number} has no expiry date on file.`;
  return "";
}

export interface RefusedLabel { label: Label; why: string }

/** The labels that may print, and the ones held back with the reason for each. */
export function splitPrintable(labels: Label[]): { printable: Label[]; refused: RefusedLabel[] } {
  const printable: Label[] = [];
  const refused: RefusedLabel[] = [];
  for (const label of labels) {
    const why = labelRefusal(label);
    if (why) refused.push({ label, why });
    else printable.push(label);
  }
  return { printable, refused };
}

/** What to tell the dispenser about labels that were held back — by medicine,
 *  so they know which box is still without a sticker. */
export function refusedSummary(refused: RefusedLabel[]): string {
  const name = (l: Label) => `${l.product_name}${l.strength ? ` ${l.strength}` : ""}`;
  if (refused.length === 1) return `${name(refused[0].label)} was not printed. ${refused[0].why}`;
  return `${refused.length} labels were not printed. `
    + refused.map((r) => `${name(r.label)}. ${r.why}`).join(" ");
}

/** Print through the browser's dialog. Refused labels never reach the sheet,
 *  whoever called this; what was held back is returned so the caller can say. */
export function printLabels(labels: Label[], copies = 1): { printed: number; refused: RefusedLabel[] } {
  const { printable, refused } = splitPrintable(labels);
  if (printable.length === 0) return { printed: 0, refused };
  const sheet = Array.from({ length: Math.max(1, copies) }, () => printable).flat();
  // A SPACE, NOT A NAME.
  //
  // Chrome prints the document's title into the page header, and on a 42mm
  // sticker that header is a third of the label: a real one came off the roll
  // reading "3 PM" in one corner and "Dispensing labels" in the other, with the
  // medicine pushed into the bottom two thirds. The title is the half of that
  // we control, so it says nothing. A blank title is not enough — Chrome falls
  // back to printing the URL — so it is a space.
  //
  // The other half, the date and time, is the browser's and no stylesheet can
  // remove it. It is off when "Headers and footers" is unticked in the print
  // dialog, which Chrome then remembers for that printer; printing through the
  // label agent instead skips the browser dialog altogether.
  printHtml(" ", LABEL_CSS,
            labelSheetHtml(sheet).replace(/^<style>[\s\S]*?<\/style>/, ""));
  return { printed: sheet.length, refused };
}
