/** Printing through the desktop shell, with no dialog.
 *
 *  The shell can hand bytes to the Windows spooler; a browser cannot, because
 *  `window.print()` always asks. So a till running the desktop app prints its
 *  labels the instant a sale completes, and a browser tab falls back to the
 *  dialog: the same document either way.
 *
 *  Which printer is a per-machine choice, not a per-pharmacy one: the label
 *  roll is plugged into this till and called whatever Windows calls it here.
 *  It is kept in local storage for that reason, and nowhere near the database.
 */
import { labelLines, receiptLines } from "./deviceAgent";
import { render, type Line } from "./escpos";
import { barcodePdf, labelPdf } from "./labelPdf";
import { readStored, writeStored } from "./storage";
import type { Label, Sale } from "./types";

const CHOSEN = "label_printer";
const WIDTH = "label_printer_width";
const STICKER = "label_sticker_mm";
const MODE = "label_printer_mode";

/** The kinds of thing this pharmacy prints, and what each one is called.
 *
 *  `label` keeps the original storage key, so a till that already chose a roll
 *  carries on using it with nothing to set up. The rest fall back to it, which
 *  means one printer still works for everything until somebody says otherwise.
 */
export type DocKind = "label" | "receipt" | "price" | "delivery" | "claim" | "barcode";

export const DOC_KINDS: { kind: DocKind; name: string; hint: string; paper: "roll" | "page" }[] = [
  { kind: "label", name: "Dispensing label", paper: "roll",
    hint: "The sticker that goes on the box." },
  { kind: "receipt", name: "Receipt", paper: "roll",
    hint: "The tax invoice the customer takes away, when the money is taken here." },
  { kind: "price", name: "Price label", paper: "roll",
    hint: "What something costs, for somebody deciding whether to buy it." },
  { kind: "delivery", name: "Delivery label", paper: "roll",
    hint: "Name, address and script number, for the driver." },
  { kind: "claim", name: "Claim copy", paper: "page",
    hint: "A4. The copy that goes in the file or to the funder." },
  { kind: "barcode", name: "Script barcode", paper: "roll",
    hint: "The Rx number as a barcode. MCAZ expects a dispensed script to carry one." },
];

function keyFor(kind: DocKind): string {
  return kind === "label" ? CHOSEN : `printer_${kind}`;
}

/** Which printer this kind goes to. Falls back to the label roll.
 *
 *  The fallback is what makes this safe to ship: a till that has only ever
 *  chosen one printer keeps printing everything on it, exactly as before, and
 *  nothing has to be configured for the upgrade to be invisible.
 */
export function printerFor(kind: DocKind): string {
  return readStored(keyFor(kind)) ?? readStored(CHOSEN) ?? "";
}

/** Point one kind of document at a printer. "" means "follow the label roll". */
export function routeTo(kind: DocKind, printer: string) {
  writeStored(keyFor(kind), printer);
}

/** What has been set explicitly, as against inherited from the label roll. */
export function explicitRoute(kind: DocKind): string {
  return readStored(keyFor(kind)) ?? "";
}

interface Bridge {
  core?: { invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T> };
  invoke?: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;
}

function bridge(): Bridge | null {
  const shell = (globalThis as unknown as { __TAURI__?: Bridge }).__TAURI__;
  return shell ?? null;
}

/** True when this is the desktop app rather than a browser tab. */
export function canPrintDirect(): boolean {
  const shell = bridge();
  return Boolean(shell?.core?.invoke || shell?.invoke);
}

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const shell = bridge();
  const call = shell?.core?.invoke ?? shell?.invoke;
  if (!call) throw new Error("This is not the desktop application.");
  return call<T>(cmd, args);
}

/** Every printer Windows can see on this machine. Empty in a browser. */
export async function listPrinters(): Promise<string[]> {
  if (!canPrintDirect()) return [];
  try {
    return await invoke<string[]>("list_printers");
  } catch {
    // A shell that cannot enumerate is not a failure worth a message: the
    // application simply offers the print dialog instead.
    return [];
  }
}

/** Which printer this till sends labels to, if somebody has chosen one. */
export function chosenPrinter(): string {
  return readStored(CHOSEN) ?? "";
}

export function choosePrinter(name: string, width = 32) {
  writeStored(CHOSEN, name);
  writeStored(WIDTH, String(width));
}

export function printerWidth(): number {
  const stored = Number(readStored(WIDTH));
  return Number.isFinite(stored) && stored > 0 ? stored : 32;
}

/** HOW THIS TILL'S LABEL PRINTER IS DRIVEN.
 *
 *  Two ways, and which is right depends entirely on the machine:
 *
 *  "page"  the label is a small PDF handed to the printer's own Windows driver.
 *          Works on anything Windows can see, whatever language the printer
 *          speaks, because the driver does the talking. A Zebra on its
 *          ZDesigner driver, a TSC, a Brother, an A4 laser in a pinch.
 *
 *  "raw"   the label is ESC/POS bytes written straight to the spooler. Faster
 *          and what a receipt-style thermal head wants, and complete nonsense
 *          to a printer that speaks ZPL — it prints blank or prints rubbish,
 *          and never says which.
 *
 *  The default is "page", because it is the one that is right about a printer
 *  nobody has told us anything about. A pharmacy with an ESC/POS roll can say
 *  so once and get the faster path.
 */
