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
import { useToast } from "../components/Toast";
import { useNavigate, useParams } from "react-router-dom";

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
      toast.error(errorText(e, "That could not be recorded."));
    }
  }

  async function cancel() {
    if (!owed) return;
    try {
      await api.post(`/api/to-follows/${owed.id}/cancel`, { reason: reason.trim() });
      toast.ok(`${owed.reference} cancelled.`);
      setCancelling(false);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be cancelled."));
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
        <EntityLink kind="patient" id={owed.patient_id}>{owed.patient_name}</EntityLink>
      )}
      loading={!owed && !error}
      error={error}
      facts={owed ? [
        { label: "Still owed", value: owed.quantity_outstanding,
          hint: `of ${owed.quantity_owed}` },
        { label: "In stock now", value: owed.quantity_on_hand,
          hint: owed.can_settle_now ? "enough to finish it"
                : owed.can_settle_partially ? "enough for some of it"
                : "not enough" },
        { label: "Promised", value: owed.promised_for ? fmtDate(owed.promised_for) : "no date",
          hint: owed.overdue ? "past the date" : undefined },
        { label: "Status", value: owed.status },
      ] : undefined}
    >
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
              Cancelled{owed.cancelled_reason ? ` — ${owed.cancelled_reason}` : ""}.
              Nothing further is owed.
            </div>
          )}
          {owed.status === "settled" && (
            <div className="alert ok">
              Handed over in full{owed.settled_at ? ` on ${fmtDate(owed.settled_at)}` : ""}.
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="What is owed">
              <dl className="kv">
                <dt>Reference</dt><dd className="mono">{owed.reference}</dd>
                <dt>Medicine</dt>
                <dd>
                  <EntityLink kind="product" id={owed.product_id}>
                    {owed.product_name}
                  </EntityLink>
                </dd>
                <dt>Owed</dt><dd>{owed.quantity_owed}</dd>
                <dt>Given so far</dt><dd>{owed.quantity_settled}</dd>
                <dt>Still owed</dt><dd><b>{owed.quantity_outstanding}</b></dd>
                <dt>From sale</dt>
                <dd className="mono">
                  <EntityLink kind="sale" id={owed.sale_id}>
                    {owed.sale_id ? `#${owed.sale_id}` : "—"}
                  </EntityLink>
                </dd>
                <dt>Recorded</dt>
                <dd>
                  {fmtDateTime(owed.created_at)}
                  {owed.created_by && <div className="muted small">{owed.created_by}</div>}
                </dd>
              </dl>
              {owed.notes && <p className="prose">{owed.notes}</p>}
            </Panel>

            <Panel title="What happens next">
              {owed.status !== "outstanding" ? (
                <div className="empty">
                  <p>Nothing — this one is {owed.status}.</p>
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
                      ? `There is enough on the shelf to finish this — ${owed.quantity_outstanding} to hand over.`
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
                      Cancel — not coming
                    </button>
                  </p>
                </>
              )}
            </Panel>
          </div>

          {owed.patient_phone && (
            <p className="muted"><Phone size={13} /> {owed.patient_phone}</p>
          )}
        </>
      )}
    </RecordPage>
  );
}
