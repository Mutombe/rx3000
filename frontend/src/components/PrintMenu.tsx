/** The things a dispensary prints when a script is finished.
 *
 *  Modelled on the menu the previous system put on the same keystroke, because
 *  that menu is a good description of what a dispensary actually needs: a
 *  label, a claim copy, a price quote, a delivery label, a reprint. Its letters
 *  are kept — L, C, P, V, R — so a dispenser's hands work on the first morning.
 *
 *  WHY THIS IS NOT A MODAL
 *
 *  The obvious build is a dialog after Dispense: tick what to print, press OK.
 *  It is obvious and it is wrong. That dialog appears on every script, thirty
 *  times a morning, and its answer is the same almost every time — so it stops
 *  being read, gets dismissed by reflex, and the one script that needed a
 *  delivery label goes out without one.
 *
 *  A dialog is for a decision. Printing a label after dispensing is not a
 *  decision, it is the rest of the action.
 *
 *  So the primary button does the whole common case — dispense AND label — in
 *  one press, and nothing opens. The menu holds what is genuinely occasional,
 *  which is where a menu belongs.
 *
 *  WHICH PRINTER IS NOT ASKED EITHER
 *
 *  Also configuration, also not a question. The roll is plugged into this till
 *  and Windows knows what it is called; that fact has not changed since it was
 *  plugged in, and asking about it at the counter is asking the dispenser to
 *  answer for the hardware in front of a patient. It is set once on This Till
 *  and every print after that is silent. See `shellPrinter.printerFor`.
 */
import { useEffect, useRef, useState } from "react";
import { CaretDown } from "@phosphor-icons/react";

export interface PrintAction {
  /** The single letter the previous system used. Pressed on its own. */
  key: string;
  label: string;
  /** Said under the label where the outcome is not obvious from the name. */
  hint?: string;
  run: () => void | Promise<void>;
  /** Greyed, with the reason, rather than hidden — see the note below. */
  unavailable?: string;
  /** A rule above this item in the menu. */
  separated?: boolean;
}

export default function PrintMenu({
  primaryLabel, onPrimary, actions, busy, disabled, primaryTitle,
}: {
  primaryLabel: string;
  onPrimary: () => void | Promise<void>;
  actions: PrintAction[];
  busy?: boolean;
  disabled?: boolean;
  primaryTitle?: string;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement | null>(null);

  // Escape and a click outside, the two ways a person expects a menu to close.
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); return; }
      // The accelerators, live only while the menu is open. Deliberately not
      // global: a dispensary types into every field on this screen, and a
      // single-letter shortcut that fires while somebody is typing a patient's
      // name is a printer that starts on its own.
      const hit = actions.find(
        (a) => a.key.toLowerCase() === e.key.toLowerCase() && !a.unavailable);
      if (hit) {
        e.preventDefault();
        setOpen(false);
        void hit.run();
      }
    };
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", key);
    document.addEventListener("mousedown", away);
    return () => {
      document.removeEventListener("keydown", key);
      document.removeEventListener("mousedown", away);
    };
  }, [open, actions]);

  return (
    <div className="printmenu" ref={box}>
      <button
        className="btn primary printmenu-main"
        onClick={() => void onPrimary()}
        disabled={busy || disabled}
        title={primaryTitle}
      >
        {busy ? "Working…" : primaryLabel}
      </button>
      <button
        className="btn primary printmenu-caret"
        aria-label="Other things to print"
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        <CaretDown size={13} weight="bold" />
      </button>

      {open && (
        <div className="printmenu-list" role="menu">
          {actions.map((a) => (
            <button
              key={a.key}
              role="menuitem"
              className={a.separated ? "sep" : undefined}
              /* Shown greyed with the reason rather than hidden. Somebody who
                 used the old system knows Delivery Label is on this menu, and a
                 gap where it should be reads as a missing feature; "no address
                 on this patient" reads as a thing to go and fix. */
              disabled={Boolean(a.unavailable)}
              title={a.unavailable}
              onClick={() => { setOpen(false); void a.run(); }}
            >
              <kbd>{a.key.toUpperCase()}</kbd>
              <span>
                {a.label}
                {(a.hint || a.unavailable) && (
                  <small>{a.unavailable ?? a.hint}</small>
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
