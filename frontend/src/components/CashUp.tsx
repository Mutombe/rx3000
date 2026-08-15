/** Cashing up a till, counted blind.
 *
 *  The screen this replaces puts the expected figure next to the box you type
 *  the counted figure into. Nobody sets out to copy it and almost everybody
 *  eventually does, and a till that always balances is telling you nothing.
 *
 *  So this screen cannot show the expected figure, because it has not been sent
 *  one. The server does not release it until a count has been committed. That
 *  distinction matters: a control that relies on the front end choosing not to
 *  display something it was given is not a control, it is an honour system with
 *  extra steps.
 *
 *  Cash is counted by denomination rather than as a total. The operator counts
 *  objects — seven singles, two hundreds — and asking them to do the
 *  multiplication in their head is asking for exactly the arithmetic error the
 *  count exists to catch.
 */
import { useEffect, useMemo, useState } from "react";
import { api, money } from "../api";
import { useToast } from "./Toast";
import { useConfirm } from "./Confirm";

interface Tender { method: string; label: string }
interface Setup {
  currencies: string[]; currency: string;
  denominations: number[]; tenders: Tender[];
}
interface Line {
  method: string; label: string;
  counted: number; system: number; difference: number;
}
interface Result {
  lines: Line[]; opening_float: number;
  expected_cash: number; counted_cash: number; cash_variance: number;
  total_counted: number; total_system: number; variance: number;
  unattributed: number;
}

