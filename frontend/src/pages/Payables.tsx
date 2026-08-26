/** Supplier invoices: what was billed, what arrived, and what is still owed.
 *
 *  The ledger raised a creditor when goods were received, using the costs off
 *  the purchase order. That is an estimate, not a bill. Nothing here had ever
 *  read the invoice the wholesaler actually sent, so a price rise between
 *  ordering and delivery disappeared, being billed for more than arrived was
 *  invisible, and — because nothing anywhere debited trade creditors — the
 *  account only ever grew.
 *
 *  The screen leads with what is owed and what is late, because that is the
 *  question an owner opens it to answer. The match sits behind an invoice,
 *  where it is read at the moment somebody is deciding whether to pay.
 */
import { useCallback, useEffect, useState } from "react";
import {
  ArrowClockwise, CheckCircle, Question, Receipt, Warning,
} from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "../components/BusyButton";
import { useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";

interface AgeInvoice {
  invoice_id: number; invoice_number: string; invoice_date: string;
  due_date: string; total: number; outstanding: number;
  days_overdue: number; status: string; band: string;
}
interface AgeSupplier {
  supplier_id: number; supplier: string; bands: Record<string, number>;
  total: number; oldest_days: number; queried: number; invoices: AgeInvoice[];
}
interface Ageing {
  as_at: string; bands: string[]; totals: Record<string, number>;
  total: number; queried: number; suppliers: AgeSupplier[];
  control_balance: number; difference: number;
}
interface MatchLine {
  description: string; billed_quantity: number; received_quantity: number;
  billed_unit_cost: number; ordered_unit_cost: number; line_total: number;
  issues: string[];
}
interface MatchResult {
  depth: "lines" | "totals" | "none"; matched: boolean; order_number?: string;
  ordered: number; received: number; billed: number; variance: number;
  lines: MatchLine[]; problems: string[];
}
interface Invoice {
  id: number; invoice_number: string; supplier: string; supplier_id: number;
  order_number: string; invoice_date: string; due_date: string | null;
  total: number; status: string; query_note: string; posted_reference: string;
  paid: number; outstanding: number; match?: MatchResult;
}
interface Uninvoiced {
  order_id: number; order_number: string; supplier: string;
  received_at: string | null; value: number; days: number | null;
}

const DEPTH_SAYS: Record<string, string> = {
  lines: "Matched line by line against what was received.",
  totals: "Only the total was keyed, so this compares totals. A short delivery and an overcharge of the same size would cancel out and pass.",
  none: "No order is linked, so there is nothing to check this against.",
};

export default function Payables() {
  const [ageing, setAgeing] = useState<Ageing | null>(null);
  const [waiting, setWaiting] = useState<Uninvoiced[]>([]);
  const [open, setOpen] = useState<Invoice | null>(null);
  const [failed, setFailed] = useState("");
  const [spinning, setSpinning] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(async () => {
    setSpinning(true);
    try {
      const [aged, un] = await Promise.all([
        api.get<Ageing>("/api/payables/ageing"),
        api.get<{ items: Uninvoiced[] }>("/api/payables/uninvoiced"),
      ]);
      setAgeing(aged);
      setWaiting(un.items);
      setFailed("");
    } catch (e) {
      setFailed(errorText(e, "What is owed could not be worked out."));
    } finally {
      // Held briefly so the turn is visible. A spinner that stops on the same
      // frame it started reads as a button that did nothing.
      window.setTimeout(() => setSpinning(false), 450);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function show(invoiceId: number) {
    try {
      setOpen(await api.get<Invoice>(`/api/payables/invoices/${invoiceId}`));
    } catch (e) {
      toast.error(errorText(e, "That invoice could not be opened."));
    }
  }

  async function approve() {
    if (!open) return;
    const m = open.match;
    const ok = await confirm({
      title: "Approve for payment?",
      body: (
        <>
          {m && !m.matched
            ? <>This invoice did not match cleanly. Approving it accepts
                the difference of <b>{money(m.variance)}</b> as correct.</>
            : <>This brings the creditor to what the supplier billed.</>}
          {" "}Only the difference against the goods receipt is posted, so
          approving twice does nothing.
        </>
      ),
      confirmLabel: "Approve it",
    });
    if (!ok) return;
    try {
      const r = await api.post<Invoice & { message: string }>(
        `/api/payables/invoices/${open.id}/approve`, {});
      toast.ok(r.message);
      await show(open.id);
      await load();
    } catch (e) {
      toast.error(errorText(e, "That could not be approved."));
    }
  }

  if (failed) return <div className="alert error">{failed}</div>;

  const late = ageing
    ? Object.entries(ageing.totals)
        .filter(([band]) => band !== "Not yet due")
        .reduce((sum, [, value]) => sum + value, 0)
    : 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Supplier accounts</h1>
          <div className="sub">What was billed, what arrived, and what is still owed</div>
        </div>
        <button className="btn secondary" onClick={load}>
          <ArrowClockwise size={15} className={spinning ? "spin" : ""} />
          Refresh
        </button>
      </div>

      {!ageing ? <p className="muted">Working out what is owed…</p> : (
        <>
          <div className="wc-bands">
            <div className="wl-stat">
              <b>{money(ageing.total)}</b><span>owed to suppliers</span>
            </div>
            <div className={`wl-stat${late > 0.005 ? " wc-stale" : ""}`}>
              <b>{money(late)}</b><span>past its due date</span>
            </div>
            <div className={`wl-stat${ageing.queried > 0.005 ? " wc-abandoned" : ""}`}>
              <b>{money(ageing.queried)}</b><span>queried with the supplier</span>
            </div>
            <div className="wl-stat">
              <b>{money(waiting.reduce((s, w) => s + w.value, 0))}</b>
              <span>received, not yet invoiced</span>
            </div>
          </div>

          {/* The two are kept separately so they can disagree. A difference
              means something was posted straight to the control account with no
              invoice behind it, and that is the one error nothing else finds. */}
          {Math.abs(ageing.difference) > 0.005 && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />
              <span>
                The ledger says {money(ageing.control_balance)} is owed but these
                invoices come to {money(ageing.total)}, a difference of{" "}
                <b>{money(ageing.difference)}</b>. Something was posted to trade
                creditors without an invoice behind it.
              </span>
            </div>
          )}

          <div className="card">
            <div className="card-head">
              <h3>What is owed, by age</h3>
              <span className="muted small">
                Aged on the due date, not the invoice date
              </span>
            </div>
            {ageing.suppliers.length === 0 ? (
              <div className="empty">
                <b>Nothing is owed to any supplier.</b>
                <p>
                  Every invoice recorded has been paid and allocated. Goods
                  received that no invoice has arrived for are listed below;
                  those are a debt that has not been billed yet.
                </p>
              </div>
            ) : (
              <table className="dt">
                <thead>
                  <tr>
                    <th>Supplier</th>
                    {ageing.bands.map((b) => <th key={b} className="num">{b}</th>)}
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {ageing.suppliers.map((s) => (
                    <tr key={s.supplier_id}>
                      <td>
                        <b>{s.supplier}</b>
                        {s.oldest_days > 0 && (
                          <div className="muted small">
                            oldest is {s.oldest_days} day{s.oldest_days === 1 ? "" : "s"} past due
                          </div>
                        )}
                      </td>
                      {ageing.bands.map((b) => (
                        <td key={b} className="num">
                          {s.bands[b] ? money(s.bands[b]) : <span className="muted">—</span>}
                        </td>
                      ))}
                      <td className="num"><b>{money(s.total)}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {ageing.suppliers.length > 0 && (
            <div className="card">
              <div className="card-head"><h3>Open invoices</h3></div>
              <table className="dt">
                <thead>
                  <tr>
                    <th>Invoice</th><th>Supplier</th><th>Due</th>
                    <th className="num">Outstanding</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {ageing.suppliers.flatMap((s) =>
                    s.invoices.map((i) => (
                      <tr key={i.invoice_id}>
                        <td className="mono">{i.invoice_number}</td>
                        <td>{s.supplier}</td>
                        <td>
                          {fmtDate(i.due_date)}
                          {i.days_overdue > 0 && (
                            <div className="muted small">
                              {i.days_overdue} day{i.days_overdue === 1 ? "" : "s"} late
                            </div>
                          )}
                        </td>
                        <td className="num">{money(i.outstanding)}</td>
                        <td className="actions">
                          {i.status === "queried" && (
                            <span className="badge"><Question size={11} /> queried</span>
                          )}
                          <button className="btn small"
                                  onClick={() => show(i.invoice_id)}>
                            Open
                          </button>
                        </td>
                      </tr>
                    )))}
                </tbody>
              </table>
            </div>
          )}

          <div className="card">
            <div className="card-head">
              <h3>Received, but no invoice has arrived</h3>
            </div>
            {waiting.length === 0 ? (
              <div className="empty">
                <b>Every delivery has been billed.</b>
                <p>
                  Stock on the shelf with no bill behind it is a debt that has
                  not been recorded. Nothing is outstanding.
                </p>
              </div>
            ) : (
              <table className="dt">
                <thead>
                  <tr>
                    <th>Order</th><th>Supplier</th><th>Received</th>
                    <th className="num">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {waiting.map((w) => (
                    <tr key={w.order_id}>
                      <td className="mono">{w.order_number}</td>
                      <td>{w.supplier}</td>
                      <td>
                        {w.received_at ? fmtDate(w.received_at) : "—"}
                        {w.days !== null && w.days > 45 && (
                          <div className="muted small">{w.days} days ago</div>
                        )}
                      </td>
                      <td className="num">{money(w.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {open && (
        <div className="card">
          <div className="card-head">
            <h3><Receipt size={16} /> Invoice {open.invoice_number}</h3>
            <button className="btn secondary small" onClick={() => setOpen(null)}>
              Close
            </button>
          </div>

          {open.match && (
            <>
              <p className={open.match.matched ? "muted" : ""}>
                {open.match.matched
                  ? <><CheckCircle size={14} weight="fill" /> It matches what was received.</>
                  : <b>This invoice does not match what was received.</b>}
                {" "}{DEPTH_SAYS[open.match.depth]}
              </p>

              {open.match.problems.length > 0 && (
                <div className="alert warn">
                  <Warning size={16} weight="fill" />
                  <ul>
                    {open.match.problems.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                </div>
              )}

              <dl className="kv">
                <dt>Ordered</dt><dd>{money(open.match.ordered)}</dd>
                <dt>Received</dt><dd>{money(open.match.received)}</dd>
                <dt>Billed</dt><dd>{money(open.match.billed)}</dd>
                <dt>Difference</dt>
                <dd>
                  {open.match.variance >= 0
                    ? money(open.match.variance)
                    : `(${money(Math.abs(open.match.variance))})`}
                  <div className="muted small">
                    Approving posts this difference alone. The goods receipt
                    already raised the rest.
                  </div>
                </dd>
                <dt>Outstanding</dt><dd>{money(open.outstanding)}</dd>
              </dl>

              {open.match.lines.length > 0 && (
                <table className="dt sub">
                  <thead>
                    <tr>
                      <th>Line</th><th className="num">Billed</th>
                      <th className="num">Received</th><th className="num">At</th>
                      <th className="num">Ordered at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {open.match.lines.map((l, i) => (
                      <tr key={i}>
                        <td>
                          {l.description}
                          {l.issues.length > 0 && (
                            <div className="muted small">{l.issues.join(", ")}</div>
                          )}
                        </td>
                        <td className="num">{l.billed_quantity}</td>
                        <td className="num">{l.received_quantity}</td>
                        <td className="num">{money(l.billed_unit_cost)}</td>
                        <td className="num">{money(l.ordered_unit_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}

          {open.posted_reference ? (
            <p className="muted">
              Posted as <span className="mono">{open.posted_reference}</span>.
            </p>
          ) : (
            <BusyButton onClick={approve}>Approve for payment</BusyButton>
          )}
        </div>
      )}
    </>
  );
}
