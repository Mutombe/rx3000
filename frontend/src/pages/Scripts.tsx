/** Every script the pharmacy holds, looked up by the number on it.
 *
 *  There was no such screen. A script could be reached through a patient —
 *  which needs the patient's name, or through the dispensing history, which
 *  lists the individual dispensings, so a script supplied over four visits
 *  appears four times and one never dispensed does not appear at all. The
 *  question a dispensary asks constantly, "bring me RX-0412", had no answer
 *  except the alter dialogue, which finds the script and then only lets you
 *  change a quantity.
 *
 *  THE NUMBER IS THE POINT
 *
 *  So it leads the row, in a monospace face, because it is read off a piece of
 *  paper and typed, or read down a telephone. A script that has been altered
 *  says so on the row: that is the one somebody is usually looking for, and
 *  before this the only way to find it was a report.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, PencilSimpleLine } from "@phosphor-icons/react";
import { api, errorText, fmtDate, prefetchRoute } from "../api";
import { EntityLink } from "../components/Filters";
import RowLink from "../components/RowLink";
import Pagination, { Paged } from "../components/Pagination";
import Select from "../components/Select";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { DRAFT_SCRIPT, DRAFT_SCRIPT_PLURAL } from "../terms";

interface Row {
  id: number;
  script_id: string;
  rx_number: string;
  draft_ref: string;
  status: string;
  /** COLLECTED, WAITING or ONHOLD: where the medicine has got to. */
  state?: string;
  date_prescribed: string | null;
  created_at: string;
  patient_id: number | null;
  patient: string;
  doctor_id: number | null;
  doctor: string;
  items: number;
  repeats_left: number;
  dispensed_count: number;
  alterations: number;
}

const WINDOWS: [string, string][] = [
  ["0", "All time"], ["7", "Last 7 days"], ["30", "Last 30 days"],
  ["90", "Last 90 days"], ["365", "Last year"],
];

/** The states a script can be in, in the words the dispensary uses. */
/* Where the medicine is, which is what a counter asks.
 *
 * "Active", "Draft" and "Cancelled" describe the RECORD, and nobody behind a
 * counter thinks in those terms. They ask whether the bag is still on the
 * shelf, whether somebody has taken it home, or whether something is stopping
 * it. Draft and cancelled stay on the list because they exist, but they are not
 * what the filter leads with.
 */
const STATES: [string, string][] = [
  ["", "Any state"],
  ["WAITING", "Waiting"],
  ["COLLECTED", "Collected"],
  ["ONHOLD", "On hold"],
  ["draft", DRAFT_SCRIPT_PLURAL],
  ["cancelled", "Cancelled"],
];

/** How long a script has been waiting, said rather than left to arithmetic.
 *
 *  A prescription written yesterday and one written eight months ago both read
 *  "Waiting", and the reader had to subtract a date in another column to tell
 *  them apart. The one that has been waiting since February is the one worth
 *  acting on, and it looked exactly like the one from this morning.
 *
 *  Deliberately a FACT and not a verdict. This system has no prescription
 *  validity window: there is no column for one and no setting behind it, and
 *  `services/script_scan.py` says so where it refuses to invent one. A badge
 *  here reading "out of date" would be this screen enforcing a rule no other
 *  screen agrees with. How long it has waited is true either way, and it is
 *  the part somebody needs to see.
 */
function waitingFor(written: string | null): string {
  if (!written) return "";
  const days = Math.floor((Date.now() - new Date(written).getTime()) / 86400000);
  if (days < 31) return "";
  const months = Math.round(days / 30);
  return months < 12
    ? `${months} month${months === 1 ? "" : "s"}`
    : `over a year`;
}

