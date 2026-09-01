/** The bar that appears when rows are ticked.
 *
 *  Fixed to the bottom of the screen rather than above the table, because the
 *  row somebody ticks last is as likely to be at the bottom of a long list as
 *  the top, and an action bar that has scrolled off is an action nobody takes.
 *
 *  It says the count and what will happen to it, in that order, because "12
 *  deliveries" is what the operator is checking before they press anything. A
 *  bulk action is the one place where pressing the wrong thing is expensive by
 *  definition: it is the same mistake, multiplied.
 */
import type { ReactNode } from "react";
import { X } from "@phosphor-icons/react";

export default function BulkBar({
  count, noun, onClear, children,
}: {
  count: number;
  /** What is selected — "delivery", "repeat", "line". Pluralised here. */
  noun: string;
  onClear: () => void;
  /** The actions. Buttons, in the order somebody would reach for them. */
  children: ReactNode;
}) {
  if (!count) return null;
  return (
    <div className="bulk-bar" role="region" aria-label="Selected rows">
      <span className="bulk-count">
        <b>{count.toLocaleString()}</b> {noun}{count === 1 ? "" : "s"} selected
      </span>
      <div className="bulk-actions">{children}</div>
      <button className="btn ghost sm" onClick={onClear} title="Clear selection">
        <X size={13} weight="bold" />
      </button>
    </div>
  );
}

/** The header tick that takes the whole page, and the per-row one. */
export function SelectAll(
  { checked, onChange }: { checked: boolean; onChange: () => void },
) {
  return (
    <th className="bulk-tick">
      <input type="checkbox" checked={checked} onChange={onChange}
             aria-label="Select every row on this page" />
    </th>
  );
}

export function SelectRow(
  { checked, onChange }: { checked: boolean; onChange: () => void },
) {
  return (
    <td className="bulk-tick"
        // The tick must not also open the row. Two destinations in one cell,
        // and the one somebody meant is almost never the navigation.
        onClick={(e) => e.stopPropagation()}>
      <input type="checkbox" checked={checked} onChange={onChange}
             aria-label="Select this row" />
    </td>
  );
}
