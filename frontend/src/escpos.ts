/** Turning a label into the bytes a thermal printer understands.
 *
 *  A thermal printer does not render HTML. It takes a stream of text with
 *  control codes in it — ESC/POS — and prints as it reads. Sending those bytes
 *  straight to the spooler is what makes a label appear the instant a sale
 *  completes, with no print dialog in the way, which is the difference between
 *  a till and a web page.
 *
 *  This mirrors `device-agent/printing.py` deliberately, byte for byte. Two
 *  renderers of the same document that drift apart produce labels that differ
 *  depending on which path printed them, and the label is a legal record.
 */

export interface Line {
  text: string;
  align?: "left" | "centre" | "right";
  bold?: boolean;
  /** Double height and width. Used for the directions, which are read at
   *  arm's length by somebody who may not have their glasses on. */
  double?: boolean;
  /** Blank lines after this one. */
  feed?: number;
}

const ESC = 0x1b;
const GS = 0x1d;

const INIT = [ESC, 0x40];
const BOLD_ON = [ESC, 0x45, 0x01];
const BOLD_OFF = [ESC, 0x45, 0x00];
const ALIGN_LEFT = [ESC, 0x61, 0x00];
const ALIGN_CENTRE = [ESC, 0x61, 0x01];
const DOUBLE_ON = [GS, 0x21, 0x11];
const DOUBLE_OFF = [GS, 0x21, 0x00];
const CUT = [GS, 0x56, 0x42, 0x00];

/** Code page 437, which is what these printers default to.
 *
 *  Anything outside it becomes '?' rather than throwing: a patient named
 *  Müller must still get a label, and a printer that refuses the job because
 *  of one character is worse than one that prints "Muller".
 */
function encode(text: string): number[] {
  const out: number[] = [];
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 63;
    if (code < 0x80) {
      out.push(code);
      continue;
    }
    // The handful that actually turn up on a Zimbabwean counter.
    const swap: Record<string, number> = {
      "é": 130, "è": 138, "ü": 129, "ö": 148, "ä": 132, "ç": 135,
      "£": 156, "°": 248, "·": 250, "–": 45, "—": 45, "’": 39, "‘": 39,
      "“": 34, "”": 34, "…": 46,
    };
    out.push(swap[ch] ?? 63);
  }
  return out;
}

/** Lay lines out as ESC/POS. `width` is characters per line for this roll. */
export function render(lines: Line[], width = 32, cut = true): Uint8Array {
  const out: number[] = [...INIT];
  for (const line of lines) {
    const align = line.align ?? "left";
    let text = line.text ?? "";
    if (align === "centre") {
      out.push(...ALIGN_CENTRE);
    } else {
      out.push(...ALIGN_LEFT);
      // Right alignment by padding rather than by the printer's own mode: a
      // double-height line is also double-width, so the printer's idea of the
      // right margin and ours disagree exactly when it matters.
      if (align === "right") {
        const room = line.double ? Math.floor(width / 2) : width;
        text = text.padStart(room);
      }
    }
    if (line.double) out.push(...DOUBLE_ON);
    if (line.bold) out.push(...BOLD_ON);
    out.push(...encode(text), 0x0a);
    if (line.bold) out.push(...BOLD_OFF);
    if (line.double) out.push(...DOUBLE_OFF);
    for (let i = 0; i < (line.feed ?? 0); i += 1) out.push(0x0a);
  }
  if (cut) out.push(0x0a, 0x0a, 0x0a, ...CUT);
  return Uint8Array.from(out);
}

/** What the roll will actually say, for showing on screen.
 *
 *  The preview has to be the same document as the print or it is a lie, and
 *  this one cannot be shown as HTML — so it is shown as the text the printer
 *  receives, wrapped at the roll's own width.
 */
export function asText(lines: Line[], width = 32): string {
  return lines.map((line) => {
    const room = line.double ? Math.floor(width / 2) : width;
    const text = (line.text ?? "").slice(0, room);
    if (line.align === "centre") {
      const pad = Math.max(0, Math.floor((room - text.length) / 2));
      return " ".repeat(pad) + text;
    }
    if (line.align === "right") return text.padStart(room);
    return text;
  }).join("\n");
}