export type LabelMode = "page" | "raw";

export function labelMode(): LabelMode {
  return readStored(MODE) === "raw" ? "raw" : "page";
}

export function setLabelMode(mode: LabelMode) {
  writeStored(MODE, mode);
}

/** The sticker on the roll, in millimetres. The label is drawn to this, so it
 *  is the one measurement that has to match the physical paper. */
export function sticker(): { wide: number; tall: number } {
  const [w, h] = String(readStored(STICKER) ?? "").split("x").map(Number);
  return Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0
    ? { wide: w, tall: h }
    : { wide: 58, tall: 42 };
}

export function setSticker(wide: number, tall: number) {
  writeStored(STICKER, `${wide}x${tall}`);
}

/** Send a rendered page document to a printer by name, with no dialog.
 *
 *  Separate from `printLines` because it is a different thing entirely. That
 *  sends RAW bytes — ESC/POS — which is what a thermal roll speaks and what an
 *  A4 laser cannot render at all: it would print the escape codes as text, or
 *  eject a hundred blank pages, both of which have happened to somebody.
 *
 *  A page document is handed over as a file and Windows chooses the driver.
 */
export async function printPage(bytes: Uint8Array | ArrayBuffer,
                                kind: DocKind = "claim"): Promise<void> {
  const printer = printerFor(kind);
  if (!printer) throw new Error("No printer has been chosen for this document.");
  const data = Array.from(
    bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes));
  await invoke<number>("print_page", { printer, data });
}

/** True when this kind will go straight to a printer with no dialog. */
export function goesStraightToPrinter(kind: DocKind = "label"): boolean {
  return canPrintDirect() && Boolean(printerFor(kind));
}

/** True when labels will go straight to a roll with no dialog. */
export function labelsGoStraightToRoll(): boolean {
  return canPrintDirect() && Boolean(chosenPrinter());
}

/** Print one label. Throws with the printer's own complaint if it refuses.
 *
 *  `kind` chooses the printer. It defaults to the dispensing label so every
 *  existing caller keeps its behaviour without being edited.
 */
export async function printLines(lines: Line[], copies = 1,
                                 kind: DocKind = "label"): Promise<number> {
  const printer = printerFor(kind);
  if (!printer) throw new Error("No label printer has been chosen on this till.");
  const width = printerWidth();
  const payload = Array.from(render(lines, width));
  let done = 0;
  for (let i = 0; i < Math.max(1, copies); i += 1) {
    await invoke<number>("print_raw", { printer, data: payload });
    done += 1;
  }
  return done;
}

/** Print labels the way this till is set up to print them, with no dialog.
 *
 *  One place that decides, so the dispensary, the till and the reprint screen
 *  cannot disagree about how a label reaches the paper. Returns how many were
 *  printed; throws with the printer's own complaint if it refuses, which is
 *  what the callers fall back to the print dialog on.
 */
export async function printLabelsDirect(labels: Label[], copies = 1): Promise<number> {
  const printer = printerFor("label");
  if (!printer) throw new Error("No label printer has been chosen on this till.");
  if (labelMode() === "raw") {
    let done = 0;
    for (const label of labels) done += await printLines(labelLines(label, printerWidth()));
    return done * Math.max(1, copies);
  }
  const paper = sticker();
  let done = 0;
  for (let i = 0; i < Math.max(1, copies); i += 1) {
    for (const label of labels) {
      await printPage(labelPdf(label, paper), "label");
      done += 1;
    }
  }
  return done;
}

/** Print a receipt on the receipt printer, with no dialog.
 *
 *  A receipt is ESC/POS on a roll, always — that is what a receipt printer is,
 *  and unlike a label printer there is no ambiguity about the language. The
 *  routing has allowed a separate receipt printer since `DOC_KINDS` was
 *  written; nothing used it, so a till with a receipt roll chosen in its
 *  settings still opened the browser's dialog to print one.
 */
/** Print a script's barcode on whichever printer that kind goes to.
 *
 *  Its own kind rather than the dispensing label's, because a pharmacy that
 *  buys a dedicated barcode roll wants it there, and one that has not simply
 *  falls back to the label roll like everything else does. Always a page
 *  through the driver: a barcode is bars at exact widths, and that is the one
 *  thing a text-mode ESC/POS stream cannot express.
 */
export async function printBarcodeDirect(text: string, below = ""): Promise<void> {
  if (!printerFor("barcode")) {
    throw new Error("No printer has been chosen for script barcodes.");
  }
  await printPage(barcodePdf(text, below, sticker()), "barcode");
}

export async function printReceiptDirect(sale: Sale, pharmacyName: string,
                                         regNo = ""): Promise<void> {
  if (!printerFor("receipt")) {
    throw new Error("No receipt printer has been chosen on this till.");
  }
  await printLines(receiptLines(sale, pharmacyName, regNo, printerWidth()), 1, "receipt");
}
