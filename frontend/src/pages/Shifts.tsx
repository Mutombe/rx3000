import { FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDateTime, money } from "../api";
import { Shift, ShiftTakings } from "../types";

export default function Shifts() {
  const [current, setCurrent] = useState<Shift | null>(null);
  const [history, setHistory] = useState<Shift[]>([]);
  const [openFloat, setOpenFloat] = useState("500");
  const [counted, setCounted] = useState("");
  const [notes, setNotes] = useState("");
  const [takings, setTakings] = useState<ShiftTakings | null>(null);
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  function load() {
    api.get<Shift | null>("/api/shifts/current").then((shift) => {
      setCurrent(shift);
      // Only meaningful once a shift exists; skipped entirely on single-currency tills.
      if (shift) {
        api.get<ShiftTakings>(`/api/shifts/${shift.id}/takings`).then(setTakings).catch(() => {});
      } else {
        setTakings(null);
      }
    }).catch((e) => toast.error(e.message));
    api.get<Shift[]>("/api/shifts").then(setHistory);
  }

  useEffect(load, []);

  async function openShift(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/api/shifts/open", { opening_float: Number(openFloat) || 0 });
      toast.ok("Shift opened — sales you process are now tracked against it.");
      load();
    } catch (err: any) { toast.error(err.message); } finally { setBusy(false); }
  }

  async function closeShift(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const closed = await api.post<Shift>("/api/shifts/close", {
        counted_cash: Number(counted) || 0, notes,
      });
      const v = closed.variance;
      toast.ok(
        Math.abs(v) < 0.005
          ? `Shift balanced exactly at ${money(closed.expected_cash)}.`
          : `Shift closed with a ${v > 0 ? "surplus" : "shortfall"} of ${money(Math.abs(v))}.`,
      );
      setCounted(""); setNotes("");
      load();
    } catch (err: any) { toast.error(err.message); } finally { setBusy(false); }
  }

  const variancePreview = current && counted !== ""
    ? Number(counted) - current.expected_cash
    : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Cash Office</h1>
          <div className="sub">Opening float, takings by tender and end-of-shift cash-up</div>
        </div>
      </div>

      {current ? (
        <>
          <div className="grid cols-4">
            <div className="card stat hero">
              <div className="label">Expected in drawer</div>
              <div className="value">{money(current.expected_cash)}</div>
              <div className="hint">Float {money(current.opening_float)} + cash sales</div>
            </div>
            <div className="card stat">
              <div className="label">Card takings</div>
              <div className="value">{money(current.card_total)}</div>
            </div>
            <div className="card stat">
              <div className="label">Medical aid</div>
              <div className="value">{money(current.medical_aid_total)}</div>
            </div>
            <div className="card stat">
              <div className="label">Transactions</div>
              <div className="value">{current.sales_count}</div>
              <div className="hint">since {fmtDateTime(current.opened_at)}</div>
            </div>
          </div>

          {takings && takings.currencies.length > 1 && (
            <div className="card">
              <h3>Takings by currency</h3>
              <p className="muted">
                Each currency has its own drawer. Cash is shown net of change,
                because change leaves the drawer in whichever currency it was given.
              </p>
              <table>
                <thead>
                  <tr><th>Currency</th><th className="num">Opening float</th><th className="num">Cash (net)</th>
                    <th className="num">Card</th><th className="num">Mobile money</th>
                    <th className="num">Expected in drawer</th></tr>
                </thead>
                <tbody>
                  {takings.currencies.map((c) => (
                    <tr key={c.currency}>
                      <td>
                        <b>{c.currency}</b>
                        {c.is_base && <span className="badge muted" style={{ marginLeft: 8 }}>base</span>}
                      </td>
                      <td className="num">{c.opening_float.toFixed(2)}</td>
                      <td className="num">{c.cash.toFixed(2)}</td>
                      <td className="num">{c.card.toFixed(2)}</td>
                      <td className="num">{c.mobile_money.toFixed(2)}</td>
                      <td className="num"><b>{c.expected_cash.toFixed(2)}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="card">
            <h3>Cash up &amp; close shift</h3>
            <form onSubmit={closeShift}>
              <div className="form-row">
                <div className="field">
                  <label>Cash counted in drawer</label>
                  <input type="number" step="0.01" value={counted} required
                    onChange={(e) => setCounted(e.target.value)} placeholder="0.00" autoFocus />
                </div>
                <div className="field">
                  <label>Notes</label>
                  <input value={notes} onChange={(e) => setNotes(e.target.value)}
                    placeholder="e.g. R50 paid out for delivery" />
                </div>
              </div>
              {variancePreview !== null && (
                <div className={Math.abs(variancePreview) < 0.005 ? "success-banner" : "error-banner"}>
                  {Math.abs(variancePreview) < 0.005
                    ? "Balances exactly."
                    : `${variancePreview > 0 ? "Over" : "Short"} by ${money(Math.abs(variancePreview))}`}
                </div>
              )}
              <button disabled={busy}>{busy ? "Closing…" : "Close shift"}</button>
            </form>
          </div>
        </>
      ) : (
        <div className="card">
          <h3>Start a shift</h3>
          <p className="muted">Count your opening float, then open a shift so every sale you take is attributed to it.</p>
          <form onSubmit={openShift} style={{ maxWidth: 320, marginTop: 12 }}>
            <div className="field">
              <label>Opening float</label>
              <input type="number" step="0.01" value={openFloat} onChange={(e) => setOpenFloat(e.target.value)} />
            </div>
            <button disabled={busy}>{busy ? "Opening…" : "Open shift"}</button>
          </form>
        </div>
      )}

      <div className="card">
        <h3>Shift history</h3>
        <table>
          <thead>
            <tr>
              <th>Cashier</th><th>Opened</th><th>Closed</th>
              <th className="num">Float</th><th className="num">Expected</th><th className="num">Counted</th>
              <th className="num">Variance</th><th className="num">Sales</th><th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {history.map((s) => (
              <tr key={s.id}>
                <td><b>{s.user?.full_name ?? s.user_id}</b></td>
                <td>{fmtDateTime(s.opened_at)}</td>
                <td>{s.closed_at ? fmtDateTime(s.closed_at) : <span className="badge">open</span>}</td>
                <td className="num">{money(s.opening_float)}</td>
                <td className="num">{money(s.expected_cash)}</td>
                <td className="num">{money(s.counted_cash)}</td>
                <td className="num">
                  {s.status === "closed" && (
                    <span className={`badge ${Math.abs(s.variance) < 0.005 ? "ok" : "danger"}`}>
                      {s.variance > 0 ? "+" : ""}{money(s.variance)}
                    </span>
                  )}
                </td>
                <td className="num">{s.sales_count}</td>
                <td className="muted">{s.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {history.length === 0 && <div className="empty">No shifts recorded yet</div>}
      </div>
    </>
  );
}
