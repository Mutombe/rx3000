/** A recall: from a batch number to the people holding it.
 *
 *  A manufacturer withdraws a batch and the pharmacy has to answer two questions
 *  the same afternoon. Who has it, so they can be telephoned — that is the one
 *  with a clock on it. And where did it come from and what is left, so the rest
 *  can be quarantined and returned.
 *
 *  Every fact was already in the database and nothing joined them up, so a recall
 *  was answered from memory and a shelf.
 *
 *  The screen leads with what to do first — quarantine what is still here, then
 *  telephone — because the list of names is long and the thing that stops another
 *  person receiving it takes ten seconds.
 */
import { useCallback, useEffect, useState } from "react";
import { MagnifyingGlass, Phone, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money, prefetchRoute } from "../api";
import { useToast } from "../components/Toast";
import RowLink, { RowActions } from "../components/RowLink";
import { EntityLink } from "../components/Filters";
import { TableSkeleton } from "../components/Skeleton";

interface Hit {
  batch_id: number; batch_number: string; product: string;
  expiry_date: string | null; quantity_received: number; quantity_remaining: number;
}
interface Recipient {
  patient_id: number; patient: string; phone: string; quantity: number;
  sale_id: number | null; sale_number: string;
  prescription_id: number | null; rx_number: string; sold_at: string;
}
interface Trace {
  batch: { batch_id: number; batch_number: string; product: string;
           schedule: number | null; expiry_date: string | null; unit_cost: number };
  origin: { order_number: string; ordered_on: string | null; received_on: string | null;
            supplier: string; supplier_phone: string; supplier_email: string; certain: boolean };
  quantities: { received: number; on_shelf: number; traced_to_a_patient: number;
                sold_to_a_walk_in: number; unaccounted: number };
  recipients: Recipient[];
  to_call: number;
  no_phone: number;
  value_on_shelf: number;
  value_dispensed: number;
  warnings: string[];
}