export default function CashUp(
  { shiftId, onCounted }: { shiftId: number; onCounted?: () => void },
) {
  const toast = useToast();
  const confirm = useConfirm();
  const [setup, setSetup] = useState<Setup | null>(null);
  const [currency, setCurrency] = useState("");
  const [coins, setCoins] = useState<Record<string, string>>({});
  const [others, setOthers] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [till, setTill] = useState("");
  const [draw, setDraw] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const q = currency ? `?currency=${currency}` : "";
    api.get<Setup>(`/api/shifts/cashup/denominations${q}`)
      .then((s) => { setSetup(s); if (!currency) setCurrency(s.currency); })
      .catch(() => {});
  }, [currency]);

  // Shown as the operator counts, because it is their own arithmetic, not the
  // system's opinion. Seeing the drawer total build up is how a miscount gets
  // noticed before it is committed.
  const countedCash = useMemo(
    () => Object.entries(coins).reduce(
      (sum, [face, n]) => sum + Number(face) * (Number(n) || 0), 0),
    [coins],
  );

  async function submit() {
    const ok = await confirm({
      title: "Commit this count?",
      body: (
        <>
          <p>
            You are recording <b>{money(countedCash)}</b> in the drawer
            {Object.keys(others).length > 0 && " plus the other tenders you entered"}.
          </p>
          <p>
            The expected figure appears once you commit, and the count cannot be
            entered again afterwards — that is what makes it worth anything.
          </p>
        </>
      ),
      confirmLabel: "Commit the count",
    });
    if (!ok) return;

    setBusy(true);
    try {
      const counted: Record<string, number> = {};
      Object.entries(others).forEach(([k, v]) => { if (v) counted[k] = Number(v) || 0; });
      const coinage: Record<string, number> = {};
      Object.entries(coins).forEach(([k, v]) => { if (Number(v)) coinage[k] = Number(v); });
      setResult(await api.post<Result>(`/api/shifts/${shiftId}/cashup`, {
        counted, coinage, currency, notes, till_no: till, draw_no: draw,
      }));
      toast.ok("Count recorded and the shift is closed.");
      // Deliberately NOT telling the page to reload here. Committing closes the
      // shift, so a reload makes the parent stop rendering this component — and
      // the reconciliation, which is the entire output of the exercise, would
      // disappear the instant it was produced. The operator dismisses it when
      // they have read it.
    } catch (e: any) {
      toast.error(e?.message || "That count could not be recorded.");
    } finally {
      setBusy(false);
    }
  }

  if (!setup) return <div className="card"><div className="empty">Loading the drawer…</div></div>;

  if (result) {
    return (
      <div className="card">
        <h3>Cash-up</h3>
        <div className="cu-scroll">
          <table className="cu-table">
            <thead>
              <tr>
                <th>Tender</th>
                <th className="st-amount">Counted</th>
                <th className="st-amount">System</th>
                <th className="st-amount">Difference</th>
              </tr>
            </thead>
            <tbody>
              {result.lines.map((l) => {
                const off = Math.abs(l.difference) >= 0.01;
                return (
                  <tr key={l.method} className={off ? "is-off" : ""}>
                    <td>{l.label}</td>
                    <td className="st-amount mono">{money(l.counted)}</td>
                    <td className="st-amount mono">{money(l.system)}</td>
                    <td className={`st-amount mono${off ? " cu-diff" : ""}`}>
                      {off ? money(l.difference) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td>Total</td>
                <td className="st-amount mono">{money(result.total_counted)}</td>
                <td className="st-amount mono">{money(result.total_system)}</td>
                <td className="st-amount mono">{money(result.variance)}</td>
              </tr>
            </tfoot>
          </table>
        </div>

        <p className={`st-note ${Math.abs(result.variance) < 0.01 ? "is-ok" : "is-bad"}`}>
          {Math.abs(result.variance) < 0.01
            ? "The drawer agrees with the system."
            : result.variance > 0
              ? `The drawer is over by ${money(result.variance)}. Recorded against your name.`
              : `The drawer is short by ${money(Math.abs(result.variance))}. Recorded against your name.`}
        </p>

        {result.unattributed > 0 && (
          // Named rather than absorbed. Money we cannot attribute to a tender
          // is a gap in how something was recorded, and quietly folding it into
          // a total is how it stays a gap.
          <p className="st-note is-bad">
            {money(result.unattributed)} was taken on split payments with no tender
            breakdown, so it could not be attributed to a column. It is excluded
            from the figures above.
          </p>
        )}

        <div className="cu-actions">
          <button className="small" onClick={() => onCounted?.()}>Done</button>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="cu-head">
        <div>
          <h3 style={{ margin: 0 }}>Count the drawer</h3>
          <p className="muted" style={{ margin: "4px 0 0", maxWidth: "56ch" }}>
            Count what is physically there. The expected figure appears after you
            commit, so the count is yours rather than a copy of ours.
          </p>
        </div>
        <div className="cu-ident">
          <label className="rr-param">
            <span>Till</span>
            <input value={till} onChange={(e) => setTill(e.target.value)} />
          </label>
          <label className="rr-param">
            <span>Drawer</span>
            <input value={draw} onChange={(e) => setDraw(e.target.value)} />
          </label>
          {setup.currencies.length > 1 && (
            <label className="rr-param">
              <span>Currency</span>
              <select value={currency} onChange={(e) => { setCurrency(e.target.value); setCoins({}); }}>
                {setup.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          )}
        </div>
      </div>

      <h4 className="cu-section">Notes and coins</h4>
      <div className="cu-denoms">
        {setup.denominations.map((face) => {
          const key = String(face);
          const n = Number(coins[key]) || 0;
          return (
            <label key={key} className="cu-denom">
              <span className="cu-face">
                {face >= 1 ? money(face) : `${Math.round(face * 100)}c`}
              </span>
              <input
                type="number"
                min={0}
                inputMode="numeric"
                value={coins[key] ?? ""}
                onChange={(e) => setCoins((c) => ({ ...c, [key]: e.target.value }))}
                placeholder="0"
              />
              {/* Their own arithmetic, echoed back. Not the system's view. */}
              <span className="cu-sub mono">{n ? money(face * n) : ""}</span>
            </label>
          );
        })}
      </div>
      <div className="cu-total">
        <span>Counted in the drawer</span>
        <span className="mono">{money(countedCash)}</span>
      </div>

      <h4 className="cu-section">Other tenders</h4>
      <div className="cu-others">
        {setup.tenders.filter((t) => t.method !== "cash").map((t) => (
          <label key={t.method} className="rr-param">
            <span>{t.label}</span>
            <input
              type="number"
              step="0.01"
              value={others[t.method] ?? ""}
              onChange={(e) => setOthers((o) => ({ ...o, [t.method]: e.target.value }))}
              placeholder="0.00"
            />
          </label>
        ))}
      </div>

      <label className="rr-param" style={{ marginTop: "var(--s4)" }}>
        <span>Notes</span>
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Anything that explains a difference"
        />
      </label>

      <div className="cu-actions">
        <button className="small" onClick={submit} disabled={busy}>
          {busy ? "Recording…" : "Commit the count"}
        </button>
      </div>
    </div>
  );
}
