/** What was being captured when somebody walked away from the dispensary.
 *
 *  A pharmacist leaves a half-typed script constantly, and not because they
 *  have finished with it: to look up stock, to read a patient's history, to
 *  answer the telephone at the till. Until now the screen unmounted and took
 *  the capture with it, so coming back meant typing it again.
 *
 *  Two things could fix that and only one of them should:
 *
 *    a prompt on the way out — "save, discard, cancel" — which is a toll gate
 *    on the most-used exit in the building. It asks a question whose answer is
 *    almost always "I am coming straight back", and it asks it every time.
 *
 *    keeping it, which asks nothing. The screen is as they left it when they
 *    return, and if they did not mean to come back they clear it the way they
 *    already clear a script.
 *
 *  So: kept, not prompted. `Save for later` still exists beside it and is the
 *  different thing it always was — a draft on the server, on the worklist,
 *  visible to the rest of the shop. This is only the walk-away net, and it is
 *  deliberately the weaker of the two: this tab, this user, this shift.
 *
 *  WHAT IS NOT KEPT: the compliance ticks and the checking initials. Those are
 *  attestations — somebody stating they saw an identity document, sighted an
 *  original script, verified a prescriber. Restoring a tick would put words in
 *  a pharmacist's mouth about a check they may never have done, on the screen
 *  whose whole purpose is to record that they did. The typing comes back; the
 *  statements are made again, by a person.
 *
 *  `sessionStorage`, so it dies with the tab and never crosses a till that two
 *  people share. Stamped with the user, so a handover at the same tab does not
 *  hand over a script; and with a time, so yesterday's abandoned capture is not
 *  waiting in the morning.
 */

const KEY = "rx5000_script_draft";
/** A shift. Long enough for lunch and a fire drill, short enough that nobody
 *  returns to a script whose patient has since gone home. */
const KEEP_MS = 8 * 60 * 60 * 1000;
const VERSION = 1;

export interface ScriptDraft<Item> {
  v: number;
  savedAt: number;
  /** Who was signed in. A draft is never shown to anybody else. */
  userId: number | null;
  patient: unknown | null;
  doctorId: number | "";
  /** Which lane the draft was started in.
   *
   *  Kept optional so a draft written before the dispensary tabs were removed
   *  still parses. It is no longer read: what the screen becomes is worked out
   *  from the medicines in the basket, so there is nothing for a restored lane
   *  to disagree with.
   */
  route?: string;
  quoting: boolean;
  items: Item[];
}

/** What was left here, if it is still this person's and still this shift. */
export function readScriptDraft<Item>(userId: number | null): ScriptDraft<Item> | null {
  let raw: string | null = null;
  try {
    raw = sessionStorage.getItem(KEY);
  } catch {
    return null;                       // private mode; nothing was ever written
  }
  if (!raw) return null;
  try {
    const d = JSON.parse(raw) as ScriptDraft<Item>;
    if (d?.v !== VERSION) return null;
    if (d.userId !== userId) return null;
    if (!Array.isArray(d.items) || d.items.length === 0) return null;
    if (!d.savedAt || Date.now() - d.savedAt > KEEP_MS) { clearScriptDraft(); return null; }
    return d;
  } catch {
    // Half-written or from an older shape. It is a convenience, not a record:
    // a draft that cannot be read is dropped rather than reported.
    clearScriptDraft();
    return null;
  }
}

/** Keep what is on screen. An empty script clears it rather than storing a
 *  nothing, so finishing or clearing a script leaves no ghost to restore. */
export function writeScriptDraft<Item>(
  draft: Omit<ScriptDraft<Item>, "v" | "savedAt">,
): void {
  try {
    if (!draft.items.length) { sessionStorage.removeItem(KEY); return; }
    sessionStorage.setItem(KEY, JSON.stringify({ ...draft, v: VERSION, savedAt: Date.now() }));
  } catch {
    /* private mode, or the quota. Losing the net is not worth an error. */
  }
}

export function clearScriptDraft(): void {
  try { sessionStorage.removeItem(KEY); } catch { /* private mode */ }
}
