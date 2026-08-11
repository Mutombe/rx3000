/** Client for the local device agent.
 *
 *  The agent runs on the till PC and owns the hardware a browser cannot reach:
 *  the ESC/POS receipt printer, the cash drawer and the card terminal. It is
 *  optional — when it is not running every call reports unavailable and the
 *  caller falls back to browser printing and manual card capture.
 */
import { Sale } from "./types";
import { money } from "./api";

const AGENT = "http://127.0.0.1:9110";

export interface AgentStatus {
  agent: string;
  version: string;
  printer: { mode: string; port: string | null; width: number; ready: boolean };
  drawer: { pin: number; ready: boolean; via: string | null };
  terminal: { driver: string; ready: boolean; terminal_id?: string; message?: string };
  mobile_money?: { driver: string; ready: boolean; timeout_seconds?: number; message?: string };
}

export interface TerminalResult {
  approved: boolean;
  auth_code?: string;
  reference?: string;
  last4?: string;
  scheme?: string;
  terminal_id?: string;
  batch?: string;
  message?: string;
}

async function call<T>(path: string, body?: unknown, timeoutMs = 5000): Promise<T> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const res = await fetch(AGENT + path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: abort.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok && res.status !== 402) {
      throw new Error((data as any).error || `Device agent returned ${res.status}`);
    }
    return data as T;
  } finally {
    clearTimeout(timer);
  }
}

/** Null when the agent is not running — every caller treats that as "no hardware". */
export async function probe(): Promise<AgentStatus | null> {
  try {
    return await call<AgentStatus>("/status", undefined, 1200);
  } catch {
    return null;
  }
}

/** A card terminal request blocks until the customer has tapped, so allow minutes. */
export function takePayment(amount: number, reference: string) {
  return call<TerminalResult>("/terminal/payment", { amount, reference }, 180000);
}

export function cancelPayment() {
  return call<{ cancelled: boolean; message?: string }>("/terminal/cancel", {});
}

export interface MobileInitiate {
  started: boolean;
  poll_ref?: string;
  reference?: string;
  message?: string;
}

export interface MobilePoll {
  state: "pending" | "paid" | "cancelled" | "failed";
  reference?: string;
  message?: string;
}

/** Push a mobile money request to the customer's handset. Returns immediately —
 *  the caller polls until it resolves. */
export function initiateMobile(amount: number, phone: string, method: string, reference: string) {
  return call<MobileInitiate>("/mobile/initiate", { amount, phone, method, reference }, 20000);
}

export function pollMobile(pollRef: string) {
  return call<MobilePoll>("/mobile/poll", { poll_ref: pollRef }, 15000);
}

/** Poll until the customer approves, cancels, or the request expires.
 *  `onTick` reports progress so the cashier sees something is happening. */
export async function awaitMobilePayment(
  pollRef: string,
  { timeoutMs = 180000, intervalMs = 2000, onTick }: {
    timeoutMs?: number; intervalMs?: number; onTick?: (seconds: number) => void;
  } = {},
): Promise<MobilePoll> {
  const started = Date.now();
  for (;;) {
    const elapsed = Date.now() - started;
    if (elapsed > timeoutMs) {
      return { state: "failed", message: "The customer did not approve in time" };
    }
    onTick?.(Math.round(elapsed / 1000));
    let result: MobilePoll;
    try {
      result = await pollMobile(pollRef);
    } catch {
      // A dropped poll is not a failed payment — keep trying until the timeout.
      result = { state: "pending" };
    }
    if (result.state !== "pending") return result;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export function kickDrawer() {
  return call<{ opened: boolean }>("/drawer/kick", {});
}

type Line = { text: string; align?: "left" | "centre" | "right"; bold?: boolean; double?: boolean; feed?: number };

/** Lay a sale out as ESC/POS lines. Mirrors the browser receipt so a till with
 *  hardware and one without produce the same document. */
export function receiptLines(sale: Sale, pharmacyName: string, regNo = "", width = 42): Line[] {
  const pair = (left: string, right: string): Line => {
    const gap = Math.max(1, width - left.length - right.length);
    return { text: left + " ".repeat(gap) + right };
  };
  const rule = (): Line => ({ text: "-".repeat(width) });

  const lines: Line[] = [
    { text: pharmacyName, align: "centre", bold: true, double: true },
  ];
  if (regNo) lines.push({ text: `Reg. ${regNo}`, align: "centre" });
  lines.push({ text: "Tax Invoice", align: "centre", feed: 1 });
  lines.push(pair("Invoice", sale.sale_number));
  lines.push(pair("Date", new Date(sale.created_at).toLocaleString("en-ZA")));
  if (sale.patient) pair("Patient", `${sale.patient.first_name} ${sale.patient.last_name}`);
  lines.push(rule());

  sale.items.forEach((i) => lines.push(pair(`${i.quantity} x ${i.description}`.slice(0, width - 12), money(i.line_total))));

  lines.push(rule());
  lines.push(pair("Subtotal (excl. VAT)", money(sale.subtotal)));
  lines.push(pair("VAT", money(sale.vat_amount)));
  lines.push({ ...pair("TOTAL", money(sale.total)), bold: true });
  lines.push(pair("Paid by", sale.payment_method.replace("_", " ")));

  if (sale.payment_method === "cash") {
    lines.push(pair("Tendered", money(sale.amount_tendered)));
    lines.push(pair("Change", money(sale.change_due)));
  }
  if (sale.card_auth_code) {
    lines.push(rule());
    lines.push(pair("Auth code", sale.card_auth_code));
    if (sale.card_last4) lines.push(pair("Card", `**** ${sale.card_last4}`));
    if (sale.terminal_id) lines.push(pair("Terminal", sale.terminal_id));
  }
  if (sale.loyalty_points_earned) lines.push(pair("Points earned", `${sale.loyalty_points_earned} pts`));

  lines.push({ text: "", feed: 1 });
  lines.push({ text: "Thank you for your business.", align: "centre" });
  return lines;
}

export function printReceiptOnAgent(sale: Sale, pharmacyName: string, regNo = "", width = 42) {
  return call<{ printed: boolean }>("/print", {
    lines: receiptLines(sale, pharmacyName, regNo, width),
    cut: true,
    open_drawer: sale.payment_method === "cash",
  }, 15000);
}
