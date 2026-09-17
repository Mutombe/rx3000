/** The dispensing label as a PDF, at the exact size of the sticker.
 *
 *  WHY A PDF, AND NOT A PRINTER LANGUAGE.
 *
 *  There is no shortage of label printer languages. Zebra speaks ZPL, TSC and
 *  most of the cheap brands speak TSPL, older Zebras speak EPL, receipt heads
 *  speak ESC/POS. Writing a renderer for each is writing a text-layout engine
 *  per vendor — font metrics, wrapping, positioning, all of it again — and the
 *  same label then looks subtly different depending on which printer it came
 *  off. That does not scale past the second pharmacy.
 *
 *  Every one of those printers has a Windows driver, and every Windows driver
 *  can print a page. So the label is laid out once, here, as a PDF at the
 *  sticker's real size, and handed to the driver by name. The driver does the
 *  rasterising, at whatever resolution its printer has. A pharmacy that buys a
 *  different printer changes nothing: if Windows can see it, it prints, and it
 *  prints the identical label.
 *
 *  WHY IT IS WRITTEN BY HAND.
 *
 *  A PDF carrying text in the standard fonts needs no font embedding, no
 *  compression and no object streams — it is a few hundred bytes of plain
 *  structure. Pulling in a PDF library for that would be a megabyte of
 *  dependency to draw nine lines of text, in an application that is deliberate
 *  about carrying ten.
 *
 *  WHY IT IS VECTOR AND NOT A BITMAP.
 *
 *  A bitmap has to be rendered at one resolution and every printer has its own:
 *  203dpi on a ZD421, 300 on the model above it. Text in a PDF is resolution
 *  free, so the same file is crisp on both, and a 58mm sticker is small enough
 *  that a bitmap at the wrong density is visibly soft.
 */
import { code128Rects, code128Width } from "./code128";
import type { Label } from "./types";

/** A PDF point is 1/72 inch; a millimetre is 72/25.4 of one. */
const PT = 72 / 25.4;

/** Millimetres of margin. The printer's own unprintable edge is usually under
 *  1mm, and a label that runs closer than this to the edge looks like a mistake
 *  even when it prints. */
const PAD_X = 2;
const PAD_Y = 1.0;

/** Leading, as a multiple of the point size. */
const LEAD = 1.1;

export interface Sticker {
  /** Millimetres. The roll the pharmacy actually loaded. */
  wide: number;
  tall: number;
}

export const DEFAULT_STICKER: Sticker = { wide: 58, tall: 42 };

/** The three fonts a label needs, and nothing more.
 *
 *  All three are standard PDF fonts, so the file names them and every reader
 *  and driver already has them. Courier for the directions because that is
 *  what a dispensed label uses, and because a monospace face at the same point
 *  size fits more characters on a 58mm line.
 */
const FONTS = { plain: "F1", bold: "F2", mono: "F3" } as const;
export type FontName = keyof typeof FONTS;

/** The CSS for a font, so a canvas can measure and draw what the PDF will. */
export function cssFontFor(font: FontName, size: number): string {
  return font === "plain" ? `${size}pt Helvetica, Arial, sans-serif`
    : font === "bold" ? `bold ${size}pt Helvetica, Arial, sans-serif`
    : `bold ${size}pt "Courier New", Courier, monospace`;
}

/** How wide a string is, in points, in the font the PDF will use.
 *
 *  Measured with a canvas rather than from a table of font metrics: the canvas
 *  has the real face and gives the real advance widths, and a wrapping rule
 *  that disagrees with the renderer by a few per cent is a rule that overflows
 *  the sticker on exactly the long names that matter.
 *
 *  Falls back to a flat estimate where there is no canvas rather than refusing
 *  to produce a label.
 */
