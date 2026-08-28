/** The pharmacy's own departments, and what sits in each.
 *
 *  Every pharmacy already groups its stock this way and calls it a department:
 *  dispensary, over the counter, cosmetics, consignment. It decides where a
 *  line sits on a stocktake sheet, which margin is expected of it, and which
 *  report it lands in.
 *
 *  Valued at cost as well as counted, because a count on its own compares the
 *  wrong things: fifteen hundred cosmetics lines worth two thousand dollars and
 *  eleven hundred dispensary lines worth fifteen thousand are not the same
 *  business, and only one of those numbers says so.
 *
 *  Anything nobody has filed is shown at the top rather than left out. An
 *  untagged line is invisible on every department report, and that is exactly
 *  how a product quietly stops being counted.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import { useToast } from "../components/Toast";

interface Category {
  id: number; code: string; name: string; target_margin: number;
  active: boolean; products: number; in_stock: number; at_cost: number;
}

export default function StockCategories() {
  const [rows, setRows] = useState<Category[]>([]);
  const [untagged, setUntagged] = useState(0);
  const [error, setError] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", code: "", target_margin: "" });
  const toast = useToast();

  const load = useCallback(() => {
    setSpinning(true);
    api.get<{ items: Category[]; untagged: number }>("/api/stock-categories")
      .then((d) => { setRows(d.items ?? []); setUntagged(d.untagged ?? 0); setError(""); })
      .catch((e) => setError(errorText(e, "The departments could not be loaded.")))
      .finally(() => window.setTimeout(() => setSpinning(false), 350));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function create() {
    try {
      await api.post("/api/stock-categories", {
        name: form.name,
        code: form.code,
        target_margin: Number(form.target_margin) || 0,
      });
      toast.ok(`${form.name} added.`);
      setAdding(false);
      setForm({ name: "", code: "", target_margin: "" });
      load();
    } catch (e) {
      toast.error(errorText(e, "That department could not be added."));
    }
  }

  const totalLines = rows.reduce((n, r) => n + r.products, 0);
  const totalValue = rows.reduce((n, r) => n + r.at_cost, 0);
  const totalStocked = rows.reduce((n, r) => n + r.in_stock, 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Stock departments</h1>
          <div className="sub">How this pharmacy groups what it sells</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" onClick={load}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
          </button>
          <button className="btn" onClick={() => setAdding(true)}>New department</button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="wc-bands">
        <div className="wl-stat"><b>{rows.length}</b><span>departments</span></div>
        <div className="wl-stat"><b>{totalLines.toLocaleString()}</b><span>lines catalogued</span></div>
        <div className="wl-stat"><b>{totalStocked.toLocaleString()}</b><span>with stock on hand</span></div>
        <div className="wl-stat"><b>{money(totalValue)}</b><span>on the shelf, at cost</span></div>
      </div>

      {untagged > 0 && (
        <div className="alert warn">
          <Warning size={16} weight="fill" />
          <span>
            <b>{untagged.toLocaleString()} {untagged === 1 ? "line is" : "lines are"} filed
            under no department.</b> They will not appear on any departmental
            report — not the stocktake sheet, not the margin comparison, not the
            valuation. That is how a product stops being counted without anybody
            deciding it should.{" "}
            <EntityLink to="/stock">Open the catalogue</EntityLink> to file them.
          </span>
        </div>
      )}

      <div className="card">
        <table className="dt">
          <thead>
            <tr>
              <th>Department</th>
              <th className="num">Lines</th>
              <th className="num">With stock</th>
              <th className="num">At cost</th>
              <th className="num">Target margin</th>
              <th className="actions" />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td>
                  <b>{c.name}</b>
                  {c.code && <div className="muted small mono">{c.code}</div>}
                </td>
                <td className="num">{c.products.toLocaleString()}</td>
                <td className="num">
                  {c.in_stock.toLocaleString()}
                  {/* A department where almost nothing is in stock is either
                      seasonal or badly ordered, and the proportion says which
                      faster than the two counts side by side do. */}
                  {c.products > 0 && (
                    <div className="muted small">
                      {Math.round((100 * c.in_stock) / c.products)}% of the range
                    </div>
                  )}
                </td>
                <td className="num"><b>{money(c.at_cost)}</b></td>
                <td className="num">
                  {c.target_margin
                    ? `${c.target_margin}%`
                    : <span className="muted">not set</span>}
                </td>
                <td className="actions">
                  <EntityLink to={`/stock?category_id=${c.id}`}>
                    <button className="btn small secondary">See the lines</button>
                  </EntityLink>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !spinning && (
          <div className="empty">
            No departments yet. Every pharmacy groups its stock somehow — adding
            those groups here is what makes the stocktake and the margin reports
            mean anything.
          </div>
        )}
      </div>

      {adding && (
        <div className="modal-backdrop" onClick={() => setAdding(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>New department</h2>
            <label className="field">
              Name
              <input value={form.name} autoFocus
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder="e.g. Dispensary" />
            </label>
            <div className="form-row">
              <div className="field">
                <label>Your code</label>
                <input value={form.code}
                       onChange={(e) => setForm({ ...form, code: e.target.value })}
                       placeholder="as it appears on your own reports" />
              </div>
              <div className="field">
                <label>Target margin %</label>
                <input type="number" value={form.target_margin}
                       onChange={(e) => setForm({ ...form, target_margin: e.target.value })}
                       placeholder="optional" />
              </div>
            </div>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setAdding(false)}>Cancel</button>
              <BusyButton disabled={form.name.trim().length < 2} onClick={create}>
                Add it
              </BusyButton>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
