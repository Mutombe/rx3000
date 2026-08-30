/** What colour a figure earns, decided in one place.
 *
 *  Colour is the fastest thing on a screen and the easiest to get subtly
 *  wrong. Every call site choosing its own thresholds means a 79% that is
 *  amber on one page and green on the next, and a reader who learns to
 *  distrust the colour — at which point it is worse than none, because it is
 *  still competing for attention.
 *
 *  The one rule this file enforces: **red means somebody must do something.**
 *  Not "this number is low" — low is amber. Red is for money already lost, a
 *  drawer that does not balance, medicine that cannot go out. A screen where
 *  everything is red teaches people to ignore red.
 *
 *  `bad` was in use across two screens and had no style behind it at all, so
 *  the worst tier of every rate on the scorecard rendered with no colour —
 *  the one figure that mattered most was the only one without a signal. It is
 *  an alias for `danger` now rather than a fourth name for the same thing.
 */

export type Tone = "ok" | "warn" | "danger" | "muted";

/** A percentage against what it ought to be.
 *
 *  Within twenty points of the target is amber rather than red: a claims
 *  recovery of 62% against a target of 80 is a conversation, not an alarm,
 *  and colouring it the same as 5% would flatten the difference.
 */
export function rateTone(value: number | null | undefined,
                         good: number, span = 20): Tone {
  if (value === null || value === undefined) return "muted";
  const pct = value <= 1 ? value * 100 : value;
  if (pct >= good) return "ok";
  if (pct >= good - span) return "warn";
  return "danger";
}

/** How overdue a repeat is.
 *
 *  Green while it is not yet late, amber inside the window where a telephone
 *  call still works, red once the patient has almost certainly been served
 *  somewhere else. The thresholds are the server's — `grace_days` and
 *  `lapsed_after_days` come back with the figures — so a change there moves
 *  the colours with it rather than leaving the screen describing an older
 *  rule.
 */
export function overdueTone(daysOverdue: number, grace = 7, lapsed = 45): Tone {
  if (daysOverdue <= 0) return "ok";
  if (daysOverdue <= grace) return "warn";
  if (daysOverdue <= lapsed) return "danger";
  return "danger";
}

/** Money that should be nought.
 *
 *  A variance, an amount written off, a value that cannot be supplied. Green
 *  at zero and red at anything else, because "nearly balanced" is not a
 *  category a cash-up has.
 */
export function varianceTone(amount: number | null | undefined,
                             tolerance = 0.005): Tone {
  if (amount === null || amount === undefined) return "muted";
  return Math.abs(amount) <= tolerance ? "ok" : "danger";
}

/** A count of things that have gone wrong. Nought is green, any is amber,
 *  and past `many` it is red — one rejected claim is a task, thirty is a
 *  problem with the scheme. */
export function countTone(n: number | null | undefined, many = 10): Tone {
  if (n === null || n === undefined) return "muted";
  if (n === 0) return "ok";
  return n >= many ? "danger" : "warn";
}

/** Whether stock on hand covers what is being asked for. */
export function stockTone(onHand: number, wanted: number): Tone {
  if (onHand >= wanted) return "ok";
  return onHand > 0 ? "warn" : "danger";
}