export default function Recall() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const search = useCallback(async (term: string) => {
    if (!term.trim()) { setHits([]); return; }
    setBusy(true);
    try {
      const r = await api.get<{ items: Hit[] }>(
        `/api/recall/batches?q=${encodeURIComponent(term)}`);
      setHits(r.items);
    } catch (e) {
      toast.error(errorText(e, "The search failed."));
    } finally { setBusy(false); }
  }, [toast]);

  useEffect(() => {
    const t = window.setTimeout(() => search(q), 350);
    return () => window.clearTimeout(t);
  }, [q, search]);

  async function open(hit: Hit) {
    try {
      setTrace(await api.get<Trace>(`/api/recall/batches/${hit.batch_id}`));
    } catch (e) {
      toast.error(errorText(e, "That batch could not be traced."));
    }
  }

  function copyCallList() {
    if (!trace) return;
    const lines = trace.recipients
      .filter((r) => r.phone)
      .map((r) => `${r.patient}\t${r.phone}\t${r.quantity}\t${r.sale_number}`);
    navigator.clipboard?.writeText(
      `Recall ${trace.batch.batch_number} — ${trace.batch.product}\n` + lines.join("\n"));
    toast.ok(`${lines.length} number(s) copied.`);
  }

  const qty = trace?.quantities;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Recall</h1>
          <div className="sub">
            Trace a batch to who received it, and to where it came from
          </div>
        </div>
      </div>

      <div className="card">
        <label className="field">
          Batch number or medicine
          <div className="rc-search">
            <MagnifyingGlass size={15} />
            <input autoFocus value={q} placeholder="e.g. A43566, or Amoxicillin"
                   onChange={(e) => setQ(e.target.value)} />
          </div>
          <span className="field-hint">
            Matched loosely: a recall notice gives the number in the
            manufacturer's format and whoever booked the delivery in typed what
            was on the box.
          </span>
        </label>

        {/* A sentence where a table is about to be makes the page jump when
            the answer lands. The ghost holds the shape. */}
        {busy && (
          <TableSkeleton cols={5} rows={4}
            widths={["14ch", "22ch", "12ch", "10ch", "12ch"]} />
        )}
        {!busy && q.trim() && hits.length === 0 && (
          <div className="empty">
            <b>No batch matches that.</b>
            <p>
              Try the medicine's name instead of the number. A batch received
              before this system was in use will not be here, and stock with no
              batch recorded against it cannot be traced at all.
            </p>
          </div>
        )}

        {hits.length > 0 && (
          <table className="dt">
            <thead>
              <tr>
                <th>Batch</th><th>Medicine</th><th>Expiry</th>
                <th className="num">On shelf</th><th className="actions" />
              </tr>
            </thead>
            <tbody>
              {hits.map((h) => (
                <RowLink key={h.batch_id} to={`/batches/${h.batch_id}`}
                         prefetch={prefetchRoute}>
                  <td className="mono">
                    <EntityLink kind="batch" id={h.batch_id}>
                      {h.batch_number || "—"}
                    </EntityLink>
                  </td>
                  <td>{h.product}</td>
                  <td>{h.expiry_date ? fmtDate(h.expiry_date) : "—"}</td>
                  <td className="num">
                    {h.quantity_remaining} <span className="muted">of {h.quantity_received}</span>
                  </td>
                  <RowActions>
                    <button className="btn small" onClick={() => open(h)}>Trace it</button>
                  </RowActions>
                </RowLink>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {trace && (
        <>
          {/* What to do first, before the list of names. Quarantining what is
              still on the shelf takes ten seconds and is the only step that
              stops another person receiving it. */}
          {trace.warnings.length > 0 && (
            <div className="alert warn recall-do">
              <Warning size={16} weight="fill" />
              <ul>
                {trace.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          <div className="wc-bands">
            <div className="wl-stat"><b>{qty?.received}</b><span>received</span></div>
            <div className="wl-stat wc-abandoned"><b>{qty?.on_shelf}</b><span>still on the shelf</span></div>
            <div className="wl-stat"><b>{qty?.traced_to_a_patient}</b><span>traced to a patient</span></div>
            <div className="wl-stat"><b>{qty?.sold_to_a_walk_in}</b><span>sold to a walk-in</span></div>
            <div className={`wl-stat${qty?.unaccounted ? " wc-stale" : ""}`}>
              <b>{qty?.unaccounted}</b><span>unaccounted for</span>
            </div>
          </div>

          <div className="grid cols-2">
            <div className="card">
              <div className="card-head"><h3>Where it came from</h3></div>
              <dl className="kv">
                <dt>Medicine</dt>
                <dd>
                  {trace.batch.product}
                  {(trace.batch.schedule ?? 0) >= 3 && (
                    <span className="badge sched">S{trace.batch.schedule}</span>
                  )}
                </dd>
                <dt>Batch</dt><dd className="mono">{trace.batch.batch_number || "not recorded"}</dd>
                <dt>Expiry</dt>
                <dd>{trace.batch.expiry_date ? fmtDate(trace.batch.expiry_date) : "not recorded"}</dd>
                <dt>Supplier</dt>
                <dd>
                  {trace.origin.supplier || <span className="muted">not recorded</span>}
                  {trace.origin.supplier_phone && (
                    <div className="muted small">{trace.origin.supplier_phone}</div>
                  )}
                  {/* Said out loud. When the supplier was inferred rather than
                      recorded, the pharmacy is about to telephone a guess. */}
                  {!trace.origin.certain && trace.origin.supplier && (
                    <div className="muted small">
                      Inferred from the most recent order for this medicine, not
                      recorded against the batch. Confirm before returning stock.
                    </div>
                  )}
                </dd>
                <dt>Order</dt>
                <dd className="mono">{trace.origin.order_number || "not recorded"}</dd>
                <dt>Received</dt>
                <dd>{trace.origin.received_on ? fmtDateTime(trace.origin.received_on) : "not recorded"}</dd>
                <dt>Value on the shelf</dt><dd>{money(trace.value_on_shelf)}</dd>
                <dt>Value dispensed</dt>
                <dd>
                  {money(trace.value_dispensed)}
                  {/* The write-off is a decision, not a consequence. What a
                      recall costs depends on whether the manufacturer credits
                      it, and posting before that is known turns one uncertainty
                      into a wrong number in the ledger. */}
                  <div className="muted small">
                    Nothing is posted to the ledger from here. What a recall costs
                    depends on whether the supplier credits it.
                  </div>
                </dd>
              </dl>
            </div>

            <div className="card">
              <div className="card-head">
                <h3>Who to telephone</h3>
                {trace.to_call > 0 && (
                  <button className="btn secondary small" onClick={copyCallList}>
                    Copy the call list
                  </button>
                )}
              </div>
              {trace.recipients.length === 0 ? (
                <div className="empty">
                  <b>Nobody can be traced to this batch.</b>
                  <p>
                    {qty?.on_shelf
                      ? "All of it is still on the shelf, which is the best possible answer."
                      : "It left the shelf without a batch recorded against the sale, so who received it cannot be established from here."}
                  </p>
                </div>
              ) : (
                <>
                  <p className="muted">
                    {trace.to_call} patient{trace.to_call === 1 ? "" : "s"} to telephone
                    {trace.no_phone > 0 && `, and ${trace.no_phone} with no number on file`}.
                  </p>
                  <div className="dt-scroll" style={{ maxHeight: "46vh" }}>
                    <table className="dt">
                      <thead>
                        <tr>
                          <th>Patient</th><th className="num">Qty</th><th>When</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trace.recipients.map((r, i) => (
                          <tr key={`${r.sale_number}-${i}`}>
                            <td>
                              <EntityLink kind="patient" id={r.patient_id}>
                                <b>{r.patient}</b>
                              </EntityLink>
                              <div className="muted small">
                                {r.phone
                                  ? <><Phone size={11} /> {r.phone}</>
                                  : "no telephone number on file"}
                              </div>
                            </td>
                            <td className="num">{r.quantity}</td>
                            <td>
                              {fmtDate(r.sold_at)}
                              <div className="muted small mono">
                                {r.rx_number
                                  ? <EntityLink kind="prescription" id={r.prescription_id}>
                                      {r.rx_number}
                                    </EntityLink>
                                  : <EntityLink kind="sale" id={r.sale_id}>
                                      {r.sale_number}
                                    </EntityLink>}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
