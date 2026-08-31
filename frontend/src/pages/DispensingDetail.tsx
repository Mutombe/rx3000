/** One handover, in full.
 *
 *  The dispensing history listed thousands of these and opened none. Every
 *  column on that list was a link to something *else* — the script, the
 *  patient, the prescriber — and the dispensing itself was the one thing you
 *  could not read.
 *
 *  That is the wrong way round. On a controlled item this row IS the legal
 *  record, and "who had it, checked by whom, against which script" is a
 *  question asked by an inspector rather than out of curiosity.
 *
 *  The compliance block shows on every dispensing, not only scheduled ones. A
 *  blank identity check on an S5 has to read as a blank; a section that
 *  disappears when it is empty is a section nobody notices is missing.
 */
import { useCallback, useEffect, useState } from "react";
import RepeatValue from "../components/RepeatValue";
import { Link, useParams } from "react-router-dom";
import { CheckCircle, Warning, XCircle } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import BusyButton from "../components/BusyButton";
import { useAsk, useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";

interface Detail {
  id: number; quantity: number; dispensed_at: string; is_repeat: boolean;
  dispensed_by: string; dispensed_by_id: number | null;
  pharmacist_initial: string;
  dispense_type: string; schedule: number;
  id_verified: boolean; id_number_seen: string;
  script_sighted: boolean; prescriber_verified: boolean;
  compliance_notes: string;
  collected_at: string | null; collected_name: string; collected_by: string;
  days_waiting: number | null;
  product: { id: number; name: string; form: string; schedule: number } | null;
  patient: { id: number | null; name: string; phone: string };
  prescription: { id: number; number: string; date: string;
                  doctor: string; doctor_id: number | null } | null;
  directions: string; icd10_code: string;
  sale: { id: number; number: string; status: string;
          total: number; line_value: number } | null;
  repeat: { item_id: number; allowed: number; used: number; left: number;
            next_due: string | null; interval_days: number } | null;
  siblings: { id: number; product: string; quantity: number;
              dispensed_at: string; collected_at: string | null }[];
}

/** A yes/no that reads as a yes or a no, never as a blank. */
function Checked({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className={ok ? "tone-ok" : "tone-danger"}>
      {ok ? <CheckCircle size={15} weight="fill" />
          : <XCircle size={15} weight="fill" />}{" "}
      <span className={ok ? undefined : "muted"}>{children}</span>
    </li>
  );
}

export default function DispensingDetail() {
  const { id } = useParams();
  const [d, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.get<Detail>(`/api/dispensings/${id}`)
      .then(setData)
      .catch((e) => setError(errorText(e)));
  }, [id]);
  useEffect(load, [load]);

  const controlled = !!d && ((d.schedule || 0) >= 5 || d.dispense_type === "controlled");
  const incomplete = controlled && !(d!.id_verified && d!.script_sighted);

  const toast = useToast();
  const ask = useAsk();
  /** Hand the bag over from the will-call shelf.
   *
   *  This page says a bag has been sitting there for eleven days and had no
   *  way to close it — the collection lived only on the will-call screen, so
   *  reading the record and acting on it were two places.
   */
  async function collect() {
    if (!d) return;
    const controlledItem = (d.schedule || 0) >= 5;
    const answer = await ask({
      title: `Who is taking ${d.product?.name ?? "this"}?`,
      body: controlledItem
        ? `This is a schedule ${d.schedule} item. The name of whoever `
          + "physically receives it is the answer to \"who had it\"."
        : "Often not the patient — a relative, a driver, a neighbour going "
          + "that way. Recorded as given.",
      field: "Name, as given",
      placeholder: d.patient.name,
      required: true,
      maxLength: 120,
      confirmLabel: "Hand it over",
    });
    if (!answer.ok) return;
    try {
      await api.post(`/api/dispensing/will-call/${d.id}/collect`,
                     { taken_by: answer.value, id_seen: "" });
      toast.ok(`Handed to ${answer.value}.`);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded."));
    }
  }
  return (
    <RecordPage
      trail={[{ label: "Dispensing history", to: "/dispensing-history" },
              { label: d?.product?.name ?? "Dispensing" }]}
      eyebrow="Dispensing"
      title={d?.product?.name ?? "Dispensing"}
      subtitle={d && (
        <>
          {d.quantity} to {d.patient.name} on {fmtDateTime(d.dispensed_at)}
          {d.dispensed_by && ` · ${d.dispensed_by}`}
          {d.is_repeat && " · a repeat"}
        </>
      )}
      loading={!d && !error}
      error={error}
      actions={d && (
        <div className="page-actions">
          {!d.collected_at && (
            <BusyButton className="btn primary" onClick={collect}
                        busyLabel="Recording…">
              Hand it over
            </BusyButton>
          )}
          {d.sale && (
            <Link className="btn secondary" to={`/sales/${d.sale.id}`}>
              The sale
            </Link>
          )}
          {d.prescription && (
            <Link className="btn secondary"
                  to={`/prescriptions/${d.prescription.id}`}>
              The script
            </Link>
          )}
        </div>
      )}
      facts={d ? [
        { label: "Dispensed", value: d.quantity,
          hint: d.product?.form || undefined },
        { label: "Collected",
          value: d.collected_at ? fmtDate(d.collected_at) : "not yet",
          hint: d.collected_at ? (d.collected_name || undefined)
            : d.days_waiting !== null ? `${d.days_waiting} days on the shelf`
            : undefined,
          tone: d.collected_at ? undefined
            : (d.days_waiting ?? 0) > 14 ? "bad" : "warn" },
        ...(d.sale ? [{
          label: "Charged",
          value: money(d.sale.line_value || d.sale.total),
          hint: d.sale.line_value ? "this line" : "the whole sale",
        }] : []),
        ...(d.repeat ? [{
          label: "Repeat",
          value: `${d.repeat.used} of ${d.repeat.allowed}`,
          hint: d.repeat.left > 0 ? `${d.repeat.left} left` : "the last one",
        }] : []),
        { label: "Record",
          value: incomplete ? "incomplete" : controlled ? "complete" : "kept",
          hint: controlled ? `schedule ${d.schedule}` : undefined,
          tone: incomplete ? "bad" : undefined },
      ] : undefined}
    >
      {d && (
        <>
          {/* Not collected is the state that costs money and nobody sees. The
              stock is off the shelf, the patient is not taking it, and on a
              scheme script a claim has been made for something never received. */}
          {!d.collected_at && (
            <div className={`alert ${(d.days_waiting ?? 0) > 14 ? "error" : "warn"}`}>
              <Warning size={16} weight="fill" />{" "}
              Still on the will-call shelf
              {d.days_waiting !== null && ` — ${d.days_waiting} day${
                d.days_waiting === 1 ? "" : "s"} now`}
              . The stock is out of circulation and the patient is not taking it.
            </div>
          )}

          {incomplete && (
            // Said out loud rather than left for somebody to infer from two
            // red crosses. A scheduled item handed over without the checks is
            // exactly what an inspection is looking for.
            <div className="alert error">
              <Warning size={16} weight="fill" />{" "}
              This is a schedule {d.schedule} item and the handover record is
              incomplete.
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="What was handed over">
              <dl className="kv">
                <dt>Medicine</dt>
                <dd>
                  {d.product
                    ? <EntityLink kind="product" id={d.product.id}>
                        {d.product.name}
                      </EntityLink>
                    : "—"}
                  {d.product?.form && (
                    <span className="muted"> · {d.product.form}</span>
                  )}
                  {(d.product?.schedule ?? 0) > 0 && (
                    <span className="badge warn"> S{d.product!.schedule}</span>
                  )}
                </dd>
                <dt>Quantity</dt><dd>{d.quantity}</dd>
                <dt>Directions</dt>
                <dd className="wrap">
                  {d.directions || <span className="muted">none recorded</span>}
                </dd>
                <dt>Diagnosis</dt>
                <dd className="mono">
                  {d.icd10_code || <span className="muted">none</span>}
                </dd>
                <dt>Patient</dt>
                <dd>
                  {d.patient.id
                    ? <EntityLink kind="patient" id={d.patient.id}>
                        {d.patient.name}
                      </EntityLink>
                    : d.patient.name}
                  {d.patient.phone && (
                    <div className="muted small">{d.patient.phone}</div>
                  )}
                </dd>
                <dt>Script</dt>
                <dd>
                  {d.prescription ? (
                    <>
                      <EntityLink kind="prescription" id={d.prescription.id}>
                        {d.prescription.number || `#${d.prescription.id}`}
                      </EntityLink>
                      {d.prescription.date && (
                        <span className="muted"> · {fmtDate(d.prescription.date)}</span>
                      )}
                      {d.prescription.doctor && (
                        <div className="muted small">
                          {d.prescription.doctor_id
                            ? <EntityLink kind="prescriber" id={d.prescription.doctor_id}>
                                {d.prescription.doctor}
                              </EntityLink>
                            : d.prescription.doctor}
                        </div>
                      )}
                    </>
                  ) : <span className="muted">—</span>}
                </dd>
                {d.sale && (
                  <>
                    <dt>Sale</dt>
                    <dd>
                      <EntityLink kind="sale" id={d.sale.id}>
                        {d.sale.number}
                      </EntityLink>{" "}
                      <span className={`badge ${
                        d.sale.status === "paid" ? "ok"
                          : d.sale.status === "void" ? "bad" : "warn"}`}>
                        {d.sale.status}
                      </span>
                    </dd>
                  </>
                )}
              </dl>
            </Panel>

            <Panel
              title="The record"
              aside={<span className="muted small">
                {controlled
                  ? "A scheduled item — this is the legal record"
                  : "Kept on every dispensing, so a gap reads as a gap"}
              </span>}
            >
              <dl className="kv">
                <dt>Dispensed by</dt>
                <dd>
                  {d.dispensed_by_id
                    ? <EntityLink kind="staff" id={d.dispensed_by_id}>
                        {d.dispensed_by || "—"}
                      </EntityLink>
                    : d.dispensed_by || <span className="muted">—</span>}
                  {d.pharmacist_initial && (
                    <span className="muted"> · initialled {d.pharmacist_initial}</span>
                  )}
                </dd>
                <dt>When</dt><dd>{fmtDateTime(d.dispensed_at)}</dd>
                <dt>Collected</dt>
                <dd>
                  {d.collected_at ? (
                    <>
                      {fmtDateTime(d.collected_at)}
                      {d.collected_name && (
                        <div className="muted small">
                          Taken by {d.collected_name}
                          {d.collected_by && ` · released by ${d.collected_by}`}
                        </div>
                      )}
                    </>
                  ) : <span className="muted">still on the shelf</span>}
                </dd>
              </dl>
              <ul className="plain-list">
                <Checked ok={d.script_sighted}>Original script sighted</Checked>
                <Checked ok={d.prescriber_verified}>Prescriber verified</Checked>
                <Checked ok={d.id_verified}>
                  Identity checked{d.id_number_seen && ` — ${d.id_number_seen}`}
                </Checked>
              </ul>
              {d.compliance_notes && (
                <p className="prose">{d.compliance_notes}</p>
              )}
            </Panel>
          </div>

          {d.repeat && (
            <Panel
              title="Where this sits in the repeat"
              aside={<Link className="btn ghost sm"
                           to={`/repeats/${d.repeat.item_id}`}>
                Open the repeat
              </Link>}
            >
              <p className="muted">
                Fill {d.repeat.used} of {d.repeat.allowed}
                {d.repeat.left > 0
                  ? `, ${d.repeat.left} left`
                  : ", the last one on this script"}
                {d.repeat.next_due && ` · next due ${fmtDate(d.repeat.next_due)}`}
                {d.repeat.interval_days
                  ? ` · every ${d.repeat.interval_days} days`
                  : ""}
              </p>
            </Panel>
          )}

          <Panel
            title="The rest of this script"
            count={d.siblings.length}
            empty="Nothing else was dispensed against this script."
            aside={<span className="muted small">
              {/* A bag with one of three items in it is a different thing from
                  a finished script, and only this says which. */}
              So a bag is not handed over while its other half stays on the shelf
            </span>}
          >
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Medicine</th><th className="num">Qty</th>
                    <th>Dispensed</th><th>Collected</th>
                  </tr>
                </thead>
                <tbody>
                  {d.siblings.map((s) => (
                    <tr key={s.id}>
                      <td><Link to={`/dispensings/${s.id}`}>{s.product}</Link></td>
                      <td className="num">{s.quantity}</td>
                      <td>{fmtDateTime(s.dispensed_at)}</td>
                      <td>
                        {s.collected_at
                          ? fmtDate(s.collected_at)
                          : <span className="badge warn">on the shelf</span>}
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
