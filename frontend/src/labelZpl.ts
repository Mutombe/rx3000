/** The dispensing label as ZPL, for a printer that speaks it.
 *
 *  WHY THIS EXISTS WHEN `labelPdf.ts` ALREADY DRAWS THE LABEL.
 *
 *  That file argues, at length and correctly, that a PDF handed to the
 *  printer's own Windows driver beats writing a renderer per vendor. Every
 *  premise in that argument is true except one: that we can reach the driver.
 *
 *  We cannot. Printing a file to a NAMED printer from a desktop shell means
 *  ShellExecute with the "printto" verb, and "printto" has to be registered by
 *  whatever application owns the file type. On Windows 11 the PDF handler is
 *  Edge, and Edge does not register it. Measured on a real machine: the call
 *  returns 31, SE_ERR_NOASSOC. Acrobat and Foxit do register it, which is why
 *  this worked wherever somebody happened to have one installed, and why the
 *  failure looked random rather than total.
 *
 *  So the label was laid out correctly, written correctly, and then handed to
 *  a door with nothing behind it. The dispensary fell back to the browser's
 *  print dialog, and inside the desktop shell that fallback is a pop-up the
 *  WebView blocks — which is the message a dispenser actually saw.
 *
 *  A Zebra needs none of that. ZPL goes to the spooler as a RAW job, the
 *  driver is bypassed, and the printer executes the bytes. No file type, no
 *  handler, no dialog, nothing to install on the till.
 *
 *  WHY A PICTURE AND NOT ZPL TEXT COMMANDS.
 *
 *  ZPL can set type. Doing so means expressing this label a third time, in a
 *  third layout engine, with its own fonts and its own wrapping — and the
 *  moment it wraps differently from `labelPdf`, the preview on screen stops
 *  being what comes off the roll. That is the exact failure `labelPdf.ts` and
 *  `print.ts` both have comments about.
 *
 *  Instead the label is drawn once, from `labelPlacement` and `labelBarcode` —
 *  the same numbers the PDF and the on-screen preview draw from — onto a canvas
 *  at the printer's own resolution, and sent as a one-bit image. The sticker
 *  that comes off the roll is the sticker on the screen, to the dot, because it
 *  is the same drawing.
 */
import { cssFontFor, labelBarcode, labelPlacement, type Sticker } from "./labelPdf";
import type { Label } from "./types";

/** A point is 1/72 inch; a dot is 1/dpi of one. */
const PT_PER_INCH = 72;

/** Anything darker than this becomes a black dot.
 *
 *  The canvas antialiases edges, and a thermal head has no grey. Held near the
 *  middle: lower and the strokes of 5.5pt type thin out to nothing, higher and
 *  the antialiasing around them fattens into a smear. */
const INK = 160;

export interface Raster {
  width: number;
  height: number;
  /** One bit per dot, row-major, MSB first, 1 meaning black. */
  rows: Uint8Array[];
}

/** Draw the label at a printer's resolution and reduce it to one bit a dot.
 *
 *  Throws where there is no canvas, which is a build script or a test rather
 *  than a till. Callers fall back to another route rather than lose the label.
 */
export function rasterise(l: Label, sticker: Sticker, dpi: number): Raster {
  const perMm = dpi / 25.4;
  const perPt = dpi / PT_PER_INCH;
  const width = Math.max(8, Math.round(sticker.wide * perMm));
  const height = Math.max(8, Math.round(sticker.tall * perMm));

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("This machine cannot draw a label to send to the roll.");

  // White paper, black ink. The thermal head burns what is black.
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#000";
  ctx.textBaseline = "alphabetic";

  for (const line of labelPlacement(l, sticker)) {
    // `labelPlacement` gives points from the top left, and y is the baseline,
    // which is what "alphabetic" means here.
    ctx.font = cssFontFor(line.font, line.size * perPt, "px");
    ctx.fillText(line.text, line.x * perPt, line.y * perPt);
  }

  const bars = labelBarcode(l, sticker);
  if (bars) {
    for (const r of bars.rects) {
      // Rounded outward so a bar never disappears between two dots. A barcode
      // with a module missing scans as a different number or not at all, and
      // the second is much the better failure.
      const x = Math.floor(r.x * perPt);
      const w = Math.max(1, Math.round(r.w * perPt));
      ctx.fillRect(x, Math.floor(r.y * perPt), w, Math.max(1, Math.round(r.h * perPt)));
    }
  }

  const pixels = ctx.getImageData(0, 0, width, height).data;
  const rowBytes = Math.ceil(width / 8);
  const rows: Uint8Array[] = [];
  for (let y = 0; y < height; y += 1) {
    const row = new Uint8Array(rowBytes);
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4;
      // Luminance, weighted the way an eye sees it. The label is black on
      // white, so this is really just "is there ink here".
      const lum = 0.299 * pixels[i] + 0.587 * pixels[i + 1] + 0.114 * pixels[i + 2];
      if (lum < INK) row[x >> 3] |= 0x80 >> (x & 7);
    }
    rows.push(row);
  }
  return { width, height, rows };
}

const HEX = "0123456789ABCDEF";

function hexOf(row: Uint8Array): string {
  let out = "";
  for (const byte of row) out += HEX[byte >> 4] + HEX[byte & 15];
  return out;
}

/** The raster as a ZPL graphic field.
 *
 *  Pure, so it can be checked without a printer or a browser.
 *
 *  Two of ZPL's own shorthands are used, because a dispensing label is mostly
 *  white paper and sending it as literal hex is about forty kilobytes of
 *  zeroes per sticker:
 *
 *    ","  fill the rest of this row with white
 *    ":"  this row is the same as the one above it
 *
 *  Both are core ZPL rather than anything clever, and they take a typical
 *  label under five kilobytes, which matters on a USB roll printing four
 *  stickers for one script while somebody waits.
 */
export function graphicField(raster: Raster): string {
  const rowBytes = raster.rows[0]?.length ?? 0;
  const total = rowBytes * raster.rows.length;
  let data = "";
  let previous: string | null = null;
  for (const row of raster.rows) {
    const hex = hexOf(row);
    if (hex === previous) {
      data += ":";
      continue;
    }
    previous = hex;
    // Trailing white is the rest of the row, and "," says so in one character.
    const trimmed = hex.replace(/0+$/, "");
    data += trimmed.length === hex.length ? hex : `${trimmed},`;
  }
  return `^GFA,${total},${total},${rowBytes},${data}`;
}

/** One label as a complete ZPL job, ready for the spooler in RAW mode. */
export function labelZpl(l: Label, sticker: Sticker, dpi: number): string {
  const raster = rasterise(l, sticker, dpi);
  return [
    "^XA",
    // Home the origin. A roll that was left shifted by a previous job prints
    // this one shifted too, and nobody connects the two.
    "^LH0,0",
    `^PW${raster.width}`,
    `^LL${raster.height}`,
    "^FO0,0",
    graphicField(raster),
    "^FS",
    "^XZ",
  ].join("\n");
}

/** ZPL is text, and the spooler takes bytes. */
export function zplBytes(zpl: string): Uint8Array {
  return new TextEncoder().encode(zpl);
}
