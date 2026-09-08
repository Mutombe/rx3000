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
import { render, type Line } from "./escpos";
import { readStored, writeStored } from "./storage";

const CHOSEN = "label_printer";
const WIDTH = "label_printer_width";

/** The kinds of thing this pharmacy prints, and what each one is called.
 *
 *  `label` keeps the original storage key, so a till that already chose a roll
 *  carries on using it with nothing to set up. The rest fall back to it, which
 *  means one printer still works for everything until somebody says otherwise.
 */
export type DocKind = "label" | "price" | "delivery" | "claim";

export const DOC_KINDS: { kind: DocKind; name: string; hint: string; paper: "roll" | "page" }[] = [
  { kind: "label", name: "Dispensing label", paper: "roll",
    hint: "The sticker that goes on the box." },
  { kind: "price", name: "Price label", paper: "roll",
    hint: "What something costs, for somebody deciding whether to buy it." },
  { kind: "delivery", name: "Delivery label", paper: "roll",
    hint: "Name, address and script number, for the driver." },
  { kind: "claim", name: "Claim copy", paper: "page",
    hint: "A4. The copy that goes in the file or to the funder." },
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
