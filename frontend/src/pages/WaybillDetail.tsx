/** One delivery, end to end.
 *
 *  The deliveries board answers "what is out today". This answers the question
 *  asked afterwards, and usually under pressure: a patient says nothing
 *  arrived, or a scheme asks for proof that a controlled medicine reached the
 *  person it was dispensed to.
 *
 *  A waybill is a chain of custody, so it is shown as one — raised, dispatched,
 *  delivered — with who did each and when. The board linked its rows to the
 *  patient or the sale, which are the two records that do *not* hold any of
 *  that. `GET /api/waybills/{id}` has returned all of it since waybills were
 *  written and nothing asked for it.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Phone, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDateTime } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import BusyButton from "../components/BusyButton";
import { useAsk } from "../components/Confirm";
import { useToast } from "../components/Toast";

interface Waybill {
  id: number; waybill_number: string; status: string;
  sale_id: number | null; patient_id: number | null;
  recipient: string; address: string; phone: string; instructions: string;
  driver: string; driver_profile_id: number | null; driver_phone: string;
  received_by: string; failure_reason: string;
  // The money side, added when deliveries grew one. A waybill that does not
  // say what it is collecting is a parcel with an unknown value attached.
  delivery_fee: number; cod_amount: number; cod_collected: number;
  cod_outstanding: number; cod_settled_at: string | null;
  requires_id_check: boolean; id_number_seen: string;
  created_at: string; dispatched_at: string | null; delivered_at: string | null;
  created_by: string;
}

const TONE: Record<string, string> = {
  pending: "warn", out: "", delivered: "ok", failed: "bad",
};

/** One link in the chain: what happened, when, and who.
 *
 *  A step that has not happened is shown greyed rather than hidden. "Not
 *  dispatched" is the answer to "where is it", and an absent row answers
 *  nothing.
 */
function Step({ label, at, who, note, done }: {
  label: string; at?: string | null; who?: string; note?: string; done: boolean;
}) {
  return (
    <li className={`wb-step${done ? " is-done" : ""}`}>
      <span className="wb-step-label">{label}</span>
      <span className="wb-step-when">
        {at ? fmtDateTime(at) : <span className="muted">not yet</span>}
      </span>
      {who && <span className="wb-step-who">{who}</span>}
      {note && <span className="wb-step-note muted">{note}</span>}
    </li>
  );
}

