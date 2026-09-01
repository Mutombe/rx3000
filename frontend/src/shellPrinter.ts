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

/** True when labels will go straight to a roll with no dialog. */
export function labelsGoStraightToRoll(): boolean {
  return canPrintDirect() && Boolean(chosenPrinter());
}

/** Print one label. Throws with the printer's own complaint if it refuses. */
export async function printLines(lines: Line[], copies = 1): Promise<number> {
  const printer = chosenPrinter();
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
