/** A list that shows what you did before the server has agreed to it.
 *
 *  The pattern this implements, and why each part of it is there:
 *
 *  **The dialog closes at once.** A form that sits on "Saving…" while a counter
 *  queue builds up is the software making somebody wait for its own
 *  bookkeeping. The row appears immediately, drawn in a quieter state, and
 *  settles when the server confirms.
 *
 *  **A snapshot is taken before anything changes.** Every optimistic action
 *  records what the list looked like, so a failure restores exactly that rather
 *  than re-fetching and hoping. On a bad connection re-fetching is precisely
 *  when you cannot.
 *
 *  **A late reload cannot overwrite a fresh edit.** Every mutation bumps a
 *  generation counter; a `load` that started before it resolves into nothing.
 *  Without this, a refresh fired a moment before you pressed Delete lands a
 *  moment after and puts the row back.
 *
 *  **A pending row is not actionable.** `isPending` is exported so a screen can
 *  keep a placeholder out of bulk selection and hide its row actions. Acting on
 *  a record that does not have an id yet is how a delete goes to the wrong one.
 *
 *  What it deliberately does not do: retry. A failed write is shown, undone,
 *  and left to the person, because a till that quietly re-sends payments is
 *  worse than one that says it did not work.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { useToast } from "../components/Toast";

/** Where a row is in its life. `settled` rows are ordinary server rows. */
export type RowState = "settled" | "creating" | "saving" | "removing";

/** The id given to a row that does not have a real one yet. Negative so it can
 *  never collide with a server id, and distinctive so it is obvious in a log. */
let tempSeq = -1;
const nextTempId = () => tempSeq--;

export interface OptimisticList<T> {
  /** Server rows with the optimistic overlay applied, newest placeholder first. */
  items: T[];
  /** True until the first load resolves. Use it to choose a skeleton. */
  loading: boolean;
  /** Set when the last load failed, so the screen can say so in place. */
  error: string;
  /** Re-read from the server. Safe to call at any time. */
  reload: () => Promise<void>;
  /** How to draw this row. */
  stateOf: (item: T) => RowState;
  /** Whether this row is still in flight, so it can be kept out of actions. */
  isPending: (item: T) => boolean;
  /** Show `draft` at once, then run `commit` and replace it with what comes back. */
  create: (draft: T, commit: () => Promise<T | void>, said?: string) => Promise<boolean>;
  /** Apply `patch` to one row at once, then run `commit`. */
  update: (id: Id, patch: Partial<T>, commit: () => Promise<T | void>, said?: string) => Promise<boolean>;
  /** Take the row away at once, then run `commit`. */
  remove: (id: Id, commit: () => Promise<unknown>, said?: string) => Promise<boolean>;
  /** For a screen that needs to drop a row in without a server call. */
  setItems: React.Dispatch<React.SetStateAction<T[]>>;
}

type Id = number | string;