export default function WaybillDetail() {
  const { id } = useParams();
  const [w, setW] = useState<Waybill | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.get<Waybill>(`/api/waybills/${id}`)
      .then(setW)
      .catch((e) => setError(errorText(e, "That waybill could not be opened.")));
  }, [id]);
  useEffect(() => { setW(null); load(); }, [load]);

  const toast = useToast();
  const ask = useAsk();

  /** Send it out, sign for it, or record that it did not go.
   *
   *  The first version of this page linked back to the deliveries list to do
   *  each of these, which is not acting on the record — it is sending somebody
   *  to the list to act on it there, with the waybill they were reading held
   *  in their head. Every one of these endpoints already existed.
   */
  async function act(what: "dispatch" | "deliver" | "fail") {
    if (!w) return;
    try {
      if (what === "dispatch") {
        await api.post(`/api/waybills/${w.id}/dispatch`, {});
        toast.ok(`${w.waybill_number} is out for delivery.`);
      } else if (what === "deliver") {
        const answer = await ask({
          title: `Who took ${w.waybill_number}?`,
          body: w.requires_id_check
            ? "This delivery contains a controlled substance. The recipient's "
              + "identity must be checked at the door and recorded."
            : "A parcel signed for by nobody is a missing parcel with a tick "
              + "against it.",
          field: "Received by",
          placeholder: w.recipient || "Full name of whoever took it",
          required: true, maxLength: 120,
          confirmLabel: "Delivered",
        });
        if (!answer.ok) return;
        await api.post(`/api/waybills/${w.id}/deliver`, {
          received_by: answer.value, id_number_seen: "",
          collected: w.cod_amount || null,
        });
        toast.ok(`Signed for by ${answer.value}.`);
      } else {
        const answer = await ask({
          title: `${w.waybill_number} did not deliver`,
          body: "The medicine is still the pharmacy's and still owed to the "
              + "patient. Say what happened so somebody can try again.",
          field: "What happened",
          placeholder: "Nobody home, gate locked",
          required: true,
          confirmLabel: "Record the failure",
          destructive: true,
        });
        if (!answer.ok) return;
        await api.post(`/api/waybills/${w.id}/fail`, { reason: answer.value });
        toast.warn("Recorded. The medicine is still ours.");
      }
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Deliveries", to: "/deliveries" },
              { label: w?.waybill_number ?? "This delivery" }]}
      eyebrow="Waybill"
      title={w?.waybill_number ?? ""}
      subtitle={w && [w.recipient, w.driver ? `driver ${w.driver}` : ""]
        .filter(Boolean).join(" · ")}
      loading={!w && !error}
      error={error}
      // Every delivery action lived on the list. Opening a waybill to check an
      // address and then having to go back to the list to send it out is the
      // shape of a report, not a work screen.
      actions={w && (
        <div className="page-actions">
          {w.status === "pending" && (
            <BusyButton className="btn primary" onClick={() => act("dispatch")}
                        busyLabel="Sending…">Send it out</BusyButton>
          )}
          {w.status === "out" && (
            <BusyButton className="btn primary" onClick={() => act("deliver")}
                        busyLabel="Recording…">Sign for it</BusyButton>
          )}
          {(w.status === "pending" || w.status === "out") && (
            <BusyButton className="btn" onClick={() => act("fail")}
                        busyLabel="Recording…">Did not deliver</BusyButton>
          )}
          {w.driver_profile_id && (
            <Link className="btn secondary" to={`/drivers/${w.driver_profile_id}`}>
              The driver
            </Link>
          )}
          {w.patient_id && (
            <Link className="btn secondary" to={`/patients/${w.patient_id}`}>
              The patient
            </Link>
          )}
        </div>
      )}
      facts={w ? [
        { label: "Status", value: w.status,
          tone: TONE[w.status] || undefined,
          hint: w.status === "failed" ? "the medicine is still ours" : undefined },
        { label: "Raised", value: fmtDateTime(w.created_at),
          hint: w.created_by || undefined },
        { label: "Delivered",
          value: w.delivered_at ? fmtDateTime(w.delivered_at) : "not yet",
          hint: w.received_by ? `signed by ${w.received_by}` : undefined },
        { label: "Identity check",
          value: w.requires_id_check ? "required" : "not required",
          tone: w.requires_id_check && !w.id_number_seen && w.status === "delivered"
            ? "bad" : undefined,
          hint: w.id_number_seen || undefined },
      ] : undefined}
    >
      {w && (
        <>
          {w.status === "failed" && (
            <div className="alert error">
              <Warning size={16} weight="fill" />
              <span>
                <b>This delivery did not arrive.</b>{" "}
                {w.failure_reason || "No reason was recorded."} The medicine is
                still the pharmacy's — it has not been handed to anybody, so it
                is either back on the shelf or still in the vehicle.
              </span>
            </div>
          )}

          {/* The one that matters to an inspector: a controlled medicine that
              had to be handed to a named person, delivered with nothing
              recorded about who took it. */}
          {w.requires_id_check && w.status === "delivered" && !w.id_number_seen && (
            <div className="alert error">
              <Warning size={16} weight="fill" />
              <span>
                <b>This delivery needed an identity check and none was
                recorded.</b> The medicine has gone and there is nothing on file
                saying who took it.
              </span>
            </div>
          )}

          <Panel title="Chain of custody"
                 aside={<span className="muted small">
                   Who had it, and when it changed hands
                 </span>}>
            <ul className="wb-steps">
              <Step label="Raised" at={w.created_at} who={w.created_by} done />
              <Step label="Left the pharmacy" at={w.dispatched_at}
                    who={w.driver || undefined}
                    note={w.driver ? undefined : "no driver recorded"}
                    done={!!w.dispatched_at} />
              <Step label={w.status === "failed" ? "Did not arrive" : "Handed over"}
                    at={w.delivered_at}
                    who={w.received_by || undefined}
                    note={w.status === "failed" ? w.failure_reason : undefined}
                    done={!!w.delivered_at || w.status === "failed"} />
            </ul>
          </Panel>

          <div className="grid cols-2">
            <Panel title="Where it was going">
              <dl className="kv">
                <dt>Recipient</dt>
                <dd>
                  <EntityLink kind="patient" id={w.patient_id}>
                    {w.recipient || "—"}
                  </EntityLink>
                </dd>
                <dt>Address</dt>
                <dd className="wrap">{w.address || <span className="muted">none given</span>}</dd>
                <dt>Telephone</dt>
                <dd>
                  {w.phone
                    ? <a href={`tel:${w.phone}`} className="row-link">
                        <Phone size={13} /> {w.phone}
                      </a>
                    : <span className="muted">no number</span>}
                </dd>
                <dt>Instructions</dt>
                <dd className="wrap">
                  {w.instructions || <span className="muted">none</span>}
                </dd>
              </dl>
            </Panel>

            <Panel title="What it was for">
              <dl className="kv">
                <dt>Sale</dt>
                <dd>
                  <EntityLink kind="sale" id={w.sale_id}>
                    {w.sale_id ? `#${w.sale_id}` : "—"}
                  </EntityLink>
                </dd>
                <dt>Patient</dt>
                <dd>
                  <EntityLink kind="patient" id={w.patient_id}>
                    {w.patient_id ? w.recipient : "—"}
                  </EntityLink>
                </dd>
                <dt>Identity seen</dt>
                <dd>{w.id_number_seen || <span className="muted">not recorded</span>}</dd>
              </dl>
            </Panel>
          </div>
        </>
      )}
    </RecordPage>
  );
}
