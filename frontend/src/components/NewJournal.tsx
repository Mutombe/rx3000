/** Post a journal entry by hand.
 *
 *  Almost everything in this ledger is posted by something else — a sale, a
 *  delivery, a supplier payment — and that is right. But a pharmacy still has
 *  entries nobody else will make: a bank charge the statement showed and
 *  nothing raised, a correction to last month, an owner's drawing, a write-off
 *  the stock module cannot express. The endpoint has existed since the ledger
 *  was written and nothing called it, so the only way to make one was a
 *  developer with curl.
 *
 *  The rule is the server's and it is absolute: **it balances or it does not
 *  post.** So the balance is shown as it is typed rather than discovered on
 *  submit, and the button stays out of reach until the two sides agree. An
 *  accountant knows a journal must balance; what they should not have to do is
 *  press a button to find out whether this one does.
 */
import { useMemo, useState } from "react";
import { Plus, Trash } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "./BusyButton";
import Select from "./Select";
import { useToast } from "./Toast";

interface Account { code: string; name: string; type: string }
interface Line { account_code: string; debit: string; credit: string; description: string }

const blank = (): Line => ({ account_code: "", debit: "", credit: "", description: "" });

export default function NewJournal({ accounts, onClose, onPosted }: {
  accounts: Account[];
  onClose: () => void;
  onPosted?: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [entryDate, setEntryDate] = useState(today);
  const [description, setDescription] = useState("");
  // Two lines to start with, because a journal with one is not a journal.
  const [lines, setLines] = useState<Line[]>([blank(), blank()]);
  const toast = useToast();

  const debits = useMemo(
    () => Math.round(lines.reduce((n, l) => n + (Number(l.debit) || 0), 0) * 100) / 100,
    [lines]);
  const credits = useMemo(
    () => Math.round(lines.reduce((n, l) => n + (Number(l.credit) || 0), 0) * 100) / 100,
    [lines]);
  const out = Math.round((debits - credits) * 100) / 100;
  const balanced = Math.abs(out) < 0.005 && debits > 0.005;

  const usable = lines.filter(
    (l) => l.account_code && ((Number(l.debit) || 0) > 0 || (Number(l.credit) || 0) > 0));
  const ready = balanced && description.trim().length >= 3 && usable.length >= 2;

  function set(i: number, patch: Partial<Line>) {
    setLines((rows) => rows.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  }

  async function post() {
    try {
      await api.post("/api/ledger/entries", {
        description: description.trim(),
        entry_date: entryDate,
        source: "manual",
        lines: usable.map((l) => ({
          account_code: l.account_code,
          debit: Number(l.debit) || 0,
          credit: Number(l.credit) || 0,
          description: l.description.trim(),
        })),
      });
      toast.ok(`Posted ${money(debits)}.`);
      onPosted?.();
      onClose();
    } catch (e) {
      // The server refuses an unbalanced entry, a closed period and an unknown
      // account, and its wording says which. Shown as written.
      toast.error(errorText(e, "That entry could not be posted."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-full" onClick={(e) => e.stopPropagation()}>
        <h2>New journal entry</h2>
        <p className="muted">
          For what nothing else posts: a bank charge the statement showed, a
          correction, a write-off. Sales, deliveries and supplier payments post
          themselves and should not be entered here.
        </p>

        <div className="form-row">
          <div className="field span-3">
            <label>Date</label>
            <input type="date" value={entryDate}
                   onChange={(e) => setEntryDate(e.target.value)} />
          </div>
          <div className="field span-9">
            <label>Description</label>
            <input value={description} autoFocus
                   onChange={(e) => setDescription(e.target.value)}
                   placeholder="What this entry is for" />
          </div>
        </div>

        <table className="dt">
          <thead>
            <tr>
              <th>Account</th><th>Narration</th>
              <th className="num">Debit</th><th className="num">Credit</th>
              <th className="actions" />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td>
                  <Select
                    value={l.account_code}
                    onChange={(v) => set(i, { account_code: v })}
                    options={[{ value: "", label: "Which account?" },
                              ...accounts.map((a) => ({
                                value: a.code, label: `${a.code} · ${a.name}`,
                                hint: a.type }))]}
                    ariaLabel="Account"
                  />
                </td>
                <td>
                  <input value={l.description}
                         onChange={(e) => set(i, { description: e.target.value })}
                         placeholder="optional" />
                </td>
                <td className="num">
                  <input type="number" step="0.01" min="0" className="tender-amount"
                         value={l.debit}
                         // One side or the other, never both: a line carrying a
                         // debit and a credit is two lines somebody has merged.
                         onChange={(e) => set(i, { debit: e.target.value, credit: "" })}
                         placeholder="0.00" />
                </td>
                <td className="num">
                  <input type="number" step="0.01" min="0" className="tender-amount"
                         value={l.credit}
                         onChange={(e) => set(i, { credit: e.target.value, debit: "" })}
                         placeholder="0.00" />
                </td>
                <td className="actions">
                  {lines.length > 2 && (
                    <button className="btn ghost small" aria-label="Remove this line"
                            onClick={() => setLines(lines.filter((_, n) => n !== i))}>
                      <Trash size={13} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={2}><b>Totals</b></td>
              <td className="num"><b>{money(debits)}</b></td>
              <td className="num"><b>{money(credits)}</b></td>
              <td />
            </tr>
          </tfoot>
        </table>

        <button className="btn ghost small" onClick={() => setLines([...lines, blank()])}>
          <Plus size={13} /> Another line
        </button>

        {/* Shown as it is typed rather than discovered on submit. An accountant
            knows a journal must balance; what they should not have to do is
            press a button to find out whether this one does. */}
        <div className={`alert ${balanced ? "ok" : "warn"}`}>
          {balanced
            ? <>Balanced. {money(debits)} each side.</>
            : debits < 0.005 && credits < 0.005
              ? <>Enter the two sides. It balances or it does not post.</>
              : <>Out by <b>{money(Math.abs(out))}</b> — {out > 0
                  ? "the credits are short" : "the debits are short"}.</>}
        </div>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" disabled={!ready} onClick={post}
                      busyLabel="Posting…">
            Post {balanced ? money(debits) : ""}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
