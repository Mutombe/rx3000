/** A row acted on in place, saying so, while the screen stays usable.
 *
 *  THE SHAPE THIS FILLS.
 *
 *  Three mechanisms already exist for work that must not block:
 *  `useOptimisticList` for a list whose rows are created, edited and deleted,
 *  `closeThenSave` for a dialog that writes, and `useDoing` for a job that
 *  outlives the screen that started it.
 *
 *  None of them fits the commonest thing in this product: a button ON a row
 *  that changes that row where it sits. Settle this sale. Dispatch this
 *  waybill. Approve this authorisation. Hand this one over. The row is not
 *  created or removed, no dialog is involved, and the work is over in a
 *  second — so every screen hand-rolled it, and hand-rolling it means most of
 *  them did nothing at all and the row sat there looking untouched.
 *
 *  A row that looks exactly as it did before the button was pressed is a row
 *  somebody presses again. On a till that means taking the money twice.
 *
 *  WHAT IT GUARANTEES.
 *
 *  **The row says what is happening, in words.** Not a spinner. Five working
 *  rows with five spinners in them is a list nobody can read, which is the
 *  same argument the optimistic rows in the stylesheet already make.
 *
 *  **More than one at a time.** The ids are a set, not a flag. The whole point
 *  of not waiting is that somebody can act on three rows in a row while the
 *  first is still going; one flag makes the second press look like it did
 *  nothing.
 *
 *  **It always ends.** Success or failure, the row stops claiming to work.
 *  Nothing is retried on its own: a till that quietly re-sends a payment is
 *  worse than one that says it did not work.
 */
import { useCallback, useState } from "react";
import { errorText } from "../api";
import { useToast } from "../components/Toast";

export interface RowWork<Id> {
  /** True while this row is being worked on. */
  busy: (id: Id) => boolean;
  /** How many rows are in flight, for a screen that wants to say so. */
  count: number;
  /** The class for the row, so it dims and carries its travelling bar. */
  rowClass: (id: Id) => string;
  /** What to say is happening to this row, or "" when nothing is. */
  saidFor: (id: Id) => string;
  /** Do the work. The row says `said` until it finishes either way. */
  run: <T>(id: Id, said: string, commit: () => Promise<T>, then?: {
    /** Shown when it lands. Omit where the row leaving the list says it. */
    ok?: string | ((result: T) => string);
    /** What was not done, in words, because the row is still there to retry. */
    failed?: string;
    /** Runs only on success. */
    after?: (result: T) => void;
  }) => Promise<T | undefined>;
}

export function useRowWork<Id extends string | number = number>(): RowWork<Id> {
  const [working, setWorking] = useState<Map<Id, string>>(new Map());
  const toast = useToast();

  const mark = useCallback((id: Id, said: string | null) => {
    setWorking((all) => {
      const next = new Map(all);
      if (said === null) next.delete(id);
      else next.set(id, said);
      return next;
    });
  }, []);

  const run = useCallback(async <T,>(
    id: Id, said: string, commit: () => Promise<T>, then?: {
      ok?: string | ((result: T) => string);
      failed?: string;
      after?: (result: T) => void;
    },
  ): Promise<T | undefined> => {
    // Pressing the same row twice while it is working is the accident this
    // exists to prevent, and a screen that forgets to hide its button should
    // not be able to cause it.
    if (working.has(id)) return undefined;
    mark(id, said);
    try {
      const result = await commit();
      if (then?.ok) {
        toast.ok(typeof then.ok === "function" ? then.ok(result) : then.ok);
      }
      then?.after?.(result);
      return result;
    } catch (e) {
      // The row is still there and still in its old state, so the message says
      // what was not done rather than apologising in the abstract.
      toast.error(errorText(e, then?.failed ?? "That did not go through."));
      return undefined;
    } finally {
      mark(id, null);
    }
  }, [mark, toast, working]);

  return {
    busy: (id) => working.has(id),
    count: working.size,
    rowClass: (id) => (working.has(id) ? "row-saving" : ""),
    saidFor: (id) => working.get(id) ?? "",
    run,
  };
}

export default useRowWork;