export function useOptimisticList<T extends object>({
  load, key, enabled = true,
}: {
  /** Fetch the whole list. */
  load: () => Promise<T[]>;
  /** This row's identity. */
  key: (item: T) => Id;
  /** Skip loading entirely — for a tab that has not been opened. */
  enabled?: boolean;
}): OptimisticList<T> {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  /** id -> what is happening to it. */
  const [pending, setPending] = useState<Map<Id, RowState>>(new Map());
  const toast = useToast();

  /* Bumped by every mutation. A `load` that began before the current value
     resolves into nothing, so a reload already in the air when somebody
     presses Delete cannot put the row back a moment later. */
  const generation = useRef(0);
  /* Set true on every mount, not only at creation. A cleanup that only ever
     sets it false is a one-way switch: React's development double-invoke
     mounts, unmounts and mounts again, so the flag was left false for the rest
     of the component's life and every state update after it was silently
     dropped. The list stayed empty and a saved row never settled. */
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  /* Held in a ref as well as in state: the mutations below need to read the
     list at the moment they run, and closing over `items` would give them
     whatever it was when the callback was made. */
  const latest = useRef<T[]>(items);
  latest.current = items;

  const keyRef = useRef(key);
  keyRef.current = key;
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(async () => {
    const mine = generation.current;
    try {
      const rows = await loadRef.current();
      // Someone changed something while this was in flight. Their change is
      // newer than this answer, so this answer is thrown away.
      if (!alive.current || mine !== generation.current) return;
      setItems(rows);
      setError("");
    } catch (e) {
      if (!alive.current || mine !== generation.current) return;
      setError(errorText(e, "That list could not be loaded."));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) { setLoading(false); return; }
    reload();
  }, [enabled, reload]);

  const mark = useCallback((id: Id, state: RowState | null) => {
    setPending((prev) => {
      const next = new Map(prev);
      if (state) next.set(id, state);
      else next.delete(id);
      return next;
    });
  }, []);

  const create = useCallback(async (
    draft: T, commit: () => Promise<T | void>, said?: string,
  ) => {
    const snapshot = latest.current;
    const tempId = nextTempId();
    const placeholder = { ...draft, id: tempId } as T;
    generation.current += 1;
    // Newest first: what you just did is the thing you are looking for.
    setItems([placeholder, ...snapshot]);
    mark(tempId, "creating");
    try {
      const saved = await commit();
      if (!alive.current) return true;
      // Merged over the placeholder, never substituted for it. A create
      // endpoint commonly answers with the record it wrote rather than the row
      // the list renders — {id, name, code} where the table also wants a count
      // and a value, and replacing outright left those undefined, which is a
      // crash the moment the row is drawn. The reload below fills in whatever
      // the server computed for itself.
      setItems((rows) => rows.map((r) =>
        keyRef.current(r) === tempId ? ({ ...r, ...(saved ?? {}) } as T) : r));
      mark(tempId, null);
      if (said) toast.ok(said);
      // Read back afterwards for anything the server worked out for itself —
      // a code, a running balance, a posted reference.
      generation.current += 1;
      reload();
      return true;
    } catch (e) {
      if (!alive.current) return false;
      setItems(snapshot);
      mark(tempId, null);
      toast.error(errorText(e, "That could not be saved."));
      return false;
    }
  }, [mark, reload, toast]);

  const update = useCallback(async (
    id: Id, patch: Partial<T>, commit: () => Promise<T | void>, said?: string,
  ) => {
    const snapshot = latest.current;
    generation.current += 1;
    setItems((rows) => rows.map((r) =>
      keyRef.current(r) === id ? { ...r, ...patch } : r));
    mark(id, "saving");
    try {
      const saved = await commit();
      if (!alive.current) return true;
      if (saved) {
        setItems((rows) => rows.map((r) =>
          keyRef.current(r) === id ? ({ ...r, ...saved } as T) : r));
      }
      mark(id, null);
      if (said) toast.ok(said);
      generation.current += 1;
      reload();
      return true;
    } catch (e) {
      if (!alive.current) return false;
      setItems(snapshot);
      mark(id, null);
      toast.error(errorText(e, "That change could not be saved."));
      return false;
    }
  }, [mark, reload, toast]);

  const remove = useCallback(async (
    id: Id, commit: () => Promise<unknown>, said?: string,
  ) => {
    const snapshot = latest.current;
    generation.current += 1;
    // Marked before it goes, so the row can play its exit rather than blink out.
    mark(id, "removing");
    setItems((rows) => rows.filter((r) => keyRef.current(r) !== id));
    try {
      await commit();
      if (!alive.current) return true;
      mark(id, null);
      if (said) toast.ok(said);
      generation.current += 1;
      reload();
      return true;
    } catch (e) {
      if (!alive.current) return false;
      // Back exactly where it was, in its old position, with the reason.
      setItems(snapshot);
      mark(id, null);
      toast.error(errorText(e, "That could not be removed."));
      return false;
    }
  }, [mark, reload, toast]);

  const stateOf = useCallback(
    (item: T) => pending.get(keyRef.current(item)) ?? "settled",
    [pending]);

  const isPending = useCallback(
    (item: T) => pending.has(keyRef.current(item)),
    [pending]);

  return {
    items, loading, error, reload,
    stateOf, isPending, create, update, remove, setItems,
  };
}

/** The class name for a row in a given state.
 *
 *  Kept here rather than written out at each call site so every list in the
 *  product fades and settles the same way, and so a new state cannot be added
 *  in the hook without somewhere to draw it.
 */
export function rowClass(state: RowState): string {
  return state === "settled" ? "" : `row-${state}`;
}
