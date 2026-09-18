/** The keys a pharmacist already knows, and only the ones that are real.
 *
 *  The incumbent drives an entire script from function keys, and staff who have
 *  used it for years do not look at the keyboard. Matching those bindings is not
 *  a nicety — retraining muscle memory is the largest hidden cost of switching
 *  system, and it is paid by the pharmacy in slower service for weeks.
 *
 *  So where a key means something in Propharm it means the same thing here,
 *  and where we diverge the entry says so and says why.
 *
 *  This file used to be the wish rather than the build. It listed F2 as
 *  Ointment, F3 as marking a line cash, F7 for counter messages, F11 for claim
 *  later, Ctrl+R for a realtime response and eight Ctrl navigation keys, none
 *  of which any screen bound. That would be harmless documentation drift if
 *  nothing read it, but `tools/build_atlas.py` feeds this list to RX-Assistant,
 *  which then taught those keys to staff with total confidence. A key that does
 *  nothing, taught by the assistant, costs more than no assistant at all.
 *
 *  So the rule now: an entry belongs here only if a screen binds it. The
 *  dispensary's own table in `pages/Dispense.tsx` is the authority for the
 *  script keys, and `qa/keymap-is-real.mjs` fails the build when the two
 *  disagree.
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

/** The script screen — where a dispenser spends the day.
 *
 *  Must match the `hotkeys` table in `pages/Dispense.tsx` exactly.
 */
export const SCRIPT_KEYS: KeyBinding[] = [
  { combo: "F1", label: "Mix", incumbent: "Mix[F1]", group: "Capture" },
  {
    combo: "F2", label: "Find patient", incumbent: "Oint[F2]", group: "Capture",
    divergent: true,
    note: "The incumbent puts an ointment here. Naming the patient is the first "
        + "thing done on every script and the incumbent leaves it on the mouse, "
        + "so the key pressed most often is the one it is on.",
  },
  {
    combo: "F3", label: "Add medicine", incumbent: "NoClaim[F3]", group: "Capture",
    divergent: true,
    note: "Marking a line cash is a property of a line, and is set on the line. "
        + "This key adds the next one.",
  },
  {
    combo: "F4", label: "Diagnosis", incumbent: "Not Disp[F4]", group: "Capture",
    divergent: true,
    note: "Opens the line being worked on with the cursor in its diagnosis.",
  },
  { combo: "F5", label: "WayBill", incumbent: "WayBill[F5]", group: "Capture" },
  { combo: "F6", label: "Auth", incumbent: "Auth[F6]", group: "Safety" },
  { combo: "F8", label: "Repts", incumbent: "Repts[F8]", group: "Lists" },
  { combo: "F9", label: "Hist", incumbent: "Hist[F9]", group: "Lists" },
  {
    combo: "F12",
    label: "Finish",
    incumbent: "Finish[Enter/F12]",
    group: "Finish",
    divergent: true,
    note:
      "Same key, but this asks before committing. Finishing is irreversible once " +
      "the receipt is fiscalised. In Zimbabwe it can then only be reversed by a " +
      "credit note. Pressed again inside the dialog, it dispenses.",
  },
  { combo: "Escape", label: "Close, or clear the script", group: "Finish" },
];

/** Everywhere. Bound above the screens rather than inside one. */
export const NAV_KEYS: KeyBinding[] = [
  { combo: "Ctrl+K", label: "Ask RX-Assistant", group: "Global" },
];

/** Ours. Chosen on keys the incumbent leaves free, so nothing is displaced. */
export const RX5000_KEYS: KeyBinding[] = [
  { combo: "?", label: "Show this key map", group: "Global" },
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
