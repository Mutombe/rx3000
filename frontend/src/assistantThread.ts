/** One conversation with RX-Assistant, shared by everything that shows it.
 *
 *  The dock in the corner and the page at /assistant are two components. The
 *  thread they show is not two threads, and it was: each held its own
 *  `useState`, so asking a question in the corner and then opening the full
 *  page showed an empty panel, and the answer that had just been given was
 *  reachable only through the history list. Closing the dock lost it outright.
 *  The effect on somebody using it is that the assistant forgets mid sentence,
 *  which is the one thing an assistant may not do.
 *
 *  So the thread lives here, above both, and they subscribe to it. It also
 *  survives a reload, because a dispenser who reloads the till in the middle
 *  of asking something has not changed their mind about the question.
 *
 *  Session storage, not local: a conversation is the shape of one shift at one
 *  counter. Carrying yesterday's questions into this morning would be a second
 *  kind of wrong, and the history list is where an old thread belongs.
 */
import { readSession, writeSession } from "./storage";

export interface AssistantStep { name: string; say: string; done?: string; ms?: number }

export interface AssistantTurn {
  question: string;
  shown?: { preview: string; name: string; media_type: string }[];
  text: string;
  steps: AssistantStep[];
  routes: { title: string; steps: any[] }[];
  diagrams: { title: string; mermaid: string }[];
  model?: string;
  error?: string;
  live?: boolean;
  ms?: number;
}

const KEY = "assistant_thread";

/** Attachment previews are data URLs of a screenshot each, and a few of them
 *  will not fit in session storage. The thread keeps them in memory for as
 *  long as the tab is open and drops them from what is written down, so a
 *  reload loses the thumbnails and keeps every word. */
function forStorage(turns: AssistantTurn[]): AssistantTurn[] {
  return turns.map((t) => ({ ...t, shown: undefined, live: false }));
}

function load(): AssistantTurn[] {
  try {
    const raw = readSession(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    // A tab with storage blocked still has to hold a conversation; it simply
    // cannot carry it across a reload.
    return [];
  }
}

let turns: AssistantTurn[] = load();
const listeners = new Set<() => void>();

export function getThread(): AssistantTurn[] {
  return turns;
}

export function subscribeThread(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** Replace the thread, the way a `useState` setter does, so the call sites
 *  that already read like React keep reading like React. */
export function setThread(next: AssistantTurn[] | ((all: AssistantTurn[]) => AssistantTurn[])) {
  turns = typeof next === "function" ? (next as any)(turns) : next;
  try { writeSession(KEY, JSON.stringify(forStorage(turns))); } catch { /* see load */ }
  for (const fn of listeners) fn();
}

/** Start again. What was there is already in the history list, which is where
 *  somebody looks for it. */
export function clearThread() {
  setThread([]);
}
