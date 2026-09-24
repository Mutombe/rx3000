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
import { labelZpl, zplBytes } from "./labelZpl";
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
    hint: "A second sticker carrying only the barcode. The dispensing label "
        + "already has one along its bottom, so this is for a pack that needs "
        + "the number somewhere else." },
];

function keyFor(kind: DocKind): string {
  return kind === "label" ? CHOSEN : `printer_${kind}`;
}

/** Nothing is routed here, said so somebody knows which setting to open.
 *
 *  One sentence, naming the document in the words the settings page uses and
 *  the place to fix it. These were four different sentences, two of which said
 *  only "this document", which is no help to somebody who has just pressed
 *  Dispense and does not know a claim copy from a price ticket.
 */
function noPrinter(kind: DocKind): Error {
  const said = DOC_KINDS.find((d) => d.kind === kind)?.name.toLowerCase()
    ?? "document";
  return new Error(
    `No printer is set for the ${said} on this till. `
    + `Choose one under This till, Printers.`);
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

/** A printer as Windows describes it. The driver is what says which language
 *  it speaks, so it is carried rather than thrown away. */
export interface PrinterInfo { name: string; driver: string; port: string }

/** What Windows last said about the printers on this machine.
 *
 *  Held because printing has to decide which language to speak and cannot
 *  wait on an enumeration in the middle of a dispense. Filled the first time
 *  the printer list is asked for, which every screen that prints does on the
 *  way in.
 */
let known: PrinterInfo[] = [];

export function describe(printer: string): PrinterInfo {
  return known.find((p) => p.name === printer)
    ?? { name: printer, driver: "", port: "" };
}

/** Every printer Windows can see on this machine, with its driver. */
export async function listPrinterInfo(): Promise<PrinterInfo[]> {
  if (!canPrintDirect()) return [];
  try {
    const found = await invoke<PrinterInfo[]>("list_printers");
    // An older shell answered with plain names. Accept both rather than lose
    // the printer list to a version mismatch.
    known = found.map((p) => typeof p === "string"
      ? { name: p as unknown as string, driver: "", port: "" } : p);
    return known;
  } catch {
    // A shell that cannot enumerate is not a failure worth a message: the
    // application simply offers the print dialog instead.
    return [];
  }
}

/** Every printer Windows can see on this machine. Empty in a browser. */
export async function listPrinters(): Promise<string[]> {
  return (await listPrinterInfo()).map((p) => p.name);
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
 *  "zpl"   the label is drawn at the printer's own resolution and sent as a
 *          ZPL graphic, straight to the spooler in RAW mode. This is what a
 *          Zebra speaks. Nothing has to be installed on the till for it to
 *          work, because the driver is bypassed entirely.
 *
 *  "page"  the label is a small PDF handed to the printer's own Windows driver.
 *          Right in principle for any printer Windows can see — but only
 *          reachable where something on the machine has registered the
 *          "printto" verb for PDFs. Edge does not. See `print_page` and
 *          `labelZpl.ts`, which is why "auto" no longer chooses this blind.
 *
 *  "raw"   the label is ESC/POS bytes written straight to the spooler. Faster
 *          and what a receipt-style thermal head wants, and complete nonsense
 *          to a printer that speaks ZPL — it prints blank or prints rubbish,
 *          and never says which.
 *
 *  "auto"  work it out from what Windows says the printer is, which is the
 *          default and what a pharmacy should never have to think about. A
 *          label printer announces itself: this one is called
 *          "ZDesigner ZD421-203dpi ZPL", which names the language and the
 *          resolution. Asking a pharmacist to pick a printer language is
 *          asking a question the machine already knows the answer to.
 */
export type LabelMode = "auto" | "zpl" | "page" | "raw";

export function labelMode(): LabelMode {
  const stored = readStored(MODE);
  return stored === "raw" || stored === "page" || stored === "zpl" ? stored : "auto";
}

export function setLabelMode(mode: LabelMode) {
  writeStored(MODE, mode);
}

/** What a printer's own name and driver say about it.
 *
 *  Windows names a label printer after its driver, and a label driver names
 *  its language and usually its resolution: "ZDesigner ZD421-203dpi ZPL",
 *  "ZDesigner GK420d (EPL)", "TSC TTP-244". So the answer is already on the
 *  machine and nobody needs to be asked for it.
 *
 *  Deliberately narrow. Claiming a printer speaks ZPL when it does not means
 *  sending it bytes it will print as rubbish, so anything not recognised is
 *  left alone and takes the route it took before.
 */
export type Language = "zpl" | "unknown";

export function languageOf(printer: string, driver = ""): Language {
  const said = `${printer} ${driver}`.toLowerCase();
  // EPL is the older Zebra language and is NOT ZPL: a printer in EPL mode
  // ignores ZPL completely. Named first so "ZDesigner GK420d (EPL)" is not
  // caught by the Zebra rule underneath it.
  if (/\bepl\b|\beltron\b/.test(said)) return "unknown";
  if (/\bzpl\b|zdesigner|zebra/.test(said)) return "zpl";
  return "unknown";
}

/** The printer's resolution in dots per inch.
 *
 *  Read off the name where it says so, which a label driver almost always
 *  does, and 203 otherwise because that is what the overwhelming majority of
 *  label printers in a pharmacy are. Getting this wrong does not produce a
 *  wrong label; it produces one printed at the wrong size, which is visible
 *  immediately and fixable in the printer settings.
 */
export function dpiOf(printer: string, driver = ""): number {
  const found = /(\d{3})\s*dpi/i.exec(`${printer} ${driver}`);
  const dpi = found ? Number(found[1]) : 0;
  return dpi === 203 || dpi === 300 || dpi === 600 ? dpi : 203;
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
  if (!printer) throw noPrinter(kind);
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
  if (!printer) throw noPrinter(kind);
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
/** How a label will actually be sent, with "auto" worked out.
 *
 *  Exported because a preview has to show what the printer is about to be
 *  given. ZPL and a PDF are both the designed sticker; ESC/POS is lines of
 *  text and looks nothing like it.
 */
export function resolvedLabelMode(printer = printerFor("label")): "zpl" | "page" | "raw" {
  const chosen = labelMode();
  if (chosen !== "auto") return chosen;
  return languageOf(printer, describe(printer).driver) === "zpl" ? "zpl" : "page";
}

export async function printLabelsDirect(labels: Label[], copies = 1): Promise<number> {
  const printer = printerFor("label");
  if (!printer) throw noPrinter("label");
  // Ask Windows what this printer is, if nothing has yet.
  //
  // The dispensary prints without ever opening the printer list, so on a fresh
  // launch the driver is unknown and the language would be guessed from the
  // printer's NAME alone. That is usually the driver's name and usually right,
  // and "usually" means a pharmacy that renamed its roll to "Labels" silently
  // takes the route that cannot deliver. One enumeration per run, before the
  // first sticker, costs nothing anybody can feel.
  if (known.length === 0) await listPrinterInfo();
  const info = describe(printer);
  const mode = resolvedLabelMode(printer);

  if (mode === "raw") {
    let done = 0;
    for (const label of labels) done += await printLines(labelLines(label, printerWidth()));
    return done * Math.max(1, copies);
  }

  const paper = sticker();
  let done = 0;
  if (mode === "zpl") {
    const dpi = dpiOf(printer, info.driver);
    for (let i = 0; i < Math.max(1, copies); i += 1) {
      for (const label of labels) {
        await invoke<number>("print_raw", {
          printer, data: Array.from(zplBytes(labelZpl(label, paper, dpi))),
        });
        done += 1;
      }
    }
    return done;
  }

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
  if (!printerFor("barcode")) throw noPrinter("barcode");
  await printPage(barcodePdf(text, below, sticker()), "barcode");
}

export async function printReceiptDirect(sale: Sale, pharmacyName: string,
                                         regNo = ""): Promise<void> {
  if (!printerFor("receipt")) throw noPrinter("receipt");
  await printLines(receiptLines(sale, pharmacyName, regNo, printerWidth()), 1, "receipt");
}
