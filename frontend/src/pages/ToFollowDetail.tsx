/** One thing the pharmacy owes a patient.
 *
 *  A to-follow is the short-supply case: you had thirty of the sixty tablets on
 *  the script, the patient was billed for sixty and took thirty, and the shop
 *  owes them the rest. It is the opposite direction to money owed — there the
 *  patient owes the pharmacy; here the pharmacy owes the patient medicine.
 *
 *  Two things can happen to it and both are on this page. Either the stock
 *  arrives and the rest is handed over, or it is not coming and the obligation
 *  is cancelled, which is a real decision with a reason, not a tidy-up.
 */
import { useCallback, useEffect, useState } from "react";
import { Phone, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime } from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { Figure } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useNavigate, useParams } from "react-router-dom";
import Person from "../components/Person";

interface Owed {
  id: number; reference: string; status: string;
  patient_id: number | null; patient_name: string; patient_phone: string;
  product_id: number | null; product_name: string;
  prescription_item_id: number | null; sale_id: number | null;
  quantity_owed: number; quantity_settled: number; quantity_outstanding: number;
  quantity_on_hand: number;
  can_settle_now: boolean; can_settle_partially: boolean;
  promised_for: string | null; overdue: boolean;
  notes: string; cancelled_reason: string;
  created_at: string; created_by: string; settled_at: string | null;
}

