/** One script: who wrote it, who it is for, and what is left on it.
 *
 *  Rx numbers appear on a dozen screens — the will-call shelf, the register,
 *  recalls, claims, to-follows — and not one of them opened. The script is the
 *  document a dispensary organises itself around, and it was the one record you
 *  could not look at.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RepeatValue from "../components/RepeatValue";
import RecordPage, { Panel } from "../components/RecordPage";
import { useParams } from "react-router-dom";

interface Item {
  id: number; product_id: number; dosage_instructions: string;
  quantity: number; repeats_allowed: number; repeats_used: number;
  repeat_interval_days: number; next_repeat_date: string | null;
  auto_refill: boolean; icd10_code: string; supply_days: number;
  no_claim: boolean; not_dispensed: boolean;
  product?: { id: number; name: string; strength?: string; schedule?: number;
              unit_price?: number } | null;
}
interface Data {
  id: number; rx_number: string | null; status: string;
  patient_id: number; doctor_id: number | null;
  date_prescribed: string; notes: string;
  items: Item[];
  patient?: { id: number; first_name: string; last_name: string; phone?: string } | null;
  doctor?: { id: number; name: string; practice_number?: string } | null;
}

export default function PrescriptionDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/prescriptions/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That prescription could not be opened.")));
  }, [id]);

  const patientName = d?.patient
    ? `${d.patient.first_name} ${d.patient.last_name}`.trim() : "";
  const repeatsLeft = d?.items.reduce(
    (n, i) => n + Math.max(0, (i.repeats_allowed || 0) - (i.repeats_used || 0)), 0) ?? 0;
  // What the script still has in it. The figure a shop would want on the day a
  // patient says they are moving away, and nothing anywhere produced it.
  const worthToCome = d?.items.reduce(
    (n, i) => n + (i.product?.unit_price ?? 0) * (i.quantity ?? 0)
      * Math.max(0, (i.repeats_allowed || 0) - (i.repeats_used || 0)), 0) ?? 0;

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Dispensary", to: "/dispense" },
              { label: d?.rx_number || "This script" }]}
      eyebrow="Prescription"
      title={d?.rx_number || "Unnumbered"}
      subtitle={d && (
        <>
          <EntityLink kind="patient" id={d.patient_id}>{patientName || "Walk-in"}</EntityLink>
          {d.doctor && <> · <EntityLink kind="prescriber" id={d.doctor_id}>
            {d.doctor.name}</EntityLink></>}
        </>
      )}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Status", value: d.status },
        { label: "Items", value: d.items.length },
        { label: "Repeats left", value: repeatsLeft,
          hint: repeatsLeft ? "across all items" : "none remaining" },
        // What is still in the script. The figure a shop wants on the day a
        // patient says they are moving away, and nothing produced it.
        { label: "Still to come", value: money(worthToCome),
          hint: repeatsLeft ? "if the patient keeps returning"
                            : "the script is used up" },
        { label: "Written", value: fmtDate(d.date_prescribed) },
      ] : undefined}
    >
      {d && (
        <>
          <Panel title="Items on this script" count={d.items.length}
                 empty="Nothing was captured against this script.">
            <table className="dt">
              <thead>
                <tr>
                  <th>Medicine</th><th>Directions</th>
                  <th className="num">Qty</th><th className="num">Repeats</th>
                  {/* A script listing four repeats and no money cannot answer
                      what the script is worth if the patient keeps coming
                      back — which is the only commercial question anybody asks
                      of one. */}
                  <th className="num">Worth</th>
                  <th>Next due</th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((i) => {
                  const left = Math.max(0, (i.repeats_allowed || 0) - (i.repeats_used || 0));
                  return (
                    <tr key={i.id}>
                      <td>
                        <EntityLink kind="product" id={i.product_id}>
                          {i.product
                            ? `${i.product.name} ${i.product.strength ?? ""}`.trim()
                            : `#${i.product_id}`}
                        </EntityLink>
                        {(i.product?.schedule ?? 0) >= 3 && (
                          <span className="badge sched">S{i.product?.schedule}</span>
                        )}
                        {i.not_dispensed && (
                          <div className="muted small">not dispensed</div>
                        )}
                      </td>
                      <td>{i.dosage_instructions || "—"}</td>
                      <td className="num">{i.quantity}</td>
                      <td className="num">
                        {left} <span className="muted">of {i.repeats_allowed}</span>
                      </td>
                      <td className="num">
                        <RepeatValue
                          value={(i.product?.unit_price ?? 0) * (i.quantity ?? 0)}
                          remaining={(i.product?.unit_price ?? 0) * (i.quantity ?? 0) * left} />
                      </td>
                      <td>
                        {i.next_repeat_date ? fmtDate(i.next_repeat_date)
                          : <span className="muted">—</span>}
                        {i.auto_refill && <div className="muted small">auto refill</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>

          <div className="grid cols-2">
            <Panel title="Who it is for">
              <dl className="kv">
                <dt>Patient</dt>
                <dd>
                  <EntityLink kind="patient" id={d.patient_id}>
                    {patientName || "Walk-in"}
                  </EntityLink>
                  {d.patient?.phone && <div className="muted small">{d.patient.phone}</div>}
                </dd>
                <dt>Prescriber</dt>
                <dd>
                  <EntityLink kind="prescriber" id={d.doctor_id}>
                    {d.doctor?.name ?? "not recorded"}
                  </EntityLink>
                  {d.doctor?.practice_number && (
                    <div className="muted small mono">{d.doctor.practice_number}</div>
                  )}
                </dd>
                <dt>Written</dt><dd>{fmtDate(d.date_prescribed)}</dd>
                <dt>Status</dt><dd><span className="badge">{d.status}</span></dd>
              </dl>
            </Panel>

            <Panel title="Notes"
                   empty="Nothing was noted on this script.">
              {d.notes
                ? <p className="prose">{d.notes}</p>
                : <div className="empty"><p>Nothing was noted on this script.</p></div>}
            </Panel>
          </div>
        </>
      )}
    </RecordPage>
  );
}
