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
import { EntityLink, TableSearch, useSearch } from "./Filters";
import Select from "./Select";
import { Figure, GhostRows } from "./Skeleton";
import { useToast } from "./Toast";
import Person from "./Person";
import Th from "./Th";

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
  /* Patients who have stopped coming. The list is worked down by ringing
     people, so somebody comes back to it asking "did I already call her".
     Without a search that is a re-read of the whole list. */
  const { q, setQ, shown } = useSearch(data?.leaving ?? [], (l) =>
    [l.patient, l.phone]);
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
        patient: l.patient, phone: l.phone || "none",
        last: l.last_seen ? fmtDate(l.last_seen) : "No date",
        away: l.days_away ?? "none", visits: l.visits_before,
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

      {/* SCOPED LOADING.
       *
       * This whole screen used to sit behind one skeleton table, so arriving on
       * it showed eight grey rows and nothing else: the four band labels, the
       * two section headings and their descriptions, both table heads and the
       * search over the call list were all withheld, and then landed at once
       * about half a page taller. None of them are fetched.
       *
       * So the frame is drawn from the first paint and only the figures pulse.
       * The two "nothing to report" notices are the careful part: a pharmacy
       * being told nobody has stopped coming is being told something, and it
       * must not be told it before the server has answered. Both sit AFTER the
       * `data` test, never before it. */}
      <div className={`refreshable${loading ? " is-refreshing" : ""}`}>
        {data && therapies && !data.measurable ? (
          // Nought regulars is not nought churn. Showing 0% here would tell a
          // pharmacy three months old that its retention is perfect.
          <div className="empty">
            <b>Not enough history to measure churn yet</b>
            <p>{data.why_not}</p>
          </div>
        ) : (
          <>
            <div className="wc-bands">
              <div className="wc-band">
                <span className="wc-band-label">Churn</span>
                <b className={data ? `tone-${data.tone}` : undefined}>
                  <Figure ready={!!data} w="4ch">{data?.rate}%</Figure>
                </b>
                <span className="muted small">
                  <Figure ready={!!data} w="2ch">{data?.churned}</Figure> of{" "}
                  <Figure ready={!!data} w="3ch">{data?.regulars}</Figure> regulars
                  stopped coming
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">Worth per month</span>
                <b className={data && data.lost_monthly > 0 ? "neg" : undefined}>
                  <Figure ready={!!data} w="8ch">{data && money(data.lost_monthly)}</Figure>
                </b>
                <span className="muted small">
                  what they were spending while they came
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">A point of churn</span>
                <b><Figure ready={!!data} w="8ch">{data && money(data.point_value)}</Figure></b>
                <span className="muted small">
                  per month, so one point back is worth that much
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">Kept</span>
                <b><Figure ready={!!data} w="3ch">{data?.retained}</Figure></b>
                <span className="muted small">
                  <Figure ready={!!data} w="8ch">{data && money(data.kept_monthly)}</Figure>
                  {" a month · "}
                  <Figure ready={!!data} w="2ch">{data?.new_patients}</Figure> new since
                </span>
              </div>
            </div>

            <p className="muted small" style={{ maxWidth: "62ch" }}>
              {/* The caveat is written by the server against the window chosen,
                  so it is one of the few sentences here that really is fetched. */}
              <Figure ready={!!data} w="56ch">{data?.caveat}</Figure>
            </p>

            <div className="card-head" style={{ marginTop: 18 }}>
              <div>
                <h4>Worth a telephone call</h4>
                <span className="muted small">
                  Most valuable first. A patient seen{" "}
                  <Figure ready={!!data} w="2ch">{data?.regular_visits}</Figure> times
                  or more before, and not since.
                </span>
              </div>
            </div>
            {data && data.leaving.length === 0 ? (
              <div className="empty">
                <b>Nobody has stopped coming</b>
                <p>
                  Every regular from the earlier window has been back. That is
                  the number this screen exists to protect.
                </p>
              </div>
            ) : (
              <>
              {/* Hoisted out of the old skeleton: the box and its Clear button
                  are the same on every visit and can be typed into before a
                  single row lands. Only the count waits. */}
              <TableSearch value={q} onChange={setQ}
                           placeholder="Find a patient or a telephone number…"
                           ready={!!data}
                           shown={shown.length} total={data?.leaving.length ?? 0} />
              <div className="dt-scroll">
                <table className="dt">
                  <thead>
                    <tr>
                      <Th>Patient</Th>
                      <Th>Telephone</Th>
                      <Th>Last seen</Th>
                      <Th className="num">Days away</Th>
                      <Th className="num">Visits before</Th>
                      <Th className="num">Per month</Th>
                    </tr>
                  </thead>
                  {!data ? (
                    <GhostRows cols={6} rows={6}
                               widths={["70%", "70%", "60%", "40%", "40%", "60%"]} />
                  ) : (
                  <tbody>
                    {shown.map((l) => (
                      <tr key={l.patient_id}>
                        <td>
                          <EntityLink kind="patient" id={l.patient_id}>
                            <Person name={l.patient} />
                          </EntityLink>
                        </td>
                        <td className="mono">
                          {l.phone
                            ? <a href={`tel:${l.phone}`} className="row-link">
                                <Phone size={13} /> {l.phone}
                              </a>
                            : <span className="muted">No number</span>}
                        </td>
                        <td>{l.last_seen ? fmtDate(l.last_seen) : "No date"}</td>
                        <td className="num">{l.days_away ?? "none"}</td>
                        <td className="num">{l.visits_before}</td>
                        <td className="num">{money(l.monthly_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                  )}
                </table>
              </div>
              </>
            )}

          </>
        )}

        {/* Shown whether or not the patient half could be measured: a pharmacy
            may have plenty of dispensing history and few sales tied to a named
            patient, and a stopped treatment is the more urgent of the two
            findings anyway. */}
        <div className="card-head" style={{ marginTop: 22 }}>
          <div>
            <h4>Treatments that stopped</h4>
            <span className="muted small">
              Medicines somebody was established on. At least{" "}
              <Figure ready={!!therapies} w="1ch">{therapies?.minimum_fills}</Figure>{" "}
              fills, and has not come back for.
              {therapies && therapies.value_at_risk > 0 &&
                <> {money(therapies.value_at_risk)} of dispensing at risk.</>}
            </span>
          </div>
        </div>
        {therapies && therapies.lines.length === 0 ? (
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
                  <Th>Medicine</Th>
                  <Th className="num">Established on it</Th>
                  <Th className="num">Stopped</Th>
                  <Th className="num">Rate</Th>
                  <Th className="num">Dispensing at risk</Th>
                </tr>
              </thead>
              {!therapies ? (
                <GhostRows cols={5} rows={5}
                           widths={["70%", "40%", "40%", "40%", "60%"]} />
              ) : (
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
              )}
            </table>
          </div>
        )}
      </div>
    </>
  );
}