export default function ToFollowDetail() {
  const { id } = useParams();
  const [owed, setOwed] = useState<Owed | null>(null);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const toast = useToast();
  const navigate = useNavigate();

  const load = useCallback(() => {
    api.get<Owed>(`/api/to-follows/${id}`)
      .then(setOwed)
      .catch((e) => setError(errorText(e, "That could not be opened.")));
  }, [id]);
  useEffect(() => { setOwed(null); load(); }, [load]);

  async function give(quantity?: number) {
    if (!owed) return;
    try {
      await api.post(`/api/to-follows/${owed.id}/settle`, {
        quantity: quantity ?? owed.quantity_outstanding,
      });
      toast.ok(`${quantity ?? owed.quantity_outstanding} handed to ${owed.patient_name}.`);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded. Nothing was saved."));
    }
  }

  async function cancel() {
    if (!owed) return;
    try {
      // Closed before the write, not after it. A record being created
      // or edited costs a click if it fails, and the list is what
      // confirms it either way.
      setCancelling(false);
      await api.post(`/api/to-follows/${owed.id}/cancel`, { reason: reason.trim() });
      toast.ok(`${owed.reference} cancelled.`);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be cancelled. Nothing was saved."));
    }
  }

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "To follows", to: "/to-follows" },
              { label: owed?.reference ?? "This one" }]}
      eyebrow="Owed to a patient"
      title={owed?.product_name ?? ""}
      subtitle={owed && (
        <EntityLink kind="patient" id={owed.patient_id}><Person name={owed.patient_name} /></EntityLink>
      )}
      loading={!owed && !error}
      error={error}
      facts={[
        /* What is owed, what is on the shelf, when it was promised and where it
           stands: true of every to-follow before this one is read, so the words
           go up at once and only the counts and the date pulse. */
        { label: "Still owed",
          value: <Figure ready={!!owed} w="4ch">{owed?.quantity_outstanding}</Figure>,
          hint: <>of <Figure ready={!!owed} w="4ch">{owed?.quantity_owed}</Figure></> },
        { label: "In stock now",
          value: <Figure ready={!!owed} w="5ch">{owed?.quantity_on_hand}</Figure>,
          hint: <Figure ready={!!owed} w="18ch">
            {owed && (owed.can_settle_now ? "enough to finish it"
              : owed.can_settle_partially ? "enough for some of it"
              : "Not enough")}
          </Figure> },
        { label: "Promised",
          value: <Figure ready={!!owed} w="11ch">
            {owed && (owed.promised_for ? fmtDate(owed.promised_for) : "No date")}
          </Figure>,
          hint: owed?.overdue ? "past the date" : undefined },
        { label: "Status",
          value: <Figure ready={!!owed} w="12ch">{owed?.status}</Figure> },
      ]}
    >
      {/* The two panel headings and the seven field labels say what a to-follow
          is, which is the same before the answer comes back as after it. They
          used to sit behind the fetch with everything else, so the page opened
          blank and then arrived whole. The three status alerts stay behind it,
          because each of them is a claim about this particular obligation and
          none can be made before the record has spoken. */}
      {owed && (
        <>
          {owed.status === "outstanding" && owed.overdue && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />
              <span>
                This was promised for {fmtDate(owed.promised_for!)} and has not
                been handed over. The patient is short of their medicine and is
                waiting on the shop.
              </span>
            </div>
          )}
          {owed.status === "cancelled" && (
            <div className="alert">
              Cancelled{owed.cancelled_reason ? `: ${owed.cancelled_reason}` : ""}.
              Nothing further is owed.
            </div>
          )}
          {owed.status === "settled" && (
            <div className="alert ok">
              Handed over in full{owed.settled_at ? ` on ${fmtDate(owed.settled_at)}` : ""}.
            </div>
          )}
        </>
      )}

      <div className="grid cols-2">
        <Panel title="What is owed">
          <dl className="kv">
            <dt>Reference</dt>
            <dd className="mono">
              <Figure ready={!!owed} w="12ch">{owed?.reference}</Figure>
            </dd>
            <dt>Medicine</dt>
            <dd>
              <Figure ready={!!owed} w="20ch">
                {owed && (
                  <EntityLink kind="product" id={owed.product_id}>
                    {owed.product_name}
                  </EntityLink>
                )}
              </Figure>
            </dd>
            <dt>Owed</dt>
            <dd><Figure ready={!!owed} w="3ch">{owed?.quantity_owed}</Figure></dd>
            <dt>Given so far</dt>
            <dd><Figure ready={!!owed} w="3ch">{owed?.quantity_settled}</Figure></dd>
            <dt>Still owed</dt>
            <dd>
              <Figure ready={!!owed} w="3ch">
                {owed && <b>{owed.quantity_outstanding}</b>}
              </Figure>
            </dd>
            <dt>From sale</dt>
            <dd className="mono">
              <Figure ready={!!owed} w="8ch">
                {owed && (
                  <EntityLink kind="sale" id={owed.sale_id}>
                    {owed.sale_id ? `#${owed.sale_id}` : "none"}
                  </EntityLink>
                )}
              </Figure>
            </dd>
            <dt>Recorded</dt>
            <dd>
              <Figure ready={!!owed} w="16ch">
                {owed && (
                  <>
                    {fmtDateTime(owed.created_at)}
                    {owed.created_by && <div className="muted small">{owed.created_by}</div>}
                  </>
                )}
              </Figure>
            </dd>
          </dl>
          {owed?.notes && <p className="prose">{owed.notes}</p>}
        </Panel>

        <Panel title="What happens next">
          {/* Nothing here can be offered, or refused, until the record says
              what state it is in, so the whole answer pulses as one. */}
          <Figure ready={!!owed} w="36ch">
            {owed && (
              owed.status !== "outstanding" ? (
                <div className="empty">
                  <p>Nothing. This one is {owed.status}.</p>
                </div>
              ) : cancelling ? (
                <>
                  <p className="muted">
                    Cancelling says the pharmacy is not going to supply the rest.
                    The patient was billed for it, so whoever cancels should say
                    why: a refund or a conversation usually follows.
                  </p>
                  <label className="field">
                    Why is it not coming?
                    <input
                      value={reason} onChange={(e) => setReason(e.target.value)}
                      placeholder="e.g. discontinued by the manufacturer"
                      autoFocus
                    />
                  </label>
                  <div className="modal-actions">
                    <button className="btn ghost" onClick={() => setCancelling(false)}>
                      Keep it
                    </button>
                    <BusyButton disabled={!reason.trim()} onClick={cancel}>
                      Cancel it
                    </BusyButton>
                  </div>
                </>
              ) : (
                <>
                  <p className="muted">
                    {owed.can_settle_now
                      ? `There is enough on the shelf to finish this: ${owed.quantity_outstanding} to hand over.`
                      : owed.can_settle_partially
                        ? `${owed.quantity_on_hand} came in, which is not all of it. Giving what arrived leaves ${owed.quantity_outstanding - owed.quantity_on_hand} still owed.`
                        : "Nothing on the shelf yet. This stays here until stock arrives."}
                  </p>
                  {owed.can_settle_now && (
                    <BusyButton onClick={() => give()}>
                      Give the rest ({owed.quantity_outstanding})
                    </BusyButton>
                  )}
                  {!owed.can_settle_now && owed.can_settle_partially && (
                    <BusyButton onClick={() => give(owed.quantity_on_hand)}>
                      Give what came in ({owed.quantity_on_hand})
                    </BusyButton>
                  )}
                  <p style={{ marginTop: 12 }}>
                    <button className="btn ghost small" onClick={() => setCancelling(true)}>
                      Cancel. Not coming
                    </button>
                  </p>
                </>
              )
            )}
          </Figure>
        </Panel>
      </div>

      {owed?.patient_phone && (
        <p className="muted"><Phone size={13} /> {owed.patient_phone}</p>
      )}
    </RecordPage>
  );
}
