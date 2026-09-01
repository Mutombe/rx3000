/** Who stopped coming, and what it costs a month.
 *
 *  Every other screen in this software counts people who came. This is the only
 *  one that counts people who did not, and that asymmetry is the reason a
 *  pharmacy can lose a patient a week for a year and conclude the economy is
 *  bad. A patient who leaves files no paperwork. The absence IS the event, and
 *  the only way to see an absence is to compare two windows.
 *
 *  Two questions, deliberately kept apart:
 *
 *    **Who left the pharmacy**: regulars in the earlier window who did not
 *    come back in the later one. A retention call.
 *
 *    **What people stopped taking**: a medicine somebody was established on
 *    and has not refilled, even though they are still shopping here. That is
 *    not a lost customer; it is a stopped treatment, and it is the more urgent
 *    of the two.
 */
import { useEffect, useState } from "react";
import { Phone, Printer } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { EntityLink } from "./Filters";
import Select from "./Select";
import { Refreshable, TableSkeleton } from "./Skeleton";
import { useToast } from "./Toast";

interface Leaver {
  patient_id: number; patient: string; phone: string;
  visits_before: number; spent_before: number; monthly_value: number;
  last_seen: string | null; days_away: number | null;
}
interface Churn {
  days: number; base_from: string; base_to: string;
  recent_from: string; recent_to: string;
  regulars: number; churned: number; retained: number;
  rate: number | null; measurable: boolean;
  retention_rate: number | null; tone: string; why_not: string;
  lost_value: number; lost_monthly: number; kept_monthly: number;
  point_value: number; regular_visits: number;
  new_patients: number; leaving: Leaver[]; caveat: string;
}
interface TherapyLine {
  product_id: number; product: string; established: number; stopped: number;
  rate: number; tone: string; value_at_risk: number;
}
interface Therapies {
  days: number; therapies: number; stopped: number; rate: number;
  value_at_risk: number; minimum_fills: number; lines: TherapyLine[];
}

const WINDOWS = [
  { value: "30", label: "Month against month" },
  { value: "60", label: "Two months against two" },
  { value: "90", label: "Quarter against quarter" },
  { value: "180", label: "Half year against half" },
];

