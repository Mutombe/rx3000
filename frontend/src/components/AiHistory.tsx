/** The log of what you have asked the assistant.
 *
 *  A drawer rather than a page, because looking something up is not leaving what
 *  you are doing. The question you asked on Tuesday is usually wanted *while*
 *  you are asking a related one today, and a route change loses the half-typed
 *  one in the box.
 *
 *  Two things it is careful about:
 *
 *  **It says how many there are, not how many it fetched.** The endpoint returns
 *  one more row than the limit so "there are older ones" is a fact. A list that
 *  reports its own page size as the total is the most common way software lies
 *  by accident.
 *
 *  **Opening an entry shows what was said then**, not a fresh answer. Re-running
 *  the question would answer about today, which is a different question; quietly
 *  substituting one for the other stops the log being a record.
 */
import { useCallback, useEffect, useState } from "react";
import { ClockCounterClockwise, Trash, X } from "@phosphor-icons/react";
import { api, errorText, fmtDateTime } from "../api";
import BusyButton from "./BusyButton";
import { useConfirm } from "./Confirm";

export interface AiEntry {
  id: number;
  question: string;
  answer: string;
  model: string;
  created_at: string | null;
}

export default function AiHistory({
  open, onClose, onOpenEntry, reloadKey,
}: {
  open: boolean;
  onClose: () => void;
  /** Show this exchange in the page behind the drawer. */
  onOpenEntry: (entry: AiEntry) => void;
  /** Changes when a new answer has been saved, so the list refetches. */
  reloadKey: number;
}) {
  const [items, setItems] = useState<AiEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [more, setMore] = useState(false);
  const [failed, setFailed] = useState("");
  const [loading, setLoading] = useState(false);
  const confirm = useConfirm();

  const load = useCallback(() => {
    setLoading(true);
    return api.get<{ items: AiEntry[]; more: boolean; total: number }>("/api/ai/history?limit=50")
      .then((r) => { setItems(r.items); setMore(r.more); setTotal(r.total); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "Your history could not be loaded.")))
      .finally(() => setLoading(false));
  }, []);

  // Only when it is actually open. A drawer nobody has opened should not be
  // fetching on every answer.
  useEffect(() => { if (open) load(); }, [open, reloadKey, load]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function removeOne(entry: AiEntry) {
    if (!(await confirm({
      title: "Remove this from your history?",
      body: entry.question,
      confirmLabel: "Remove",
      destructive: true,
    }))) return;
    await api.delete(`/api/ai/history/${entry.id}`);
    await load();
  }

  async function clearAll() {
    if (!(await confirm({
      title: `Clear all ${total} questions?`,
      body: "This empties your own log. Nobody else's is touched, and it cannot be undone.",
      confirmLabel: "Clear my history",
      destructive: true,
    }))) return;
    await api.delete("/api/ai/history");
    await load();
  }

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-label="Assistant history">
        <header className="drawer-head">
          <div>
            <b><ClockCounterClockwise size={15} /> History</b>
            <span className="muted">
              {/* The real total, not the number of rows on screen. */}
              {total === 0 ? "nothing asked yet"
                : `${total} question${total === 1 ? "" : "s"}${more ? `, showing the last ${items.length}` : ""}`}
            </span>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close history" title="Close">
            <X size={15} />
          </button>
        </header>

        {failed && <div className="alert error">{failed}</div>}

        <div className="drawer-body">
          {loading && !items.length && <p className="muted">Reading your history…</p>}
          {!loading && !items.length && !failed && (
            <div className="empty">
              Nothing here yet. Every answer you get is kept, so you can come back
              to it.
            </div>
          )}
          <ul className="ai-log">
            {items.map((e) => (
              <li key={e.id}>
                <button className="ai-log-item" onClick={() => { onOpenEntry(e); onClose(); }}>
                  <b>{e.question}</b>
                  <span className="muted">
                    {e.created_at ? fmtDateTime(e.created_at) : ""}
                    {e.model ? ` · ${e.model}` : ""}
                  </span>
                </button>
                <BusyButton
                  className="icon-btn is-danger"
                  onClick={() => removeOne(e)}
                  icon={Trash}
                  iconSize={13}
                  title="Remove"
                  aria-label={`Remove: ${e.question}`}
                />
              </li>
            ))}
          </ul>
        </div>

        {items.length > 0 && (
          <footer className="drawer-foot">
            <BusyButton className="btn ghost small" onClick={clearAll} icon={Trash} busyLabel="Clearing…">
              Clear my history
            </BusyButton>
          </footer>
        )}
      </aside>
    </>
  );
}
