/** A batch: what it is, where it came from, and who received it.
 *
 *  The same trace the recall screen runs, reached from anywhere a batch number
 *  appears: an expiry sweep, a stock take, a sample register. A pharmacist who
 *  notices something odd about a batch should not have to go to the recall
 *  screen and search for it again to find out where it went.
 */
import { useCallback, useEffect, useState } from "react";
import { Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { Figure, GhostRows } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useAsk, useConfirm } from "../components/Confirm";
import BusyButton from "../components/BusyButton";
import { Link, useParams } from "react-router-dom";
import { useScheduleCodes } from "../schedules";
import Th from "../components/Th";

interface Recipient {
  patient_id: number | null; patient: string; phone: string; quantity: number;
  sale_id: number | null; sale_number: string;
  prescription_id: number | null; rx_number: string; sold_at: string;
  /** Empty on a counter sale, which has no dispensing and no pharmacist. */
  pharmacist: string; pharmacist_id: number | null;
  dispensed_at: string | null;
}
/** One thing that happened to this lot. */
interface Event {
  at: string; what: string; why: string;
  quantity: number; balance_after: number;
  reference: string; notes: string;
  who: string; who_id: number | null;
  prescription_id: number | null;
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
  life: Event[];
  warnings: string[];
}

export default function BatchDetail() {
  const schedCode = useScheduleCodes();
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
      facts={[
        /* Every batch is read for the same four things, so the four labels are
           on screen before the trace is. Only the counts, the money and the
           date wait. */
        { label: "On the shelf",
          value: <Figure ready={!!d} w="4ch">{d?.quantity_remaining}</Figure>,
          hint: <>of <Figure ready={!!d} w="4ch">{d?.quantity_received}</Figure> received</> },
        { label: "Value on hand",
          value: <Figure ready={!!d} w="9ch">{d && money(d.value_on_hand)}</Figure> },
        { label: "Expires",
          value: <Figure ready={!!d} w="11ch">
            {d && (d.expiry_date ? fmtDate(d.expiry_date) : "Not recorded")}
          </Figure>,
          hint: <Figure ready={!!d} w="12ch">
            {d && (expiry === null || expiry === undefined ? "No expiry recorded"
              : expiry < 0 ? `${Math.abs(expiry)} days ago`
              : `in ${expiry} days`)}
          </Figure> },
        { label: "Unit cost",
          value: <Figure ready={!!d} w="9ch">{d && money(d.unit_cost)}</Figure> },
      ]}
    >
      {/* The gate that stood here kept all three card headings, the ten labels
          under them and the head of the recipients table off the screen until
          the trace came back. A batch always came from somewhere and always
          went somewhere; those words are written here and owe nothing to the
          server. Only the figures beside them wait. */}
      {d && d.warnings.length > 0 && (
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
              <Figure ready={!!d} w="20ch">
                {d && (
                  <>
                    <EntityLink kind="product" id={d.product_id}>{d.product}</EntityLink>
                    {d.schedule >= 3 && <span className="badge sched">{schedCode(d.schedule)}</span>}
                  </>
                )}
              </Figure>
            </dd>
            <dt>Supplier</dt>
            <dd>
              <Figure ready={!!d} w="18ch">
                {d && (
                  <>
                    {d.origin.supplier || <span className="muted">Not recorded</span>}
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
                  </>
                )}
              </Figure>
            </dd>
            <dt>Order</dt>
            <dd className="mono">
              <Figure ready={!!d} w="12ch">{d && (d.origin.order_number || "none")}</Figure>
            </dd>
            <dt>Received</dt>
            <dd>
              <Figure ready={!!d} w="16ch">
                {d && (d.received_at ? fmtDateTime(d.received_at) : "Not recorded")}
              </Figure>
            </dd>
            <dt>Reference</dt>
            <dd className="mono">
              <Figure ready={!!d} w="12ch">{d && (d.reference || "none")}</Figure>
            </dd>
          </dl>
        </Panel>

        <Panel title="Where it went">
          <dl className="kv">
            <dt>Received</dt>
            <dd className="num"><Figure ready={!!d} w="4ch">{d?.quantities.received}</Figure></dd>
            <dt>Still on the shelf</dt>
            <dd className="num"><Figure ready={!!d} w="4ch">{d?.quantities.on_shelf}</Figure></dd>
            <dt>Traced to a patient</dt>
            <dd className="num">
              <Figure ready={!!d} w="4ch">{d?.quantities.traced_to_a_patient}</Figure>
            </dd>
            <dt>Sold to a walk-in</dt>
            <dd className="num">
              <Figure ready={!!d} w="4ch">{d?.quantities.sold_to_a_walk_in}</Figure>
            </dd>
            <dt>Unaccounted for</dt>
            <dd className="num">
              <Figure ready={!!d} w="4ch">
                {d && (
                  <>
                    {d.quantities.unaccounted}
                    {d.quantities.unaccounted > 0 && (
                      <div className="muted small">
                        left the shelf with no batch recorded against the sale
                      </div>
                    )}
                  </>
                )}
              </Figure>
            </dd>
          </dl>
        </Panel>
      </div>

      {/* EVERYTHING THAT HAPPENED TO THIS LOT, IN ORDER.
          Until the batch was a column on a movement this could not be asked:
          the lot was named in the movement's notes as prose, so the only part
          of a batch's life anybody could query was the part that went out
          through a till. A quarantine, a release, a write-off, a transfer and
          a stock take left nothing to find, and those are the events a recall
          is most about. */}
      <Panel title="Everything that happened to it" count={d?.life?.length}
             empty={!d ? undefined
               : "Nothing is recorded against this lot by name. Stock received "
                 + "before lots were tracked leaves no trail, and neither does "
                 + "anything the shelf lost without naming the lot it came from."}>
        <div className="dt-scroll" style={{ maxHeight: "40vh" }}>
          <table className="dt">
            <thead>
              <tr><Th>When</Th><Th>What</Th><Th className="num">Change</Th>
                  <Th className="num">Left</Th><Th>Who</Th><Th>Reference</Th></tr>
            </thead>
            {!d ? (
              <GhostRows cols={6} rows={3}
                         widths={["60%", "45%", "30%", "30%", "55%", "55%"]} />
            ) : (
              <tbody>
                {(d.life ?? []).map((e, i) => (
                  <tr key={`${e.at}-${i}`}>
                    <td>{fmtDate(e.at)}</td>
                    <td>
                      <span className="badge muted">{e.what.replace(/_/g, " ")}</span>
                      {e.why && <span className="cell-note">{e.why.replace(/_/g, " ")}</span>}
                    </td>
                    <td className={`num ${e.quantity < 0 ? "mv-out" : "mv-in"}`}>
                      {e.quantity > 0 ? `+${e.quantity}` : e.quantity}
                    </td>
                    <td className="num">{e.balance_after}</td>
                    <td>
                      {e.who
                        ? <EntityLink kind="staff" id={e.who_id}>{e.who}</EntityLink>
                        : <span className="muted">Not recorded</span>}
                    </td>
                    <td className="mono small">
                      {e.prescription_id
                        ? <EntityLink kind="prescription" id={e.prescription_id}>
                            {e.reference}
                          </EntityLink>
                        : e.reference || <span className="muted">None</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            )}
          </table>
        </div>
      </Panel>

      <Panel title="Who received it" count={d?.recipients.length}
             /* Both of these sentences claim to know where the stock went,
                which is precisely what is still being fetched, so neither is
                offered until the trace is in hand. */
             empty={!d ? undefined : d.quantities.on_shelf
               ? "All of it is still on the shelf, which is the best possible answer."
               : "It left the shelf without a batch recorded against the sale, so who received it cannot be established from here."}>
        <div className="dt-scroll" style={{ maxHeight: "50vh" }}>
          <table className="dt">
            <thead>
              <tr><Th>Patient</Th><Th className="num">Qty</Th><Th>When</Th>
                  <Th>Handed over by</Th><Th>Reference</Th></tr>
            </thead>
            {!d ? (
              <GhostRows cols={5} rows={3} secondLine={[0]}
                         widths={["70%", "30%", "55%", "55%", "50%"]} />
            ) : (
              <tbody>
                {d.recipients.map((r, i) => (
                  <tr key={`${r.sale_number}-${i}`}>
                    <td>
                      <EntityLink kind="patient" id={r.patient_id}>
                        <b>{r.patient}</b>
                      </EntityLink>
                      <div className="muted small">
                        {r.phone || "No telephone number on file"}
                      </div>
                    </td>
                    <td className="num">{r.quantity}</td>
                    <td>{fmtDate(r.sold_at)}</td>
                    {/* A recall asks two things about a person: who has the
                        medicine, and who gave it to them. The second was
                        reachable through the dispensing all along and was
                        never asked for. A counter sale has no pharmacist and
                        says so rather than looking like a gap. */}
                    <td>
                      {r.pharmacist
                        ? <EntityLink kind="staff" id={r.pharmacist_id}>
                            {r.pharmacist}
                          </EntityLink>
                        : <span className="muted">Sold at the counter</span>}
                    </td>
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
            )}
          </table>
        </div>
      </Panel>
    </RecordPage>
  );
}