export default function Churn() {
  const [days, setDays] = useState("90");
  const [data, setData] = useState<Churn | null>(null);
  const [therapies, setTherapies] = useState<Therapies | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<Churn>(`/api/repeats/churn?days=${days}`),
      api.get<Therapies>(`/api/repeats/churn/therapies?days=${days}`),
    ])
      .then(([c, t]) => { setData(c); setTherapies(t); })
      .catch((e) => toast.error(errorText(e, "Churn could not be worked out.")))
      .finally(() => setLoading(false));
  }, [days]);

  async function printCallList() {
    if (!data) return;
    const head = await letterhead();
    printDocument(head, {
      kind: "Patients who have stopped coming",
      meta: [
        { label: "Window", value: `${fmtDate(data.recent_from)} to ${fmtDate(data.recent_to)}` },
        { label: "Compared with", value: `${fmtDate(data.base_from)} to ${fmtDate(data.base_to)}` },
        { label: "Churn", value: `${data.rate}%` },
        { label: "Worth per month", value: money(data.lost_monthly), strong: true },
      ],
      columns: [
        { key: "patient", label: "Patient" },
        { key: "phone", label: "Telephone", width: "30mm" },
        { key: "last", label: "Last seen", width: "24mm" },
        { key: "away", label: "Days away", numeric: true, width: "22mm" },
        { key: "visits", label: "Visits", numeric: true, width: "18mm" },
        { key: "value", label: "Per month", numeric: true, width: "26mm" },
      ],
      rows: data.leaving.map((l) => ({
        patient: l.patient, phone: l.phone || "—",
        last: l.last_seen ? fmtDate(l.last_seen) : "—",
        away: l.days_away ?? "—", visits: l.visits_before,
        value: money(l.monthly_value),
      })),
      totals: { patient: `${data.leaving.length} patients`,
                value: money(data.lost_monthly) },
      note: data.caveat,
    });
  }

  return (
    <>
      <div className="card-head">
        <div>
          <h3>Churn</h3>
          <span className="muted small">
            {data
              ? <>Regulars between {fmtDate(data.base_from)} and {fmtDate(data.base_to)},
                  measured against who came back since.</>
              : "Who was coming, and who stopped."}
          </span>
        </div>
        <div className="row-actions">
          <Select value={days} onChange={setDays} options={WINDOWS}
                  ariaLabel="Comparison window" />
          <button className="btn secondary" onClick={printCallList}
                  disabled={!data?.leaving.length}>
            <Printer size={15} /> Call list
          </button>
        </div>
      </div>

      <Refreshable loading={loading} hasData={!!data}
                   skeleton={<TableSkeleton rows={8} cols={6} />}>
        {data && therapies && !data.measurable && (
          // Nought regulars is not nought churn. Showing 0% here would tell a
          // pharmacy three months old that its retention is perfect.
          <div className="empty">
            <b>Not enough history to measure churn yet</b>
            <p>{data.why_not}</p>
          </div>
        )}

        {data && therapies && data.measurable && (
          <>
            <div className="wc-bands">
              <div className="wc-band">
                <span className="wc-band-label">Churn</span>
                <b className={`tone-${data.tone}`}>{data.rate}%</b>
                <span className="muted small">
                  {data.churned} of {data.regulars} regulars stopped coming
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">Worth per month</span>
                <b className={data.lost_monthly > 0 ? "neg" : undefined}>
                  {money(data.lost_monthly)}
                </b>
                <span className="muted small">
                  what they were spending while they came
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">A point of churn</span>
                <b>{money(data.point_value)}</b>
                <span className="muted small">
                  per month, so one point back is worth that much
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">Kept</span>
                <b>{data.retained}</b>
                <span className="muted small">
                  {money(data.kept_monthly)} a month · {data.new_patients} new since
                </span>
              </div>
            </div>

            <p className="muted small" style={{ maxWidth: "62ch" }}>
              {data.caveat}
            </p>

            <div className="card-head" style={{ marginTop: 18 }}>
              <div>
                <h4>Worth a telephone call</h4>
                <span className="muted small">
                  Most valuable first. A patient seen {data.regular_visits} times
                  or more before, and not since.
                </span>
              </div>
            </div>
            {data.leaving.length === 0 ? (
              <div className="empty">
                <b>Nobody has stopped coming</b>
                <p>
                  Every regular from the earlier window has been back. That is
                  the number this screen exists to protect.
                </p>
              </div>
            ) : (
              <div className="dt-scroll">
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Patient</th>
                      <th>Telephone</th>
                      <th>Last seen</th>
                      <th className="num">Days away</th>
                      <th className="num">Visits before</th>
                      <th className="num">Per month</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.leaving.map((l) => (
                      <tr key={l.patient_id}>
                        <td>
                          <EntityLink kind="patient" id={l.patient_id}>
                            {l.patient}
                          </EntityLink>
                        </td>
                        <td className="mono">
                          {l.phone
                            ? <a href={`tel:${l.phone}`} className="row-link">
                                <Phone size={13} /> {l.phone}
                              </a>
                            : <span className="muted">no number</span>}
                        </td>
                        <td>{l.last_seen ? fmtDate(l.last_seen) : "—"}</td>
                        <td className="num">{l.days_away ?? "—"}</td>
                        <td className="num">{l.visits_before}</td>
                        <td className="num">{money(l.monthly_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

          </>
        )}

        {/* Shown whether or not the patient half could be measured: a pharmacy
            may have plenty of dispensing history and few sales tied to a named
            patient, and a stopped treatment is the more urgent of the two
            findings anyway. */}
        {data && therapies && (
          <>
            <div className="card-head" style={{ marginTop: 22 }}>
              <div>
                <h4>Treatments that stopped</h4>
                <span className="muted small">
                  Medicines somebody was established on — at least{" "}
                  {therapies.minimum_fills} fills, and has not come back for.
                  {therapies.value_at_risk > 0 &&
                    <> {money(therapies.value_at_risk)} of dispensing at risk.</>}
                </span>
              </div>
            </div>
            {therapies.lines.length === 0 ? (
              <div className="empty">
                <b>No therapy has visibly stopped</b>
                <p>
                  Either everybody established on a repeat is still collecting
                  it, or there is not yet enough history in this window to tell.
                </p>
              </div>
            ) : (
              <div className="dt-scroll">
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Medicine</th>
                      <th className="num">Established on it</th>
                      <th className="num">Stopped</th>
                      <th className="num">Rate</th>
                      <th className="num">Dispensing at risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {therapies.lines.map((l) => (
                      <tr key={l.product_id} className={`row-${l.tone}`}>
                        <td>
                          <EntityLink kind="product" id={l.product_id}>
                            {l.product}
                          </EntityLink>
                        </td>
                        <td className="num">{l.established}</td>
                        <td className="num">{l.stopped}</td>
                        <td className="num">
                          <span className={`badge ${l.tone}`}>{l.rate}%</span>
                        </td>
                        <td className="num">{money(l.value_at_risk)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Refreshable>
    </>
  );
}
