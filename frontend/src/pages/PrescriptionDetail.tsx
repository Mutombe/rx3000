/** One script: who wrote it, who it is for, and what is left on it.
 *
 *  Rx numbers appear on a dozen screens — the will-call shelf, the register,
 *  recalls, claims, to-follows, and not one of them opened. The script is the
 *  document a dispensary organises itself around, and it was the one record you
 *  could not look at.
 *
 *  WHAT CHANGED, AND WHAT HAS GONE OUT
 *
 *  Two things the page did not say and the record has always known.
 *
 *  `ScriptChange` has recorded every correction — per field, with the old
 *  value, the new value, a reason and a name — since the alter endpoint was
 *  written, and nothing read it back except a report nobody opens on the day it
 *  matters. "What did this used to say" is asked about one script at a time,
 *  usually with somebody on the telephone.
 *
 *  And what has actually left the shelf, which is the difference between a
 *  script and a supply. It also decides whether a line can still be corrected:
 *  not a matter of permission but of fact, because a dispensed line records
 *  something that physically happened and editing it would make the register
 *  disagree with the medicine.
 */
import { useEffect, useState } from "react";
import { ArrowsClockwise, PencilSimpleLine } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RepeatValue from "../components/RepeatValue";
import RecordPage, { Panel } from "../components/RecordPage";
import { Link, useNavigate, useParams } from "react-router-dom";

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

interface Alteration {
  id: number; item_id: number | null; field: string;
  old_value: string; new_value: string; reason: string;
  changed_at: string; changed_by: string;
}
interface Dispensed {
  id: number; dispensed_at: string; quantity: number; product: string;
  is_repeat: boolean; dispensed_by: string; sale_id: number | null;
}
interface Trail {
  script_id: string;
  alterations: Alteration[];
  dispensings: Dispensed[];
  items: { id: number; alterable: boolean }[];
}

/** Field names as a dispenser would say them, not as the column is spelt. */
const FIELD_NAMES: Record<string, string> = {
  quantity: "Quantity",
  dosage_instructions: "Directions",
  icd10_code: "Diagnosis",
  supply_days: "Days of supply",
};

export default function PrescriptionDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [d, setD] = useState<Data | null>(null);
  const [trail, setTrail] = useState<Trail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/prescriptions/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That prescription could not be opened.")));
    // A second request rather than a heavier first one: the capture shape is
    // what the dispensing screen asks for on every keystroke of a script being
    // built, and hanging an alteration history off it would make that request
    // carry a trail nobody is looking at yet.
    setTrail(null);
    api.get<Trail>(`/api/prescriptions/${id}/full`)
      .then(setTrail)
      // The trail is an addition to this page, not the page. Failing to load it
      // must not blank a script somebody opened to read.
      .catch(() => setTrail(null));
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
      // The number on the paper, whichever kind it is. An N-Repeat
      // carries a draft reference rather than an Rx number, and titling
      // that page "Unnumbered" told somebody holding one they had the
      // wrong script.
      title={<span className="script-id">
        {d?.rx_number || trail?.script_id || "Unnumbered"}</span>}
      subtitle={d && (
        <>
          <EntityLink kind="patient" id={d.patient_id}>{patientName || "Walk-in"}</EntityLink>
          {d.doctor && <> · <EntityLink kind="prescriber" id={d.doctor_id}>
            {d.doctor.name}</EntityLink></>}
        </>
      )}
      loading={!d && !error}
      error={error}
      // A script you could read and not act on. The one thing anybody opens a
      // script to do is dispense it, and the route was to go back to the
      // dispensary and find it again by patient.
      actions={d && (
        <div className="page-actions">
          {d.status !== "cancelled" && repeatsLeft >= 0 && (
            <button className="btn primary"
              onClick={() => navigate(`/dispense?rx=${d.id}`)}>
              {d.status === "draft" ? "Finish capturing it" : "Dispense it"}
            </button>
          )}
          {/* Labels are asked for again far more often than they are printed
              the first time: a bag re-bagged, a label that smudged. */}
          {d.status !== "draft" && (
            <button className="btn"
              onClick={() => navigate(`/dispense?reprint=${d.id}`)}>
              Reprint labels
            </button>
          )}
          {d.patient?.id && (
            <Link className="btn secondary" to={`/patients/${d.patient.id}`}>
              The patient
            </Link>
          )}
        </div>
      )}
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
        // Only when there is something to say. A zero here would be a fifth
        // figure competing with four that change a decision.
        ...(trail && trail.alterations.length ? [{
          label: "Altered", value: trail.alterations.length,
          tone: "warn", hint: "corrected since capture — see below",
        }] : []),
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
                      back, which is the only commercial question anybody asks
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

          {/* What has actually left the shelf. A script and a supply are not
              the same thing, and this page said nothing about the difference. */}
          {trail && (
            <Panel title="What has gone out" count={trail.dispensings.length}
                   empty="Nothing on this script has been dispensed yet.">
              <table className="dt">
                <thead>
                  <tr>
                    <th>When</th><th>Medicine</th>
                    <th className="num">Qty</th><th>Dispensed by</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {trail.dispensings.map((x) => (
                    <tr key={x.id}>
                      <td>{fmtDateTime(x.dispensed_at)}</td>
                      <td>
                        <Link to={`/dispensings/${x.id}`}>{x.product}</Link>
                        {x.is_repeat && (
                          <span className="badge muted" style={{ marginLeft: 6 }}>
                            <ArrowsClockwise size={10} /> repeat
                          </span>
                        )}
                      </td>
                      <td className="num">{x.quantity}</td>
                      <td className="muted">{x.dispensed_by || "—"}</td>
                      <td>
                        {x.sale_id && (
                          <Link to={`/sales/${x.sale_id}`} className="muted small">
                            the sale
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}

          {/* Newest first: somebody checking a script wants the last thing
              that happened to it and reads backwards from there. */}
          {trail && (
            <Panel title="Alterations" count={trail.alterations.length}
                   empty="Nothing on this script has been changed since it was captured.">
              <table className="dt">
                <thead>
                  <tr>
                    <th>When</th><th>Field</th><th>From</th><th>To</th>
                    <th>Reason</th><th>By</th>
                  </tr>
                </thead>
                <tbody>
                  {trail.alterations.map((a) => (
                    <tr key={a.id}>
                      <td>{fmtDateTime(a.changed_at)}</td>
                      <td>{FIELD_NAMES[a.field] ?? a.field}</td>
                      {/* The old value in full. "Directions changed" is exactly
                          the note that is useless when somebody asks what they
                          used to say. */}
                      <td className="muted">{a.old_value || <em>blank</em>}</td>
                      <td><b>{a.new_value || <em>blank</em>}</b></td>
                      <td>{a.reason || <span className="muted">—</span>}</td>
                      <td className="muted">{a.changed_by || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}

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
