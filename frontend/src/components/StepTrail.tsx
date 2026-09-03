import { CheckCircle, Circle, DotsThreeCircle } from "@phosphor-icons/react";

/** Where a step stands, and what it is still waiting for.
 *
 *  `needs` is the sentence a person reads to know what to do next, so it names
 *  the missing thing rather than the rule that is unmet: "Add at least one
 *  medicine", not "items.length must exceed zero".
 */
export type Step = {
  /** Displayed number. Passed in rather than derived, because the controlled
   *  route has a step the prescription route does not and both must number
   *  from one without a gap. */
  n: number;
  title: string;
  /** True once this step has everything it needs. */
  done: boolean;
  /** What is missing, when it is not done. Empty for an optional step. */
  needs?: string;
  /** `id` of the card this step lives in. Clicking scrolls there and puts the
   *  cursor in its first field. */
  anchor: string;
  /** The card's section colour, so the chip and the card it points at are
   *  recognisably one thing. That is what makes the strip readable without a
   *  legend: it is the same colours in the same order as the cards below. */
  tone?: "patient" | "items" | "check" | "go";
};

/** Scroll to a step's card and put the cursor in its first field.
 *
 *  Exported because the notice beside the dispense button uses it too. That
 *  notice names the missing condition, which on a screen this long is usually
 *  off the top of it, so it also has to be able to take somebody there, and
 *  it must land in the same place the trail would.
 *
 *  This is the only thing in the flow that moves focus, and it never does so
 *  on its own: a person clicked.
 */
export function goToStep(anchor: string) {
  const card = document.getElementById(anchor);
  if (!card) return;
  card.scrollIntoView({ behavior: "smooth", block: "start" });
  const field = card.querySelector<HTMLElement>(
    "input:not([type=hidden]):not([disabled]), textarea:not([disabled]), " +
    "select:not([disabled]), [role=combobox]",
  );
  field?.focus({ preventScroll: true });
}

/** The four cards of a dispense, as a trail across the top.
 *
 *  DOC'S COMPLAINT, AND WHY THIS IS THE ANSWER TO IT
 *
 *  The dispensing screen is one column of numbered cards, all visible, all
 *  editable. DOC called it blunt, and she is right: the numbers say there is an
 *  order but nothing says where you are in it, so a new dispenser reads four
 *  headings and a wall of fields and has to work out for themselves which parts
 *  are done, which are waiting on them, and which do not apply today.
 *
 *  Two other answers were on the table and both cost more than they pay.
 *
 *  Auto-advancing focus as fields fill would move the cursor while somebody is
 *  typing. Dispensing is not linear — a dispenser takes the script, often
 *  enters the medicines first and finds the patient after, corrects a quantity,
 *  goes back for the prescriber, and a cursor that jumps on its own is a
 *  keystroke landing in the wrong field. On a controlled-drug entry that is a
 *  quantity in the wrong box, in a register an inspector reads. Predictable Tab
 *  is worth more than saved Tab.
 *
 *  Putting each step behind a modal would hide the thing the screen exists to
 *  keep in view. The allergy badge, the scheme's standing, the repeats that are
 *  due and the basket are all on this page deliberately, so that they are in
 *  sight while the decision is made. A modal covers them with the field you are
 *  typing into — it makes the screen look simpler by making it know less.
 *
 *  So neither gates anything. The trail is a status display: it says where you
 *  are, what each step still wants, and lets you jump to any of them in any
 *  order. Nothing here prevents an edit, disables a field, or takes focus that
 *  was not asked for by a click.
 */
export default function StepTrail({ steps }: { steps: Step[] }) {
  // The step being worked: the first one not finished. Not a stored cursor —
  // a stored one goes stale the moment somebody edits a card behind it.
  const current = steps.findIndex((s) => !s.done);

  return (
    <ol className="trail" aria-label="Steps in this dispense">
      {steps.map((s, i) => {
        const state = s.done ? "done" : i === current ? "now" : "todo";
        return (
          <li key={s.anchor}
              className={`trail-step trail-${state}`
                + (s.tone ? ` trail-${s.tone}` : "")}>
            <button type="button" onClick={() => goToStep(s.anchor)}
                    aria-current={state === "now" ? "step" : undefined}>
              <span className="trail-mark" aria-hidden="true">
                {state === "done" ? <CheckCircle size={17} weight="fill" />
                  : state === "now" ? <DotsThreeCircle size={17} weight="fill" />
                    : <Circle size={17} />}
              </span>
              <span className="trail-text">
                <b>{s.n} · {s.title}</b>
                {/* The sentence only under the step being worked. On every
                    step at once it is four instructions competing, which is
                    the wall this replaces. */}
                {state === "now" && s.needs && (
                  <span className="trail-needs">{s.needs}</span>
                )}
                {state === "done" && (
                  <span className="trail-needs">Done</span>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
