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
import { api, money, errorText, fmtDateTime } from "../api";
import { useToast } from "./Toast";
import { useConfirm } from "./Confirm";
import Select from "./Select";

interface Tender {
  method: string; instrument: string; label: string;
  currencies: string[]; is_cash_drawer: boolean; is_delivery: boolean;
}
interface Setup {
  currencies: string[]; currency: string;
  denominations: number[]; tenders: Tender[];
}
interface Line {
  method: string; instrument: string; label: string; currency: string;
  counted: number; system: number; difference: number;
  counted_in_drawer: boolean; is_delivery: boolean; unnamed: boolean;
}
interface OnRoad { label: string; currency: string; amount: number; count: number }
interface Result {
  lines: Line[]; opening_float: number;
  expected_cash: number; counted_cash: number; cash_variance: number;
  total_counted: number; total_system: number; variance: number;
  unattributed: number;
  on_the_road: OnRoad[]; on_the_road_total: number; unnamed_total: number;
  // Till / Run / Draw — what the run is keyed on, and what somebody quotes when
  // they come back to ask about it.
  till_no?: string | null; run_number?: number | null;
  void_count: number; void_total: number;
  credit_count: number; credit_total: number;
}

interface RunDoc {
  id: number; sale_number: string; at: string | null;
  status: string; total: number; methods: string[];
}
interface RunList {
  documents: number; showing: number;
  paid: { count: number; total: number };
  void: { count: number; total: number };
  credited: { count: number; total: number };
  pending: { count: number; total: number };
  invoices: RunDoc[];
  till_no?: string | null; run_number?: number | null; draw_no?: string | null;
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
  // The run's documents, fetched only once a count exists — the server refuses
  // before that, because a list of invoices adds up to the figure the count is
  // supposed to reach on its own.
  const [run, setRun] = useState<RunList | null>(null);
  const [showRun, setShowRun] = useState(false);

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
            entered again afterwards. That is what makes it worth anything.
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
      toast.error(errorText(e, "That count could not be recorded."));
    } finally {
      setBusy(false);
    }
  }

  if (!setup) return <div className="card"><div className="empty">Loading the drawer…</div></div>;

  async function loadRun() {
    setShowRun(true);
    if (run) return;
    try {
      setRun(await api.get<RunList>(`/api/shifts/${shiftId}/invoices`));
    } catch (e) {
      toast.error(errorText(e, "The invoices for this run could not be listed."));
      setShowRun(false);
    }
  }

  if (result) {
    const runLabel = [
      result.till_no ? `Till ${result.till_no}` : "",
      result.run_number ? `run ${result.run_number}` : "",
    ].filter(Boolean).join(" · ");

    return (
      <div className="card">
        <div className="cu-head">
          <h3 style={{ margin: 0 }}>Cash-up</h3>
          {/* Only rendered when there is something to render. A shift opened
              before runs were numbered has no run, and "run 0" reads as a real
              answer. */}
          {runLabel && <span className="cu-run mono">{runLabel}</span>}
        </div>
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
              {result.lines.filter(
                (l) => l.counted || l.system || Math.abs(l.difference) >= 0.01,
              ).map((l) => {
                const off = Math.abs(l.difference) >= 0.01;
                return (
                  <tr key={`${l.instrument || l.method}-${l.currency}`}
                      className={off ? "is-off" : ""}>
                    <td>
                      {l.label}
                      {/* The wallet or the bank is the whole point of the
                          split — "Mobile money 119.00" is not something
                          anybody can tick off against a statement. */}
                      {l.currency && l.currency !== currency && (
                        <span className="muted small"> · {l.currency}</span>
                      )}
                      {l.is_delivery && (
                        <span className="muted small"> · on the road</span>
                      )}
                    </td>
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

        {result.on_the_road_total > 0 && (
          // Beside the variance, not inside it. Cash on delivery is cash, and
          // it is on a motorbike somewhere — counted against this drawer it
          // tells a cashier they are short by the size of the round, and
          // people stop reading variances they know are wrong.
          <p className="st-note">
            {money(result.on_the_road_total)} is out with drivers and not in
            this drawer:{" "}
            {result.on_the_road.map((r) => (
              `${r.count} on ${r.label.toLowerCase()}`
            )).join(", ")}. It lands in a till when the round is handed in.
          </p>
        )}

        {result.unnamed_total > 0 && (
          // Not an error and not hidden. The money is in the totals; it just
          // cannot be matched to a wallet or a bank until whatever sent it is
          // fixed, and saying so is how that gets fixed.
          <p className="st-note is-bad">
            {money(result.unnamed_total)} came in without an instrument, so it
            is grouped under its payment type and cannot be ticked off against
            a statement.
          </p>
        )}

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

        {/* Voids and credits sit next to the variance because that is where they
            are read. A sale voided after the cash was taken leaves the drawer
            over by exactly the voided amount, so a clean variance with a large
            void total is a different story from a clean variance without one. */}
        {(result.void_count > 0 || result.credit_count > 0) && (
          <p className="st-note">
            {result.void_count > 0 && (
              <>{result.void_count} sale{result.void_count === 1 ? "" : "s"} voided
                during this run, {money(result.void_total)} in total. </>
            )}
            {result.credit_count > 0 && (
              <>{result.credit_count} credit{result.credit_count === 1 ? "" : "s"} raised,
                {" "}{money(result.credit_total)}.</>
            )}
          </p>
        )}

        {showRun && run && (
          <div className="cu-scroll cu-run-list">
            <p className="muted small">
              {run.documents} document{run.documents === 1 ? "" : "s"} in this run
              {run.showing < run.documents
                // Said plainly. A shortened list presented as the whole thing is
                // the mistake this codebase has made repeatedly.
                ? `. Showing the first ${run.showing}. The totals above cover all ${run.documents}.`
                : "."}
            </p>
            {/* Only when there is something to list. A table of headings above no
                rows reads as a failure to load rather than as an empty run. */}
            {run.invoices.length > 0 && (
            <table className="cu-table">
              <thead>
                <tr>
                  <th>Invoice</th><th>Time</th><th>Status</th>
                  <th>Tender</th><th className="st-amount">Total</th>
                </tr>
              </thead>
              <tbody>
                {run.invoices.map((d) => (
                  <tr key={d.id} className={d.status === "void" ? "is-off" : ""}>
                    <td className="mono">{d.sale_number}</td>
                    <td>{d.at ? fmtDateTime(d.at) : "—"}</td>
                    <td>{d.status}</td>
                    <td>{d.methods.join(", ") || "—"}</td>
                    <td className="st-amount mono">{money(d.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </div>
        )}

        <div className="cu-actions">
          {!showRun && (
            <button className="small ghost" onClick={loadRun}>
              Show the invoices in this run
            </button>
          )}
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
              <Select
                value={String(currency ?? "")}
                onChange={(__value) => { setCurrency(__value); setCoins({}); }}
                options={[...setup.currencies.map((c) => ({ value: String(c), label: c }))]}
              />
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
        {/* The pharmacy's own instruments, from the same list the till offers.
            Cash is counted by denomination above; anything a driver is holding
            is not this drawer's to count and is left off entirely rather than
            offered to somebody being helpful. */}
        {setup.tenders.filter((t) => !t.is_cash_drawer && !t.is_delivery)
          .map((t) => (
          <label key={t.instrument} className="rr-param">
            <span>{t.label}</span>
            <input
              type="number"
              step="0.01"
              value={others[t.instrument] ?? ""}
              onChange={(e) => setOthers(
                (o) => ({ ...o, [t.instrument]: e.target.value }))}
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
