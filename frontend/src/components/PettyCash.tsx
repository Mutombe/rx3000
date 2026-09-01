/** Money out of the drawer with no sale behind it, and back into it.
 *
 *  The endpoint was there, step-up gated, and no screen called it. That matters
 *  more than it sounds: the cash-up already adds petty cash into what the drawer
 *  should hold, so a payout that could not be recorded made the till short at
 *  every count by exactly the amount that left, and a cashier was asked to explain
 *  a variance that was never theirs.
 *
 *  One signed field rather than two buttons. Negative is money out, positive is
 *  money in, and the form says which as you type — two fields and a rule about
 *  which one to use is how a payout gets entered as a top-up.
 *
 *  Small amounts, often, with a description nobody checks is the oldest way to
 *  lose cash from a pharmacy. So a payout asks for a category and whether a
 *  receipt was actually seen, and the list shows which entries have no receipt
 *  behind them.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDateTime, money } from "../api";
import { useStepUp, CANCELLED } from "./StepUp";
import { useToast } from "./Toast";
import Checkbox from "./Checkbox";
import Select from "./Select";

interface Entry {
  id: number; amount: number; category: string; description: string;
  reference: string; receipt_seen: boolean; created_at?: string | null;
  user?: string;
}
interface Listing { net: number; entries: Entry[] }

const CATEGORIES = [
  "Cleaning", "Refreshments", "Transport", "Repairs", "Stationery",
  "Staff welfare", "Bank charges", "Other",
];

export default function PettyCash() {
  const toast = useToast();
  const { guarded, prompt } = useStepUp();
  const [list, setList] = useState<Listing | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  const [direction, setDirection] = useState<"out" | "in">("out");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [description, setDescription] = useState("");
  const [reference, setReference] = useState("");
  const [receiptSeen, setReceiptSeen] = useState(false);
  /* Which drawer it came out of. The column has been on the record since it
     was written and the form never set one, so every payout in a pharmacy that
     runs two currencies was recorded as an amount with no currency, and a ZiG
     taxi fare taken off a USD drawer is a variance nobody can explain. */
  const [currencyCode, setCurrencyCode] = useState("");
  const [currencies, setCurrencies] = useState<{ code: string; is_base?: boolean }[]>([]);

  useEffect(() => {
    api.get<any>("/api/currency")
      .then((c) => {
        const list = c?.currencies ?? [];
        setCurrencies(list);
        setCurrencyCode((prev) => prev || c?.base || list[0]?.code || "");
      })
      .catch(() => undefined);
  }, []);

  const load = useCallback(() => {
    api.get<Listing>("/api/shifts/petty-cash?limit=50")
      .then(setList)
      .catch((e) => toast.error(errorText(e, "The petty cash could not be listed.")));
  }, [toast]);

  useEffect(load, [load]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0) {
      toast.error("Enter the amount, as a number greater than zero.");
      return;
    }
    setBusy(true);
    try {
      // The sign is applied here from the chosen direction, so the person typing
      // enters a plain amount and cannot accidentally record a payout as a
      // top-up by forgetting a minus.
      const signed = direction === "out" ? -value : value;
      const res = await guarded(
        "pettycash.record",
        (token) => api.post<{ message: string }>("/api/shifts/petty-cash", {
          amount: signed,
          currency_code: currencyCode,
          category: category.trim(),
          description: description.trim(),
          reference: reference.trim(),
          receipt_seen: receiptSeen,
        }, token),
        `${direction} ${value}`,
      );
      if (res === CANCELLED) return;
      toast.ok(res.message);
      setAmount(""); setDescription(""); setReference(""); setReceiptSeen(false);
      setOpen(false);
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const noReceipt = (list?.entries ?? []).filter((e) => e.amount < 0 && !e.receipt_seen);

  return (
    <div className="card">
      {prompt}
      <div className="cu-head">
        <h3 style={{ margin: 0 }}>Petty cash</h3>
        <button className="btn small" onClick={() => setOpen((o) => !o)}>
          {open ? "Close" : "Record a movement"}
        </button>
      </div>
      <p className="muted">
        Money that left or entered the drawer without a sale. Counted into what the
        till should hold, so anything not recorded here shows up as a variance
        somebody has to explain.
      </p>

      {open && (
        <form onSubmit={save} className="pc-form">
          <div className="form-row">
            <div className="field">
              <label>Direction</label>
              <Select
                value={String(direction ?? "")}
                onChange={(__value) => setDirection(__value as "out" | "in")}
                options={[{ value: "out", label: "Out of the drawer" }, { value: "in", label: "Into the drawer" }]}
              />
            </div>
            <div className="field">
              <label>Amount</label>
              <input type="number" min="0.01" step="0.01" value={amount}
                onChange={(e) => setAmount(e.target.value)} required />
            </div>
            {/* Which drawer. Only worth asking where there is more than one —
                a single-currency pharmacy should not be made to answer it. */}
            {currencies.length > 1 && (
              <div className="field">
                <label>Out of which drawer</label>
                <Select
                  value={currencyCode}
                  onChange={setCurrencyCode}
                  options={currencies.map((c) => ({
                    value: c.code,
                    label: c.code + (c.is_base ? " (base)" : ""),
                  }))}
                />
              </div>
            )}
            <div className="field">
              <label>Category</label>
              <Select
                value={String(category ?? "")}
                onChange={(__value) => setCategory(__value)}
                options={[...CATEGORIES.map((c) => ({ value: String(c), label: c }))]}
              />
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>What it was for</label>
              <input value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. window cleaner, invoice 4471" required />
            </div>
            <div className="field">
              <label>Reference <span className="muted">(optional)</span></label>
              <input value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
          </div>
          {direction === "out" && (
            <div className="check-row">
              <Checkbox checked={receiptSeen} onChange={setReceiptSeen}>
              A receipt was seen for this
              <span className="muted">
                {" "}— payouts without one are listed separately below.
              </span>
              </Checkbox>
            </div>
          )}
          <div className="cu-actions">
            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? "Recording…" : direction === "out" ? "Record the payout" : "Record the top-up"}
            </button>
          </div>
        </form>
      )}

      {list && (
        <>
          <div className="stat-row">
            <div className="stat">
              <span className="stat-label">Net effect on the drawer</span>
              <span className="stat-value">{money(list.net)}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Payouts with no receipt</span>
              <span className={`stat-value${noReceipt.length ? " is-bad" : ""}`}>
                {noReceipt.length}
              </span>
            </div>
          </div>

          {list.entries.length === 0 ? (
            <div className="empty">Nothing recorded.</div>
          ) : (
            <div className="cu-scroll">
              <table>
                <thead>
                  <tr>
                    <th>When</th><th>Category</th><th>What for</th>
                    <th className="num">Amount</th><th>Receipt</th><th>By</th>
                  </tr>
                </thead>
                <tbody>
                  {list.entries.map((e) => (
                    <tr key={e.id}>
                      <td className="muted">
                        {e.created_at ? fmtDateTime(e.created_at) : "—"}
                      </td>
                      <td>{e.category || <span className="muted">—</span>}</td>
                      <td>
                        {e.description || <span className="muted">no description</span>}
                        {e.reference && <div className="muted mono small">{e.reference}</div>}
                      </td>
                      {/* Out is shown negative, because that is what it does to
                          the drawer. A payout displayed as a positive number is
                          how a float reconciles to the wrong figure. */}
                      <td className={`num${e.amount < 0 ? " cu-diff" : ""}`}>
                        {money(e.amount)}
                      </td>
                      <td>
                        {e.amount >= 0 ? <span className="muted">—</span>
                          : e.receipt_seen ? <span className="badge ok">seen</span>
                            : <span className="badge danger">none</span>}
                      </td>
                      <td className="muted">{e.user ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
