/** A table row that is itself a link, without eating the controls inside it.
 *
 *  Two rules from the navigation standard, and they fight each other unless
 *  handled deliberately:
 *
 *  1. The *whole row* navigates, so the hit target is forgiving — not a tiny
 *     chevron somebody has to aim at.
 *  2. The buttons inside the row still work. A click on "Write off" must not
 *     also navigate to the detail page, so in-row controls stop the click from
 *     bubbling.
 *
 *  `<RowActions>` is the wrapper that enforces rule 2. Putting controls in a
 *  bare `<td>` inside a `<RowLink>` is the bug this component exists to prevent,
 *  so actions have their own component rather than relying on everyone
 *  remembering to call stopPropagation.
 *
 *  Hovering prefetches, so the click feels free. `prefetch` is given the URL
 *  the row leads to; the caller decides what "warm this up" means — usually a
 *  GET whose response the detail page will find already cached.
 */
import { MouseEvent, ReactNode, useRef } from "react";
import { useNavigate } from "react-router-dom";

interface Props {
  to: string;
  children: ReactNode;
  className?: string;
  /** Called once on first hover. Keep it cheap and idempotent. */
  prefetch?: (to: string) => void;
}

export default function RowLink({ to, children, className = "", prefetch }: Props) {
  const navigate = useNavigate();
  const warmed = useRef(false);

  function go(e: MouseEvent<HTMLTableRowElement>) {
    // Let the browser do what the user asked for: a middle-click or Ctrl-click
    // opens a new tab, and hijacking that is the fastest way to make a table
    // feel like it is fighting you.
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) {
      return;
    }
    // A link inside the row wins. Without this, clicking a product name in a
    // row that navigates to the patient would take you to the patient — the
    // row silently swallowing a more specific destination. Anchors and buttons
    // are their own hit targets even when the row is one too.
    const target = e.target as HTMLElement | null;
    if (target?.closest("a, button, input, select, textarea, label")) return;
    navigate(to);
  }

  function warm() {
    if (warmed.current || !prefetch) return;
    warmed.current = true;
    prefetch(to);
  }

  return (
    <tr
      className={`row-link ${className}`.trim()}
      onClick={go}
      onMouseEnter={warm}
      onFocus={warm}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") navigate(to);
      }}
    >
      {children}
    </tr>
  );
}

/** Wrap in-row controls so acting on one does not also navigate.
 *
 *  Also stops keyboard activation bubbling, or pressing Enter on a focused
 *  button would fire the button *and* the row.
 */
export function RowActions({ children }: { children: ReactNode }) {
  return (
    <td
      className="actions"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {children}
    </td>
  );
}
