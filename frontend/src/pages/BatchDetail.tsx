/** A batch: what it is, where it came from, and who received it.
 *
 *  The same trace the recall screen runs, reached from anywhere a batch number
 *  appears — an expiry sweep, a stock take, a sample register. A pharmacist who
 *  notices something odd about a batch should not have to go to the recall
 *  screen and search for it again to find out where it went.
 */
import { useCallback, useEffect, useState } from "react";
import { Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useToast } from "../components/Toast";
import { useAsk, useConfirm } from "../components/Confirm";
import BusyButton from "../components/BusyButton";
import { Link, useParams } from "react-router-dom";

interface Recipient {
  patient_id: number | null; patient: string; phone: string; quantity: number;
  sale_id: number | null; sale_number: string;
  prescription_id: number | null; rx_number: string; sold_at: string;
}
interface Data {
  id: number; batch_number: string; product_id: number; product: string;
  schedule: number; expiry_date: string | null; days_to_expiry: number | null;
  quantity_received: number; quantity_remaining: number;
  unit_cost: number; value_on_hand: number;
  received_at: string | null; reference: string;
  origin: { order_number: string; supplier: string; supplier_phone: string;
            received_on: string | null; certain: boolean };
  quantities: { received: number; on_shelf: number; traced_to_a_patient: number;
                sold_to_a_walk_in: number; unaccounted: number };
  recipients: Recipient[];
  warnings: string[];
}

export default function BatchDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.get<Data>(`/api/stock/batches/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That batch could not be opened.")));
  }, [id]);
  useEffect(() => { setD(null); load(); }, [load]);

  const expiry = d?.days_to_expiry;

  const toast = useToast();
  const confirm = useConfirm();
  /** Write off what is left of a batch — expired, damaged, recalled.
   *
   *  The endpoint has existed since batches did and only the stock screen
   *  reached it, so the page that shows an expiry date could not act on it.
   */
  async function writeOff() {
    if (!d) return;
    const ok = await confirm({
      title: `Write off ${d.quantity_remaining} of ${d.product}?`,
      body: (
        <>
          <p>
            Batch <b>{d.batch_number}</b>
            {d.expiry_date && <>, expiring {fmtDate(d.expiry_date)}</>}. Worth{" "}
            <b>{money(d.value_on_hand)}</b> at cost. The stock leaves the shelf
            and the loss is recorded against it.
          </p>
          <p className="muted">
            This cannot be undone. It is the right answer for expired or
            damaged stock and the wrong one for a miscount, which is a stock
            take.
          </p>
        </>
      ),
      confirmLabel: "Write it off",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.post(`/api/stock/batches/${d.id}/write-off`, {});
      toast.ok("Written off.");
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be written off."));
    }
  }
  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Inventory", to: "/stock" },
              { label: d?.batch_number || "This batch" }]}
      eyebrow="Batch"
      title={d?.batch_number || "Not recorded"}
      subtitle={d && <EntityLink kind="product" id={d.product_id}>{d.product}</EntityLink>}
      loading={!d && !error}
      error={error}
      actions={d && (
        <div className="page-actions">
          {d.quantity_remaining > 0 && (
            <BusyButton className="btn danger" onClick={writeOff}
                        busyLabel="Writing off…">
              Write off {d.quantity_remaining}
            </BusyButton>
          )}
          <Link className="btn secondary" to={`/products/${d.product_id}`}>
            The product
          </Link>
        </div>
      )}
      facts={d ? [
        { label: "On the shelf", value: d.quantity_remaining,
          hint: `of ${d.quantity_received} received` },
        { label: "Value on hand", value: money(d.value_on_hand) },
        { label: "Expires",
          value: d.expiry_date ? fmtDate(d.expiry_date) : "not recorded",
          hint: expiry === null || expiry === undefined ? undefined
            : expiry < 0 ? `${Math.abs(expiry)} days ago`
            : `in ${expiry} days` },
        { label: "Unit cost", value: money(d.unit_cost) },
      ] : undefined}
    >
      {d && (
        <>
          {d.warnings.length > 0 && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />
              <ul>{d.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="Where it came from">
              <dl className="kv">
                <dt>Medicine</dt>
                <dd>
                  <EntityLink kind="product" id={d.product_id}>{d.product}</EntityLink>
                  {d.schedule >= 3 && <span className="badge sched">S{d.schedule}</span>}
                </dd>
                <dt>Supplier</dt>
                <dd>
                  {d.origin.supplier || <span className="muted">not recorded</span>}
                  {d.origin.supplier_phone && (
                    <div className="muted small">{d.origin.supplier_phone}</div>
                  )}
                  {/* Said out loud: an inferred supplier is a guess, and the
                      pharmacy is about to telephone it. */}
                  {!d.origin.certain && d.origin.supplier && (
                    <div className="muted small">
                      Inferred from the most recent order for this medicine, not
                      recorded against the batch.
                    </div>
                  )}
                </dd>
                <dt>Order</dt><dd className="mono">{d.origin.order_number || "—"}</dd>
                <dt>Received</dt>
                <dd>{d.received_at ? fmtDateTime(d.received_at) : "not recorded"}</dd>
                <dt>Reference</dt><dd className="mono">{d.reference || "—"}</dd>
              </dl>
            </Panel>

            <Panel title="Where it went">
              <dl className="kv">
                <dt>Received</dt><dd className="num">{d.quantities.received}</dd>
                <dt>Still on the shelf</dt><dd className="num">{d.quantities.on_shelf}</dd>
                <dt>Traced to a patient</dt>
                <dd className="num">{d.quantities.traced_to_a_patient}</dd>
                <dt>Sold to a walk-in</dt>
                <dd className="num">{d.quantities.sold_to_a_walk_in}</dd>
                <dt>Unaccounted for</dt>
                <dd className="num">
                  {d.quantities.unaccounted}
                  {d.quantities.unaccounted > 0 && (
                    <div className="muted small">
                      left the shelf with no batch recorded against the sale
                    </div>
                  )}
                </dd>
              </dl>
            </Panel>
          </div>

          <Panel title="Who received it" count={d.recipients.length}
                 empty={d.quantities.on_shelf
                   ? "All of it is still on the shelf, which is the best possible answer."
                   : "It left the shelf without a batch recorded against the sale, so who received it cannot be established from here."}>
            <div className="dt-scroll" style={{ maxHeight: "50vh" }}>
              <table className="dt">
                <thead>
                  <tr><th>Patient</th><th className="num">Qty</th><th>When</th><th>Reference</th></tr>
                </thead>
                <tbody>
                  {d.recipients.map((r, i) => (
                    <tr key={`${r.sale_number}-${i}`}>
                      <td>
                        <EntityLink kind="patient" id={r.patient_id}>
                          <b>{r.patient}</b>
                        </EntityLink>
                        <div className="muted small">
                          {r.phone || "no telephone number on file"}
                        </div>
                      </td>
                      <td className="num">{r.quantity}</td>
                      <td>{fmtDate(r.sold_at)}</td>
                      <td className="mono small">
                        {r.rx_number
                          ? <EntityLink kind="prescription" id={r.prescription_id}>
                              {r.rx_number}
                            </EntityLink>
                          : <EntityLink kind="sale" id={r.sale_id}>
                              {r.sale_number}
                            </EntityLink>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
