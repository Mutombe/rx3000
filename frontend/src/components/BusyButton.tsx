/** A button that shows it is working.
 *
 *  A control that fires a request and then sits there looking exactly as it did
 *  before is the single most common way software feels broken. On a counter it
 *  is worse than untidy: the operator presses it again, and again, and now three
 *  identical requests are in flight while a customer waits.
 *
 *  So the busy state is not something each call site remembers to add. Hand this
 *  an async `onClick` and it holds the promise: while it is unresolved the button
 *  is disabled, its icon spins, and its label can change. Nothing else to wire
 *  up, and nothing to forget.
 *
 *  Deliberately not a spinner replacing the label. A control that swaps its text
 *  for a spinner changes width, which moves the buttons beside it, and the row
 *  jumps under a hand that is already reaching for the next one. The spinner is
 *  added beside the label instead.
 *
 *  It used to spin only the icon a caller had passed, which meant every button
 *  without one — "Take payment", "Authorise", "Post", most of the actions in
 *  every modal in the product — showed nothing at all but a slightly dimmer
 *  label. That is the exact failure this component was written to prevent, so
 *  a busy button now always has something turning.
 */
import { ReactNode, useCallback, useRef, useState } from "react";
import { CircleNotch, type Icon } from "@phosphor-icons/react";

export default function BusyButton({
  onClick, icon: Glyph, iconSize = 14, children, busyLabel, className = "", ...rest
}: {
  /** May return a promise. While it is pending the button is busy. */
  onClick: () => unknown | Promise<unknown>;
  /** Spun while the action runs. */
  icon?: Icon;
  iconSize?: number;
  children?: ReactNode;
  /** Shown in place of the label while working, when there is a label. */
  busyLabel?: string;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick">) {
  const [busy, setBusy] = useState(false);
  /* Unmounting mid-request is ordinary here: half these buttons reload a list,
     and the reload can navigate away. Setting state afterwards would be a
     warning in development and a leak in a long shift. */
  const alive = useRef(true);

  const run = useCallback(async () => {
    if (busy) return;                    // a second press is not a second request
    setBusy(true);
    try {
      await onClick();
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [busy, onClick]);

  return (
    <button
      {...rest}
      type={rest.type ?? "button"}
      className={`${className}${busy ? " is-busy" : ""}`.trim()}
      // Not `disabled`: a disabled button loses its tooltip and its focus ring,
      // and a keyboard user tabbing through the row would find it simply gone.
      // aria-busy says what is happening, and the guard above says no twice.
      aria-busy={busy}
      onClick={run}
      ref={(el) => { if (el) alive.current = true; }}
    >
      {/* Whatever the caller gave us, or a spinner in its place. Never
          nothing: a control that fires a request and looks unchanged is how an
          operator comes to press it three times. */}
      {busy
        ? <CircleNotch size={iconSize} weight="bold" className="spin" />
        : Glyph && <Glyph size={iconSize} weight="bold" />}
      {busy && busyLabel ? busyLabel : children}
    </button>
  );
}