export default function Scripts() {
  const [data, setData] = useState<Paged<Row> | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [days, setDays] = useState("0");
  const [altered, setAltered] = useState(false);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [spinning, setSpinning] = useState(false);
  const [failed, setFailed] = useState("");

  const load = useCallback(() => {
    setSpinning(true);
    const params = new URLSearchParams({
      q, status, days, page: String(page),
      ...(altered ? { altered_only: "true" } : {}),
    });
    api.get<Paged<Row>>(`/api/prescriptions/table?${params}`)
      .then((d) => { setData(d); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "Scripts could not be listed.")))
      .finally(() => { setLoading(false); setSpinning(false); });
  }, [q, status, days, altered, page]);

  // Typing narrows the list; it should not fire a request per keystroke on a
  // table this size.
  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  // A new filter is a new result set, so it starts at its first page rather
  // than page four of something else.
  useEffect(() => { setPage(1); }, [q, status, days, altered]);

  // The script detail already exists at /prescriptions/:id — it is the
  // page every Rx number in the product links to, and a second one for the
  // same record would drift from it inside a fortnight. This list is the
  // part that was missing.
  useEffect(() => { prefetchRoute("/prescriptions/1"); }, []);

  const rows = data?.items ?? [];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Scripts</h1>
          <div className="page-sub">
            Every script on file, by its number. What is on it, what has gone
            out, and what has been altered since capture
          </div>
        </div>
        <button className="btn secondary" onClick={load}>
          <ArrowClockwise size={15} className={spinning ? "spin" : ""} />
          Refresh
        </button>
      </div>

      <div className="card">
        <div className="filter-bar">
          <input
            type="search" className="filter-search" autoFocus
            placeholder="Script number, patient, ID number or prescriber…"
            value={q} onChange={(e) => setQ(e.target.value)}
          />
          <span className="filter-dim">
            <Select value={status} onChange={setStatus} ariaLabel="State"
                    options={STATES.map(([v, l]) => ({ value: v, label: l }))} />
          </span>
          <span className="filter-dim">
            <Select value={days} onChange={setDays} ariaLabel="Period"
                    options={WINDOWS.map(([v, l]) => ({ value: v, label: l }))} />
          </span>
          {/* The reason this screen exists in the form it does. */}
          <button className={`btn small ${altered ? "" : "ghost"}`}
                  onClick={() => setAltered(!altered)}>
            <PencilSimpleLine size={13} /> Altered
          </button>
        </div>

        {failed && <div className="alert error">{failed}</div>}

        {!failed && !loading && rows.length === 0 && (
          <div className="empty">
            <b>No script matches that.</b>
            <p>
              Search by the number on the script. An Rx number for one that has
              been finished, or the reference on {"an " + DRAFT_SCRIPT} for one
              still being captured. A patient's name, ID number or the
              prescriber will find it too.
            </p>
          </div>
        )}

        {/* The skeleton was inside `rows.length > 0`, where it could never run:
            by the time there were rows there was nothing to stand in for. So
            the first paint of this screen was an empty card with a filter bar
            above it, and then a table. */}
        {(loading || rows.length > 0) && (
          <Refreshable
            loading={loading}
            hasData={!!data?.items?.length}
            skeleton={<TableSkeleton cols={7} rows={10} rowHeight={49}
              widths={["14ch", "10ch", "20ch", "18ch", "5ch", "8ch", "10ch"]}
              // The script number carries a badge under it, and Dispensed a
              // second line.
              secondLine={[0, 5]} />}
          >
            <table className="dt">
              <thead>
                <tr>
                  <th>Script</th>
                  <th>State</th>
                  <th>Patient</th>
                  <th>Prescriber</th>
                  <th className="num">Items</th>
                  <th className="num">Dispensed</th>
                  <th>Written</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <RowLink key={r.id} to={`/prescriptions/${r.id}`}>
                    <td>
                      <b className="script-id">{r.script_id}</b>
                      {/* An alteration is the fact somebody came here to
                          find. It belongs on the row, not one click in. */}
                      {r.alterations > 0 && (
                        <span className="badge warn" style={{ marginLeft: 6 }}>
                          <PencilSimpleLine size={10} weight="fill" />{" "}
                          {r.alterations} altered
                        </span>
                      )}
                    </td>
                    <td>
                      {/* A cancelled or draft record says so; everything else
                          says where the medicine is. */}
                      {r.status === "draft" ? (
                        <span className="badge warn">{DRAFT_SCRIPT}</span>
                      ) : r.status === "cancelled" ? (
                        <span className="badge muted">Cancelled</span>
                      ) : r.state === "ONHOLD" ? (
                        <span className="badge danger">On hold</span>
                      ) : r.state === "COLLECTED" ? (
                        <span className="badge ok">Collected</span>
                      ) : (
                        <>
                          <span className="badge warn">Waiting</span>
                          {waitingFor(r.date_prescribed) && (
                            <div className="muted small">
                              {waitingFor(r.date_prescribed)} old
                            </div>
                          )}
                        </>
                      )}
                    </td>
                    <td>
                      <EntityLink kind="patient" id={r.patient_id}>
                        {r.patient || "none"}
                      </EntityLink>
                    </td>
                    <td className="muted">{r.doctor || "none"}</td>
                    <td className="num">{r.items}</td>
                    <td className="num">
                      {r.dispensed_count}
                      {r.repeats_left > 0 && (
                        <div className="muted small">
                          {r.repeats_left} repeat{r.repeats_left === 1 ? "" : "s"} left
                        </div>
                      )}
                    </td>
                    <td className="muted">
                      {r.date_prescribed ? fmtDate(r.date_prescribed) : "No date"}
                    </td>
                  </RowLink>
                ))}
              </tbody>
            </table>
          </Refreshable>
        )}

        {data && <Pagination meta={data} onPage={setPage} noun="scripts" />}
      </div>
    </div>
  );
}