let ruler: CanvasRenderingContext2D | null | undefined;
function widthOf(text: string, font: FontName, size: number): number {
  if (ruler === undefined) {
    try { ruler = document.createElement("canvas").getContext("2d"); }
    catch { ruler = null; }
  }
  if (!ruler) {
    // No canvas: a build script, a test, a server. Estimated from the widths
    // these faces actually have, and deliberately on the generous side —
    // Courier is exactly 0.6em, and Helvetica averages near 0.5em in mixed
    // case but closer to 0.62em in the bold capitals a medicine name is set
    // in. An estimate that runs narrow reports a label as fitting when it does
    // not, which is the one answer worth never giving.
    const em = font === "mono" ? 0.6 : font === "bold" ? 0.62 : 0.55;
    return text.length * size * em;
  }
  ruler.font = cssFontFor(font, size);
  return ruler.measureText(text).width;
}

/** Break text to a width, on spaces where it can and mid-word where it must.
 *
 *  A medicine name is one long token often enough — AMOXYCILLIN/CLAVULANATE —
 *  that breaking only on spaces puts it past the edge of the sticker, where the
 *  driver clips it without saying so.
 */
function wrap(text: string, font: FontName, size: number, limit: number,
              firstLimit = limit): string[] {
  const out: string[] = [];
  // The first line is often narrower than the rest, because something sits
  // beside it. Only that line pays for it: the quantity and the classification
  // occupy the top right corner and nothing below it, so wrapping every line of
  // a medicine name to the width left over turned a two-line name into four.
  const widthAt = () => (out.length === 0 ? firstLimit : limit);
  for (const paragraph of String(text ?? "").split(/\n+/)) {
    let line = "";
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      const next = line ? `${line} ${word}` : word;
      if (widthOf(next, font, size) <= widthAt()) { line = next; continue; }
      if (line) { out.push(line); line = ""; }
      let rest = word;
      while (widthOf(rest, font, size) > widthAt() && rest.length > 1) {
        let cut = rest.length;
        while (cut > 1 && widthOf(rest.slice(0, cut), font, size) > widthAt()) cut -= 1;
        out.push(rest.slice(0, cut));
        rest = rest.slice(cut);
      }
      line = rest;
    }
    if (line) out.push(line);
  }
  return out;
}

/** Text inside a PDF string. Three characters end the string or escape it. */
function pdfText(s: string): string {
  return String(s ?? "")
    // WinAnsi is a single-byte encoding and the standard fonts use it. A
    // character outside it would be written as a byte meaning something else,
    // so anything beyond Latin-1 is dropped rather than mistranslated.
    .replace(/[^\x20-\x7E\xA0-\xFF]/g, "")
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)");
}

interface Block {
  at: number;                       // points from the top
  lines: string[];
  font: FontName;
  size: number;
  align: "left" | "right";
}

/** Everything on the sticker, in the order it is read, measured before it is
 *  drawn so the whole thing can be checked against the paper. */
