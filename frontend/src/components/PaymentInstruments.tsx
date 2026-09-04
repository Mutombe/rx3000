/** What this pharmacy takes money on.
 *
 *  One list, read by the till when it takes the money and by the cash-up when
 *  it counts it. They used to hold their own ideas of this and disagreed: the
 *  till knew the customer paid on EcoCash and wrote it into a free-text
 *  reference, and the cash-up reconciled seven hard-coded families and never
 *  read it, so EcoCash and InnBucks arrived as one "Mobile money" line that no
 *  statement in the world matches.
 *
 *  Editable because the list is not the same in two pharmacies. One banks with
 *  CBZ and one with Stanbic; one takes InnBucks and one does not; a new wallet
 *  appearing in the market should not need a release.
 *
 *  Two flags do real work and are worth reading before changing:
 *
 *    **In the drawer**: this is physically counted at close of trade. Cash is.
 *    A swipe is not, and asking somebody to count a card terminal is how a
 *    cash-up gets signed off without being read.
 *
 *    **Carried by a driver**: money collected at the door. It is deliberately
 *    NOT counted against the counter's till, because it is on a motorbike.
 */
import { useEffect, useState } from "react";
import { Plus } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import Select from "./Select";
import { useToast } from "./Toast";
import { useOptimisticList, rowClass } from "../hooks/useOptimisticList";

interface Instrument {
  id: number; code: string; name: string; method: string;
  currencies: string[]; settles_to: string;
  is_cash_drawer: boolean; is_delivery: boolean;
  active: boolean; sort_order: number;
}

const METHODS = [
  { value: "cash", label: "Cash" },
  { value: "card", label: "Card" },
  { value: "mobile_money", label: "Mobile money" },
  { value: "medical_aid", label: "Medical aid" },
  { value: "voucher", label: "Voucher" },
  { value: "cheque", label: "Cheque" },
  { value: "direct", label: "Direct deposit" },
];

export default function PaymentInstruments() {
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    code: "", name: "", method: "mobile_money",
    currencies: "USD", settles_to: "",
  });
  const toast = useToast();

  const list = useOptimisticList<Instrument>({
    load: () => api.get<Instrument[]>("/api/payment-instruments?include_retired=true"),
    key: (i) => i.id,
  });
  const rows = list.items;
  const load = list.reload;

  async function patch(i: Instrument, change: Partial<Instrument>) {
    // A one-field edit on a short list. `update` shows it at once and puts the
    // old value back if the server refuses — which is what the hand-written
    // version above did, except that it re-fetched the whole list to undo one
    // checkbox and lost any other edit in flight while it did.
    await list.update(i.id, change,
                      () => api.put(`/api/payment-instruments/${i.id}`, change));
  }

  async function create() {
    // Taken once, so the placeholder and the request cannot drift apart.
    const draft = { ...form } as unknown as Instrument;
    setAdding(false);
    const ok = await list.create(
      draft,
      () => api.post<Instrument>("/api/payment-instruments", draft),
      `${draft.name} added.`,
    );
    if (ok) {
      setForm({ code: "", name: "", method: "mobile_money",
                currencies: "USD", settles_to: "" });
    } else {
      // Still holding what they typed. A refusal here is nearly always a code
      // already in use, and that is one field to change.
      setAdding(true);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>Ways money arrives</h3>
          <span className="muted small">
            The till offers these and the cash-up counts them. One list, so the
            two cannot disagree about what the columns are.
          </span>
        </div>
        <button className="btn" onClick={() => setAdding(true)}>
          <Plus size={14} weight="bold" /> Add one
        </button>
      </div>

      {adding && (
        <div className="form-row" style={{ marginBottom: 12 }}>
          <div className="field span-3">
            <label>Name</label>
            <input value={form.name} autoFocus maxLength={60}
              onChange={(e) => setForm((f) => ({
                ...f, name: e.target.value,
                // A code nobody has to think about, derived from the name and
                // still editable. Codes end up in tender rows for years.
                code: f.code || e.target.value.toLowerCase()
                  .replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""),
              }))}
              placeholder="OneMoney" />
          </div>
          <div className="field span-2">
            <label>Code</label>
            <input value={form.code} maxLength={30} className="mono"
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
          </div>
          <div className="field span-3">
            <label>Counts as</label>
            <Select value={form.method} options={METHODS}
              onChange={(v) => setForm((f) => ({ ...f, method: v }))} />
          </div>
          <div className="field span-2">
            <label>Currencies</label>
            <input value={form.currencies} maxLength={60}
              onChange={(e) => setForm((f) => ({ ...f, currencies: e.target.value }))}
              placeholder="USD,ZWG" />
            <span className="hint">
              Only what it can actually take — offering ZiG on a USD-only wallet
              produces a payment the customer cannot make.
            </span>
          </div>
          <div className="field span-2">
            <label>Settles to</label>
            <input value={form.settles_to} maxLength={120}
              onChange={(e) => setForm((f) => ({ ...f, settles_to: e.target.value }))}
              placeholder="Merchant 0771 · Stanbic ••4417" />
          </div>
          <div className="field span-12">
            <BusyButton className="btn primary" onClick={create}
              disabled={!form.name.trim() || !form.code.trim()}
              busyLabel="Adding…">Add</BusyButton>{" "}
            <button className="btn ghost" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="dt-scroll">
        <table className="dt">
          <thead>
            <tr>
              <th>Instrument</th><th>Counts as</th><th>Currencies</th>
              <th>Settles to</th>
              <th className="num">In the drawer</th>
              <th className="num">Carried by a driver</th>
              <th className="num">Offered</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <tr key={i.id}
                  className={`${i.active ? "" : "row-muted"} ${rowClass(list.stateOf(i))}`.trim() || undefined}>
                <td>
                  <b>{i.name}</b>
                  <div className="muted small mono">{i.code}</div>
                </td>
                <td>
                  {METHODS.find((m) => m.value === i.method)?.label ?? i.method}
                </td>
                <td className="mono small">{i.currencies.join(", ") || "—"}</td>
                <td className="muted small">
                  {i.settles_to || (
                    // Not decoration. Ticking a column off against a statement
                    // means knowing which statement, and nothing else records it.
                    <span className="muted">not recorded</span>
                  )}
                </td>
                <td className="num">
                  <input type="checkbox" checked={i.is_cash_drawer}
                    onChange={(e) => patch(i, { is_cash_drawer: e.target.checked })} />
                </td>
                <td className="num">
                  <input type="checkbox" checked={i.is_delivery}
                    onChange={(e) => patch(i, { is_delivery: e.target.checked })} />
                </td>
                <td className="num">
                  <input type="checkbox" checked={i.active}
                    onChange={(e) => patch(i, { active: e.target.checked })} />
                </td>
              </tr>
            ))}
            {!rows.length && !loading && (
              <tr><td colSpan={7} className="muted pad">
                Nothing set up. Open a till once and the standard list appears.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="muted small">
        Retiring one keeps it on every payment already taken on it — the code is
        what says what those payments came in on.
      </p>
    </div>
  );
}
