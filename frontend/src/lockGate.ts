/** The gate between a locked till and anything that changes data.
 *
 *  The lock used to be a wall: a modal with no way out, which is wrong for a
 *  counter. Somebody wants to look up a price for the person in front of them
 *  without stopping to type a PIN, and a lock that forbids reading gets resented
 *  and then disabled.
 *
 *  So the lock became a gate. Dismiss it and the till is still locked, but you
 *  can read: browse patients, check stock, look at a report. The moment anything
 *  would *change* — a dispensing, a sale, an edit, a delete — the gate stops the
 *  request and asks who is at the keyboard. Nothing is lost while it asks: the
 *  request is held, not failed, and it continues the moment the PIN lands.
 *
 *  Reads are deliberately not gated. A locked screen that hides the catalogue
 *  protects nothing the shelf does not already show, and it would make the lock
 *  something staff work around rather than with.
 */
/** What a held request is told when the gate finally answers.
 *  `unlocked` — the PIN landed, carry on. `abandoned` — the operator pushed the
 *  prompt aside; do nothing, and say nothing. */
export type GateOutcome = "unlocked" | "abandoned";

type Waiter = { resolve: (outcome: GateOutcome) => void };

let locked = false;
let dismissed = false;
const waiters: Waiter[] = [];
const listeners = new Set<() => void>();

function announce() {
  for (const l of listeners) l();
}

export const lockGate = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },

  /** Locked, whether or not the modal is currently on screen. */
  isLocked: () => locked,
  /** Locked, but the operator has pushed the prompt aside to read something. */
  isDismissed: () => dismissed,
  /** The prompt should be visible: locked and not pushed aside. */
  isPrompting: () => locked && !dismissed,

  lock() {
    if (locked) return;
    locked = true;
    dismissed = false;
    announce();
  },

  /** Push the prompt aside. The till stays locked; reading continues. */
  dismiss() {
    if (!locked) return;
    dismissed = true;
    announce();
  },

  /** Bring the prompt back, because somebody tried to do something. */
  prompt() {
    if (!locked) return;
    dismissed = false;
    announce();
  },

  unlock() {
    locked = false;
    dismissed = false;
    // Everything that was held now proceeds, in the order it arrived.
    while (waiters.length) waiters.shift()!.resolve("unlocked");
    announce();
  },

  /** Give up on the held requests, so a cancel does not leave promises pending
   *  for the rest of the session.
   *
   *  Resolved as *abandoned* rather than rejected. Rejecting looked right — the
   *  request did not happen — but nothing was catching it, so pressing "Not now"
   *  logged an unhandled failure every time, and on a page with a held save it
   *  produced an error the operator had done nothing to cause. The caller is
   *  told the request was dropped and returns quietly instead. */
  abandon() {
    while (waiters.length) waiters.shift()!.resolve("abandoned");
    announce();
  },

  /** Called by the API layer before anything that writes. Resolves at once when
   *  the till is open, and otherwise waits for the PIN. */
  ensureUnlocked(): Promise<GateOutcome> {
    if (!locked) return Promise.resolve("unlocked");
    lockGate.prompt();
    return new Promise<GateOutcome>((resolve) => waiters.push({ resolve }));
  },
};

/* Reachable from the console in development only.
   Not a convenience: a dynamic `import()` of this module from outside the app
   can resolve to a second instance, because Vite serves hot-reloaded modules
   under a timestamped URL. A test that locks that copy watches nothing happen
   and concludes the lock is broken. This hands out the instance the app is
   actually using. */
if (import.meta.env.DEV) {
  (window as unknown as { __lockGate?: typeof lockGate }).__lockGate = lockGate;
}