function layout(l: Label, sticker: Sticker): { blocks: Block[]; usedMm: number } {
  const inner = (sticker.wide - PAD_X * 2) * PT;
  const blocks: Block[] = [];
  let y = 0;

  const put = (text: string, font: FontName, size: number, gap = 1.5,
               firstLimit = inner) => {
    const lines = wrap(text, font, size, inner, firstLimit);
    if (!lines.length) return;
    blocks.push({ at: y, lines, font, size, align: "left" });
    y += lines.length * size * LEAD + gap;
  };

  // The medicine, with the quantity and the classification beside it. The name
  // gets the width left over after them, so it wraps rather than runs under.
  const badge = [
    l.quantity ? `${l.quantity}${l.dosage_form ? ` ${l.dosage_form}` : ""}` : "",
    l.schedule_code || (l.schedule ? `S${l.schedule}` : ""),
  ].filter(Boolean).join("   ");
  const badgeW = badge ? widthOf(badge, "bold", 6.5) + 6 : 0;
  put(`${l.product_name ?? ""} ${l.strength ?? ""}`.trim(), "bold", 6.6, 0.9,
      inner - badgeW);
  if (badge) {
    blocks.push({ at: 0, lines: [badge], font: "bold", size: 6.5, align: "right" });
  }

  put(String(l.dosage_instructions ?? "").toUpperCase(), "mono", 5.9, 1.2);
  if (l.warnings) put(String(l.warnings).toUpperCase(), "bold", 5.6, 2);

  const batch = [
    l.batch_number ? `Batch. ${l.batch_number}` : "",
    l.expiry_date ? `Exp. ${new Date(l.expiry_date).toLocaleDateString("en-GB")}` : "",
  ].filter(Boolean).join("  ");
  if (batch) put(batch, "plain", 5.6, 0.35);
  if (l.manufacturer) put(`Mfr. ${l.manufacturer}`, "plain", 5.6, 0.35);
  // The patient, then when it was handed over on the line under it. They shared
  // a line once and it read as a name running into a date.
  if (l.patient_name) put(l.patient_name, "bold", 5.9, 0.25);
  if (l.dispensed_at) {
    put(new Date(l.dispensed_at).toLocaleString("en-GB", { hour12: false }),
        "plain", 5.6, 0.35);
  }
  if (l.dispensed_by) put(`Dispensed by. ${l.dispensed_by}`, "plain", 5.6, 0.25);
  if (l.doctor_name) put(`Doc. ${l.doctor_name}`, "plain", 5.6, 0.35);

  const ref = [
    l.rx_number ? `RxNo. ${l.rx_number}` : "",
    (l.item_count ?? 0) > 1 ? `Item. ${l.item_number} of ${l.item_count}` : "",
    l.doctor_practice_no ? `Prof# ${l.doctor_practice_no}` : "",
    l.branch_code ? `[${l.branch_code}]` : "",
  ].filter(Boolean).join("  ");
  if (ref) put(ref, "plain", 5.6, 0.9);

  // Whose pharmacy dispensed it, and how to reach them.
  const who = l.branch_name || l.pharmacy_name;
  const where = l.branch_address || l.pharmacy_address;
  const phone = l.branch_phone || l.pharmacy_phone;
  if (who) put(who, "bold", 5.9, 0.2);
  if (where) put(where, "plain", 5.4, 0.2);
  if (phone) put(`Tel: ${phone}`, "bold", 6.4, 0);

  return { blocks, usedMm: y / PT + PAD_Y * 2 };
}

/** One line of the label, placed. Points, measured from the TOP left, which is
 *  how a label is read and how a canvas draws.
 *
 *  Exported so that anything showing the label draws exactly what the PDF
 *  contains, from the same numbers. A preview computed separately is a preview
 *  that drifts, and the whole reason this file exists is that nobody could see
 *  a label before it came off a roll.
 */
export interface Placed {
  text: string; x: number; y: number; font: FontName; size: number;
}

export function labelPlacement(l: Label, sticker: Sticker = DEFAULT_STICKER): Placed[] {
  const W = sticker.wide * PT;
  const out: Placed[] = [];
  for (const block of layout(l, sticker).blocks) {
    block.lines.forEach((text, i) => {
      const x = block.align === "right"
        ? W - PAD_X * PT - widthOf(text, block.font, block.size)
        : PAD_X * PT;
      out.push({ text, x, y: PAD_Y * PT + block.at + (i + 1) * block.size * LEAD,
                 font: block.font, size: block.size });
    });
  }
  return out;
}

