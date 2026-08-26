/** The keys a pharmacist already knows.
 *
 *  The incumbent drives an entire script from function keys, and staff who have
 *  used it for years do not look at the keyboard. Matching those bindings is not
 *  a nicety — retraining muscle memory is the largest hidden cost of switching
 *  system, and it is paid by the pharmacy in slower service for weeks.
 *
 *  So the bindings below are copied from Propharm rather than chosen. Where we
 *  add something it has no incumbent equivalent, and it goes on a key the
 *  incumbent leaves free. Where a key means something there, it means the same
 *  thing here, even when we would have picked differently.
 *
 *  One deliberate exception, and it is a safety one: F12 finishes a script in
 *  the incumbent. Finishing is irreversible once the receipt is fiscalised, so
 *  it is kept on F12 — muscle memory would fire it anyway — but the screen must
 *  confirm rather than commit silently. Matching a key is not the same as
 *  matching a behaviour, and where the two conflict the safer behaviour wins.
 */

export interface KeyBinding {
  combo: string;
  label: string;
  /** What the incumbent calls it, where it has an equivalent. */
  incumbent?: string;
  group: string;
  /** True where we deliberately behave differently from the incumbent. */
  divergent?: boolean;
  note?: string;
}

/** The script screen — where a dispenser spends the day. */
export const SCRIPT_KEYS: KeyBinding[] = [
  { combo: "F1", label: "Mixture", incumbent: "Mix[F1]", group: "Script" },
  { combo: "F2", label: "Ointment", incumbent: "Oint[F2]", group: "Script" },
  { combo: "F3", label: "Mark line as cash", incumbent: "NoClaim[F3]", group: "Line" },
  { combo: "F4", label: "Mark line not dispensed", incumbent: "Not Disp[F4]", group: "Line" },
  { combo: "F5", label: "Waybill", incumbent: "WayBill[F5]", group: "Script" },
  { combo: "F6", label: "Authorisation", incumbent: "Auth[F6]", group: "Claim" },
  { combo: "F8", label: "Repeats", incumbent: "Repts[F8]", group: "Script" },
  { combo: "F9", label: "Patient history", incumbent: "Hist[F9]", group: "Patient" },
  { combo: "F11", label: "Claim later", incumbent: "Claim Later[F11]", group: "Claim" },
  {
    combo: "F12",
    label: "Finish script",
    incumbent: "Finish[Enter/F12]",
    group: "Script",
    divergent: true,
    note:
      "Same key, but this asks before committing. Finishing is irreversible once " +
      "the receipt is fiscalised. In Zimbabwe it can then only be reversed by a " +
      "credit note.",
  },
  { combo: "Ctrl+R", label: "Realtime response", incumbent: "RT Resp[Ctrl+R]", group: "Claim" },
];

/** Navigation, from the incumbent's Dispensing menu. */
export const NAV_KEYS: KeyBinding[] = [
  { combo: "Ctrl+N", label: "New script", incumbent: "New Script", group: "Dispensing" },
  { combo: "Ctrl+O", label: "Over-the-counter script", incumbent: "Over The Counter Script", group: "Dispensing" },
  { combo: "Ctrl+B", label: "Alter script", incumbent: "Alter Script", group: "Dispensing" },
  { combo: "Ctrl+Q", label: "Quick pricing", incumbent: "Quick Pricing", group: "Dispensing" },
  { combo: "Ctrl+P", label: "Reprint script", incumbent: "Reprint Script", group: "Dispensing" },
  { combo: "Ctrl+L", label: "Reprint labels", incumbent: "Reprint Labels", group: "Dispensing" },
  { combo: "Ctrl+T", label: "To follows", incumbent: "To Follows", group: "Dispensing" },
  { combo: "Ctrl+U", label: "Unfinished scripts", incumbent: "Unfinished Scripts", group: "Dispensing" },
];

/** Ours. Chosen on keys the incumbent leaves free, so nothing is displaced. */
export const RX5000_KEYS: KeyBinding[] = [
  { combo: "F7", label: "Counter messages for this patient", group: "Patient" },
  { combo: "Ctrl+K", label: "Search anything", group: "Global" },
  { combo: "?", label: "Show this key map", group: "Global" },
  { combo: "Escape", label: "Close / cancel", group: "Global" },
];

export const ALL_KEYS: KeyBinding[] = [...NAV_KEYS, ...SCRIPT_KEYS, ...RX5000_KEYS];

/** Guards against two features silently claiming one key. */
export function conflicts(bindings: KeyBinding[] = ALL_KEYS): string[] {
  const seen = new Map<string, string>();
  const clashes: string[] = [];
  for (const b of bindings) {
    const previous = seen.get(b.combo);
    if (previous) clashes.push(`${b.combo}: "${previous}" and "${b.label}"`);
    else seen.set(b.combo, b.label);
  }
  return clashes;
}

export function byGroup(bindings: KeyBinding[] = ALL_KEYS): Record<string, KeyBinding[]> {
  return bindings.reduce<Record<string, KeyBinding[]>>((acc, b) => {
    (acc[b.group] ||= []).push(b);
    return acc;
  }, {});
}

/** Every place we behave differently from the incumbent, and why. */
export function divergences(): KeyBinding[] {
  return ALL_KEYS.filter((b) => b.divergent);
}
