/** Choosing many rows, and doing one thing to all of them.
 *
 *  Of twenty-one list screens in this system, one let you act on more than one
 *  row at a time. That is the gap that does not show in a demo and decides
 *  whether the software is used: a pharmacy assigning twelve deliveries to a
 *  driver one at a time does not assign them, it writes a list on paper. A
 *  pharmacy telephoning two hundred overdue repeats one row at a time
 *  telephones about nine of them.
 *
 *  The shape is deliberately small. A hook that holds which ids are ticked, and
 *  a bar that appears when any are — because a bulk action that lives in a menu
 *  is one nobody finds, and tick boxes with no visible action are decoration.
 *
 *  `keep` is the part worth explaining. When the list reloads — after a filter
 *  changes, or after the action itself — anything ticked that is no longer on
 *  screen is dropped. Without that, an action silently applies to rows the
 *  operator can no longer see, which is the worst possible behaviour for
 *  something irreversible.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

export function useSelection<T>(rows: T[], key: (row: T) => number) {
  const [chosen, setChosen] = useState<Set<number>>(new Set());

  const present = useMemo(() => new Set(rows.map(key)), [rows, key]);

  // Anything ticked that has left the list goes with it. An action must never
  // reach a row the operator cannot see.
  useEffect(() => {
    setChosen((current) => {
      const kept = new Set([...current].filter((id) => present.has(id)));
      return kept.size === current.size ? current : kept;
    });
  }, [present]);

  const toggle = useCallback((id: number) => {
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const all = useCallback(() => {
    setChosen((current) =>
      current.size === present.size ? new Set() : new Set(present));
  }, [present]);

  const clear = useCallback(() => setChosen(new Set()), []);

  return {
    chosen,
    ids: useMemo(() => [...chosen], [chosen]),
    count: chosen.size,
    has: useCallback((id: number) => chosen.has(id), [chosen]),
    toggle,
    all,
    clear,
    allChosen: present.size > 0 && chosen.size === present.size,
    /** The rows themselves, for an action that needs more than the id. */
    rows: useMemo(() => rows.filter((r) => chosen.has(key(r))),
                  [rows, chosen, key]),
  };
}