/** The label as a PDF file, ready to hand to a printer by name. */
export function labelPdf(l: Label, sticker: Sticker = DEFAULT_STICKER): Uint8Array {
  const W = sticker.wide * PT;
  const H = sticker.tall * PT;

  const content = labelPlacement(l, sticker)
    // PDF's origin is the bottom left and the placement is from the top, which
    // is how a label is read. The nudge is the descender.
    .map((line) => `BT /${FONTS[line.font]} ${line.size} Tf `
      + `${line.x.toFixed(2)} ${(H - line.y + line.size * 0.24).toFixed(2)} Td `
      + `(${pdfText(line.text)}) Tj ET`)
    .join("\n");

  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${W.toFixed(2)} ${H.toFixed(2)}] `
      + "/Resources << /Font << /F1 5 0 R /F2 6 0 R /F3 7 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold /Encoding /WinAnsiEncoding >>",
  ];

  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((body, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const at of offsets) pdf += `${String(at).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\n`
    + `startxref\n${xref}\n%%EOF\n`;

  // Latin-1, because the fonts are declared WinAnsiEncoding and `pdfText` has
  // already dropped anything that cannot be written as one byte.
  const bytes = new Uint8Array(pdf.length);
  for (let i = 0; i < pdf.length; i += 1) bytes[i] = pdf.charCodeAt(i) & 0xff;
  return bytes;
}

/** How much of the sticker the content needs, in millimetres.
 *
 *  A label that wants more than the paper has is clipped by the driver without
 *  complaint, which is the failure worth catching before a roll of them is
 *  printed.
 */
export function labelHeightMm(l: Label, sticker: Sticker = DEFAULT_STICKER): number {
  return layout(l, sticker).usedMm;
}

/** A script's barcode, as its own small label.
 *
 *  MCAZ expects a dispensed script to carry a barcode, and what it encodes is
 *  the Rx number — the identity this system already issues and already treats
 *  as the script's name. Printed as its own sticker rather than squeezed onto
 *  the dispensing label, because a barcode that is too short or too dense does
 *  not read, and the dispensing label has no room to spare: it fits at 40.5mm
 *  of 42, measured.
 *
 *  Drawn as filled rectangles at whatever the paper is, so the same call is
 *  correct on a 203dpi roll and a 300dpi one.
 */
export function barcodePdf(text: string, below: string,
                           sticker: Sticker = DEFAULT_STICKER): Uint8Array {
  const W = sticker.wide * PT;
  const H = sticker.tall * PT;
  const modules = code128Width(text);
  if (!modules) throw new Error("There is nothing to encode in that barcode.");

  // The module width is what decides whether it scans. A hand scanner wants
  // about 0.25mm and will not read much under 0.19; a symbol wider than the
  // sticker is worse than a small one, so the paper caps it and the caller is
  // told when the number simply will not fit.
  const usable = (sticker.wide - PAD_X * 2) * PT;
  const module = usable / modules;
  if (module * (25.4 / 72) < 0.19) {
    throw new Error(
      `"${text}" needs a wider sticker to scan: at ${sticker.wide}mm its bars `
      + "come out under 0.19mm and most scanners will not read them.");
  }

  // Text under the bars, because a barcode that will not scan is still a script
  // number somebody can type, and the label is the only copy the patient has.
  const caption = below || text;
  const capSize = 6.5;
  const barsTop = PAD_Y * PT;
  const barsHigh = Math.max(H * 0.42, H - PAD_Y * 2 * PT - capSize * 2.4);
  const left = PAD_X * PT;

  const ops = code128Rects(text).map(({ x, width }) =>
    `${(left + x * module).toFixed(2)} ${(H - barsTop - barsHigh).toFixed(2)} `
    + `${(width * module).toFixed(2)} ${barsHigh.toFixed(2)} re f`);

  const capW = widthOf(caption, "plain", capSize);
  ops.push("BT /F1 " + capSize + " Tf "
    + `${((W - capW) / 2).toFixed(2)} `
    + `${(H - barsTop - barsHigh - capSize * 1.25).toFixed(2)} Td `
    + `(${pdfText(caption)}) Tj ET`);

  const content = ops.join("\n");
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${W.toFixed(2)} ${H.toFixed(2)}] `
      + "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
  ];

  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((body, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const at of offsets) pdf += `${String(at).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\n`
    + `startxref\n${xref}\n%%EOF\n`;

  const bytes = new Uint8Array(pdf.length);
  for (let i = 0; i < pdf.length; i += 1) bytes[i] = pdf.charCodeAt(i) & 0xff;
  return bytes;
}
