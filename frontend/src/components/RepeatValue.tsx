/** What a repeat is worth, wherever a repeat is named.
 *
 *  The repeat book is the most valuable thing a pharmacy owns and the only
 *  part of its revenue it can see coming. Every screen that listed repeats
 *  showed the position, "REPEAT 2/5", and none of them showed the money, so
 *  a rail with two hundred names on it could not be worked in the order that
 *  pays. On a short-staffed morning that order is the whole question.
 *
 *  One component, used by the queue, the call sheet, the chronic panel, the
 *  repeats tables and the patient record, so the figure means the same thing
 *  and looks the same everywhere. Six hand-rolled versions would have drifted
 *  into six different definitions of "worth" inside a month, which is worse
 *  than not showing it: two screens disagreeing about money is how people stop
 *  believing either.
 *
 *  Two numbers, and the distinction is the point. **Now** is what this
 *  collection is worth. **To come** is what the rest of the script is worth if
 *  the patient keeps returning, and therefore what walks out of the door for
 *  good if they go somewhere else. A pharmacy losing 10% of its repeats needs
 *  the second figure to know what that sentence cost.
 */
import { money } from "../api";
import { nRepeat, nRepeatPhrase } from "../terms";

export default function RepeatValue({
  value, remaining, used, allowed, size = "row", title,
}: {
  /** What this fill is worth. */
  value?: number | null;
  /** What the unfilled repeats behind it are worth. */
  remaining?: number | null;
  used?: number | null;
  allowed?: number | null;
  /** "row" inside a table, "chip" on a card, "hero" on a detail page. */
  size?: "row" | "chip" | "hero";
  title?: string;
}) {
  const now = value ?? 0;
  const later = remaining ?? 0;
  // Nothing to say rather than a confident 0.00. A line with no price on the
  // product is not a line worth nothing, it is a line nobody has priced, and
  // printing 0.00 states the first while meaning the second.
  if (!now && !later) {
    return <span className="rv-none" title="No price on this product yet">—</span>;
  }

  // "3-Repeat" — the dispensary's own name for a script with three
  // collections still to come, and the number is the point of it. The bare
  // `2/5` said the same thing in a notation you have to be taught.
  const left = allowed ? Math.max(0, allowed - (used ?? 0)) : 0;
  const position = allowed ? (nRepeat(left) || `${used ?? 0}/${allowed}`) : null;

  return (
    <span className={`rv rv-${size}`}
          title={title ?? ((allowed ? nRepeatPhrase(left) + " · " : "") + (later
            ? `${money(now)} this collection · ${money(later)} still to come on this script`
            : `${money(now)} this collection`))}>
      {position && <span className="rv-pos">{position}</span>}
      <span className="rv-now">{money(now)}</span>
      {/* The second figure is the one that answers "what did losing them
          cost", so it is present but quieter — a queue is read for the first
          number and audited on the second. */}
      {later > 0 && size !== "chip" && (
        <span className="rv-later">+{money(later)}</span>
      )}
    </span>
  );
}
