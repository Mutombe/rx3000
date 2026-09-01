/** One bag on the will-call shelf.
 *
 *  The shelf listed bags and opened none of them, so the four questions asked
 *  at the counter — is this the right bag, has it been paid for, who may take
 *  it, how long has it been here — were answered by reading a row and guessing.
 *
 *  Handing it over is the action, so it is the button. Everything else on the
 *  page exists to make that decision safely: what is owed, whether an identity
 *  document is needed, and whether anything else for the same patient is still
 *  on the shelf behind it.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowUUpLeft, Phone, Printer, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDateTime, money } from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import LabelSheet from "../components/LabelSheet";
import RecordPage, { Panel } from "../components/RecordPage";
import { useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";
import { useNavigate, useParams } from "react-router-dom";

interface Alongside {
  dispensing_id: number; product: string; quantity: number; dispensed_at: string;
}
interface Bag {
  dispensing_id: number; quantity: number; schedule: number; is_repeat: boolean;
  dispensed_at: string; dispensed_by_id: number | null; dispensed_by: string;
  pharmacist_initial: string;
  collected_at: string | null; collected_name: string;
  days_waiting: number; band: string; action: string; needs_id: boolean;
  product_id: number | null; product: string; directions: string;
  prescription_id: number | null; rx_number: string;
  prescriber_id: number | null; prescriber: string;
  patient: { id: number | null; name: string; phone: string };
  sale_id: number | null; sale_number: string; sale_status: string;
  sale_total: number; outstanding: number;
  claim_id: number | null; scheme_pays: number;
  alongside: Alongside[];
}

const TONE: Record<string, string> = {
  fresh: "", waiting: "warn", stale: "warn", abandoned: "bad",
};

export default function WillCallBag() {
  const { id } = useParams();
  const [bag, setBag] = useState<Bag | null>(null);
  const [error, setError] = useState("");
  const [takenBy, setTakenBy] = useState("");
  const [idSeen, setIdSeen] = useState("");
  const [labels, setLabels] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();
  const navigate = useNavigate();

  const load = useCallback(() => {
    api.get<Bag>(`/api/dispensing/will-call/${id}`)
      .then(setBag)
      .catch((e) => setError(errorText(e, "That bag could not be opened.")));
  }, [id]);
  useEffect(() => { setBag(null); load(); }, [load]);

  async function handOver() {
    if (!bag) return;
    try {
      await api.post(`/api/dispensing/will-call/${bag.dispensing_id}/collect`, {
        taken_by: takenBy.trim(), id_seen: idSeen.trim(),
      });
      toast.ok(`Handed to ${takenBy.trim() || bag.patient.name}.`);
      navigate("/will-call");
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded."));
    }
  }

  const owed = bag?.outstanding ?? 0;

  /** Put a bag back on the shelf.
   *
   *  A collection marked against the wrong bag is an ordinary counter mistake —
   *  two people at the till, one queue, and until now it was permanent. The
   *  bag showed as handed over, the worklist stopped counting it, and the
   *  medicine sat on the shelf with nothing saying it was still there. The
   *  endpoint to undo it has existed since will-call was written and no screen
   *  ever offered it.
   */
  async function uncollect() {
    if (!bag) return;
    const ok = await confirm({
      title: "Put this bag back on the shelf?",
      body: <>
        It will show as waiting again, from the date it was dispensed rather
        than today, so the queue does not lose track of how long it has been
        there. Use this when a collection was recorded against the wrong bag —
        not when medicine has been returned, which is a reversal.
      </>,
      confirmLabel: "Put it back",
    });
    if (!ok) return;
    try {
      await api.post(`/api/dispensing/will-call/${bag.dispensing_id}/uncollect`, {});
      toast.ok("Back on the shelf, and waiting again.");
      await load();
    } catch (e) {
      toast.error(errorText(e, "That collection could not be undone."));
    }
  }

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Will call", to: "/will-call" },
              { label: bag?.product || "This bag" }]}
      eyebrow="On the shelf"
      title={bag?.product ?? ""}
      subtitle={bag && (
        <EntityLink kind="patient" id={bag.patient.id}>{bag.patient.name}</EntityLink>
      )}
      loading={!bag && !error}
      error={error}
      facts={bag ? [
        { label: "Waiting", value: `${bag.days_waiting} day${bag.days_waiting === 1 ? "" : "s"}`,
          hint: bag.band },
        { label: "Quantity", value: bag.quantity },
        { label: "To pay", value: owed > 0.005 ? money(owed) : "nothing",
          hint: owed > 0.005 ? "collect at the till" : undefined },
        { label: "Dispensed", value: fmtDateTime(bag.dispensed_at) },
      ] : undefined}
      actions={bag && !bag.collected_at
        ? <button className="btn secondary" onClick={() => setLabels(true)}>
            <Printer size={15} /> Labels
          </button>
        : undefined}
    >
      {bag && (
        <>
          {bag.collected_at ? (
            <div className="alert ok">
              <span>
                Handed over {fmtDateTime(bag.collected_at)}
                {bag.collected_name ? ` to ${bag.collected_name}` : ""}.
              </span>
              <button className="btn small secondary" onClick={uncollect}>
                <ArrowUUpLeft size={14} /> Not collected after all
              </button>
            </div>
          ) : (
            <>
              {/* What to do about it, in the band's own words. */}
              <div className={`alert ${TONE[bag.band] || ""}`}>
                <b>{bag.band}</b> — {bag.action}
              </div>

              {owed > 0.005 && (
                <div className="alert warn">
                  <Warning size={16} weight="fill" />
                  <span>
                    <b>{money(owed)} has not been paid.</b> Take it at the till
                    before this goes out, or the medicine leaves and the money
                    stays a question nobody was asked.{" "}
                    <EntityLink kind="sale" id={bag.sale_id}>
                      {bag.sale_number}
                    </EntityLink>
                  </span>
                </div>
              )}
            </>
          )}

          <div className="grid cols-2">
            <Panel title="What is in the bag">
              <dl className="kv">
                <dt>Medicine</dt>
                <dd>
                  <EntityLink kind="product" id={bag.product_id}>{bag.product}</EntityLink>
                  {bag.schedule >= 3 && <span className="badge sched">S{bag.schedule}</span>}
                </dd>
                <dt>Quantity</dt><dd>{bag.quantity}</dd>
                <dt>Directions</dt><dd>{bag.directions || "—"}</dd>
                <dt>Script</dt>
                <dd className="mono">
                  <EntityLink kind="prescription" id={bag.prescription_id}>
                    {bag.rx_number || "—"}
                  </EntityLink>
                  {bag.is_repeat && <div className="muted small">repeat</div>}
                </dd>
                <dt>Prescriber</dt>
                <dd>
                  <EntityLink kind="prescriber" id={bag.prescriber_id}>
                    {bag.prescriber || "not recorded"}
                  </EntityLink>
                </dd>
                <dt>Checked by</dt>
                <dd>
                  <EntityLink kind="staff" id={bag.dispensed_by_id}>
                    {bag.dispensed_by || bag.pharmacist_initial || "—"}
                  </EntityLink>
                </dd>
              </dl>
            </Panel>

            {!bag.collected_at ? (
              <Panel title="Hand it over">
                <p className="muted">
                  {bag.needs_id
                    ? "A Schedule 5 or 6 item cannot go to whoever turns up. Record who took it and the identity document you saw."
                    : "Often it is not the patient — a relative, a driver, a neighbour going that way. Recording who took it is the answer to “who had it” later."}
                </p>
                <label className="field">
                  Who is taking it?
                  <input
                    value={takenBy} onChange={(e) => setTakenBy(e.target.value)}
                    placeholder={bag.patient.name}
                    autoFocus
                  />
                </label>
                {bag.needs_id && (
                  <label className="field">
                    Identity document seen
                    <input
                      value={idSeen} onChange={(e) => setIdSeen(e.target.value)}
                      placeholder="e.g. 63-1234567-K-42"
                    />
                  </label>
                )}
                <BusyButton
                  onClick={handOver}
                  disabled={bag.needs_id && !takenBy.trim()}
                >
                  Hand over
                </BusyButton>
                {bag.needs_id && !takenBy.trim() && (
                  <p className="muted small">
                    The register has to answer &ldquo;who had it and when&rdquo;.
                  </p>
                )}
              </Panel>
            ) : (
              <Panel title="Who took it">
                <dl className="kv">
                  <dt>Collected</dt><dd>{fmtDateTime(bag.collected_at)}</dd>
                  <dt>Taken by</dt><dd>{bag.collected_name || "not recorded"}</dd>
                </dl>
              </Panel>
            )}
          </div>

          <Panel title="Also waiting for this patient" count={bag.alongside.length}
                 empty="Nothing else of theirs is on the shelf.">
            <table className="dt">
              <thead>
                <tr><th>Medicine</th><th className="num">Qty</th><th>Dispensed</th></tr>
              </thead>
              <tbody>
                {bag.alongside.map((a) => (
                  <tr key={a.dispensing_id}>
                    <td>
                      <EntityLink to={`/will-call/${a.dispensing_id}`}>
                        {a.product}
                      </EntityLink>
                    </td>
                    <td className="num">{a.quantity}</td>
                    <td>{fmtDateTime(a.dispensed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          {bag.patient.phone && (
            <p className="muted">
              <Phone size={13} /> {bag.patient.phone}
            </p>
          )}
        </>
      )}

      {labels && bag?.prescription_id && (
        <LabelSheet rxId={bag.prescription_id} onClose={() => setLabels(false)} />
      )}
    </RecordPage>
  );
}
