import { FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import RowLink, { RowActions } from "../components/RowLink";
import PettyCash from "../components/PettyCash";
import CashUp from "../components/CashUp";
import { api, fmtDateTime, money, errorText, prefetchRoute } from "../api";
import { Shift, ShiftTakings } from "../types";
import { EntityLink } from "../components/Filters";
import { Refreshable, TableSkeleton } from "../components/Skeleton";

export default function Shifts() {
  const [current, setCurrent] = useState<Shift | null>(null);
  const [history, setHistory] = useState<Shift[]>([]);
  const [loading, setLoading] = useState(true);
  const [openFloat, setOpenFloat] = useState("500");
  const [till, setTill] = useState("1");
  const [draw, setDraw] = useState("");
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
    }).catch((e) => toast.error(errorText(e)));
    api.get<Shift[]>("/api/shifts").then(setHistory)
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function openShift(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/api/shifts/open", {
        opening_float: Number(openFloat) || 0,
        till_no: till.trim(), draw_no: draw.trim(),
      });
      toast.ok("Shift opened, sales you process are now tracked against it.");
      load();
    } catch (err: any) { toast.error(errorText(err)); } finally { setBusy(false); }
  }

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
              {/* This was the expected drawer total, in the largest type on the
                  page, directly above the box you type your count into. The
                  float is the useful part and gives nothing away: it is what
                  was in the drawer before trading, not what should be in it
                  now. */}
              <div className="label">Opening float</div>
              <div className="value">{money(current.opening_float)}</div>
              <div className="hint">Counted in at the start of this shift</div>
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
</tr>
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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <CashUp shiftId={current.id} onCounted={load} />

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
            {/* Asked now, not at cash-up. The run number is allocated per till
                when the shift opens, so the run has an identity while it is
                still trading rather than only once the money is counted. */}
            <div className="field">
              <label>Till</label>
              <input
                value={till} onChange={(e) => setTill(e.target.value)}
                placeholder="e.g. 1"
              />
            </div>
            <div className="field">
              <label>Drawer <span className="muted">(optional)</span></label>
              <input value={draw} onChange={(e) => setDraw(e.target.value)} />
            </div>
            <button disabled={busy}>{busy ? "Opening…" : "Open shift"}</button>
          </form>
        </div>
      )}

      {/* Sits with the drawer it affects rather than in an admin screen: the
          cash-up counts petty cash into what the till should hold. */}
      <PettyCash />

      <div className="card">
        <h3>Shift history</h3>
        <Refreshable
          loading={loading}
          hasData={history.length > 0}
          skeleton={<TableSkeleton cols={10} rows={5}
            widths={["14ch", "8ch", "12ch", "12ch", "8ch", "8ch", "8ch", "8ch", "8ch", "10ch"]} />}
        >
        <table>
          <thead>
            <tr>
              <th>Cashier</th><th>Run</th><th>Opened</th><th>Closed</th>
              <th className="num">Float</th><th className="num">Expected</th><th className="num">Counted</th>
              <th className="num">Variance</th><th className="num">Sales</th><th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {history.map((s) => (
              <RowLink key={s.id} to={`/shifts/${s.id}`}
                       prefetch={prefetchRoute}>
                <td><EntityLink kind="staff" id={s.user_id}><b>{s.user?.full_name ?? s.user_id}</b></EntityLink></td>
                {/* A run number without its till is meaningless, and every shift
                    opened before runs were numbered has neither. Both absent
                    shows a dash rather than "Till  · run 0". */}
                <td className="mono sh-run">
                  {s.till_no || s.run_number
                    ? [s.till_no && `Till ${s.till_no}`, s.run_number && `run ${s.run_number}`]
                        .filter(Boolean).join(" · ")
                    : "—"}
                </td>
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
              </RowLink>
            ))}
          </tbody>
        </table>
        {history.length === 0 && !loading && (
          <div className="empty">
            <b>No shifts recorded yet</b>
            <p>
              A shift is opened when somebody takes the till and closed when
              they count it. The history is what a cash-up is checked against.
            </p>
          </div>
        )}
        </Refreshable>
      </div>
    </>
  );
}
