/** Nothing here, and why.
 *
 *  There was no component for this. There was a CSS class, copied by hand into
 *  a hundred and four places, and thirty-six tables with nothing at all — they
 *  simply ended, leaving a header row above a void. A table that stops without
 *  a word is indistinguishable from one that failed to load, and the person
 *  looking at it cannot tell whether the shop has no deliveries today or
 *  whether the screen is broken.
 *
 *  AN EMPTY STATE IS AN ANSWER, NOT A CAPTION.
 *
 *  "No records" tells somebody nothing they had not already worked out from
 *  the blank space. What they need is which of the two empties this is:
 *
 *    NOTHING YET      the shop has never had one of these. Say what the thing
 *                     is for, and offer the way to make one.
 *    NOTHING MATCHED  there are plenty, and the filters have excluded them
 *                     all. Say that, and offer to clear them — otherwise
 *                     somebody concludes the data is gone.
 *
 *  Those are different sentences and the caller knows which it is, so `title`
 *  is required and there is no default. A default here would be "Nothing to
 *  show" on ninety screens, which is the state this replaces.
 */
import { ReactNode } from "react";

export default function Empty({
  title, children, action, className = "",
}: {
  /** The answer, in one short line. */
  title: ReactNode;
  /** Why it is empty, or what to do about it. */
  children?: ReactNode;
  /** The way out: make the first one, or clear the filters. */
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`empty ${className}`.trim()}>
      <b>{title}</b>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}

/** The same, inside a table that has a header row.
 *
 *  A table's empty state belongs INSIDE the table, spanning every column, so
 *  the header stays above it and the reader can still see what the columns
 *  would have been. Put beneath the table instead, it reads as a note about
 *  the page rather than as the table's own answer.
 */
export function EmptyRow({
  cols, title, children, action,
}: {
  /** How many columns to span. Getting this wrong leaves the cell short and
   *  the row ragged, which is why it is required rather than guessed. */
  cols: number;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <tr className="empty-row">
      <td colSpan={cols}>
        <Empty title={title} action={action}>{children}</Empty>
      </td>
    </tr>
  );
}
