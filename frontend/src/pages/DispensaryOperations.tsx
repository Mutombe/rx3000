/** The dispensary's day, as it is happening.
 *
 *  CareXpress To-Be blueprint §10, the Dispensing Operations Dashboard: scripts
 *  processed, queue depth, processing time, holds and reversals, in real time.
 *  Read by whoever runs the dispensary between patients, so it answers "how are
 *  we doing and what is stuck" at a glance, and refreshes itself.
 *
 *  "Today" is counted here, in the browser, not on the server. Everything is
 *  stored in UTC and the server's clock is not the pharmacy's: a day cut at UTC
 *  midnight would split a Harare morning at two o'clock and file the eight
 *  o'clock rush under six. The server sends the last thirty-six hours as they
 *  happened; this page counts them in the time zone it is read in.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ArrowsClockwise } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import { ColumnChart, useSeries } from "../components/charts";
import { Block, Refreshable } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import Person from "../components/Person";

interface Operations {
  as_of: string;
  queue_lines: number;
  dispensings: { at: string; prescription_id: number; patient_id: number | null;
                 dispenser: string; waited_minutes: number | null }[];
  voids: { at: string; sale_number: string }[];
  holds_placed: string[];
  open_holds: { id: number; prescription_id: number; rx_number: string; patient: string;
                reason: string; placed_by: string; placed_at: string; hours_held: number }[];
}

/** A script dispensed within this many minutes of being captured went out in
 *  the same visit — typed at the counter and handed over. Counted apart, or a
 *  morning of walk-ins drags the median wait to nothing. */
const SAME_VISIT_MINUTES = 5;
const REFRESH_MS = 60_000;

function isToday(iso: string, now: Date): boolean {
  const d = new Date(iso);
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
    && d.getDate() === now.getDate();
}

function duration(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min`;
  if (minutes < 24 * 60) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes - h * 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  const days = Math.round(minutes / (24 * 60));
  return `${days} day${days === 1 ? "" : "s"}`;
}

function median(sorted: number[]): number | null {
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export default function DispensaryOperations() {
  const toast = useToast();
  const series = useSeries();
  const [data, setData] = useState<Operations | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api.get<Operations>("/api/dispensary/operations")
      .then(setData)
      .catch((e) => toast.error(errorText(e, "The dispensary's figures could not be loaded.")))
      .finally(() => setLoading(false));
  }, [toast]);

  useEffect(() => {
    load();
    const t = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const day = useMemo(() => {
    if (!data) return null;
    const now = new Date();
    const today = data.dispensings.filter((d) => isToday(d.at, now));

    // One wait per script: from capture to its first line going out today.
    const firstOut = new Map<number, { at: Date; waited: number | null }>();
    for (const d of today) {
      const at = new Date(d.at);
      const seen = firstOut.get(d.prescription_id);
      if (!seen || at < seen.at) firstOut.set(d.prescription_id, { at, waited: d.waited_minutes });
    }
    const waits = [...firstOut.values()].map((s) => s.waited).filter((w): w is number => w !== null);
    const sameVisit = waits.filter((w) => w < SAME_VISIT_MINUTES).length;
    const waited = waits.filter((w) => w >= SAME_VISIT_MINUTES).sort((a, b) => a - b);

    // Scripts by the hour their first line went out, from opening until now.
    const byHour = new Map<number, number>();
    for (const s of firstOut.values()) byHour.set(s.at.getHours(), (byHour.get(s.at.getHours()) ?? 0) + 1);
    const hours = [...byHour.keys()];
    const from = Math.min(8, ...hours);
    const to = Math.max(now.getHours(), ...hours, from);
    const columns = Array.from({ length: to - from + 1 }, (_, i) => from + i).map((h) => ({
      label: `${String(h).padStart(2, "0")}h`,
      segments: [{ key: "Scripts", value: byHour.get(h) ?? 0, colour: series[0] }],
    }));

    const people = new Map<string, { scripts: Set<number>; lines: number }>();
    for (const d of today) {
      const who = d.dispenser || "Unknown";
      const row = people.get(who) ?? { scripts: new Set<number>(), lines: 0 };
      row.scripts.add(d.prescription_id);
      row.lines += 1;
      people.set(who, row);
    }
    const dispensers = [...people.entries()]
      .map(([name, r]) => ({ name, scripts: r.scripts.size, lines: r.lines }))
      .sort((a, b) => b.scripts - a.scripts || b.lines - a.lines);

    return {
      scripts: firstOut.size,
      lines: today.length,
      patients: new Set(today.map((d) => d.patient_id).filter(Boolean)).size,
      sameVisit,
      waitedCount: waited.length,
      medianWait: median(waited),
      holdsPlacedToday: data.holds_placed.filter((h) => isToday(h, now)).length,
      voidsToday: data.voids.filter((v) => isToday(v.at, now)).length,
      columns,
      dispensers,
      updated: new Date(data.as_of),
    };
  }, [data, series]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dispensary operations</h1>
          <div className="sub">
            Today, as it happens
            {day && <> · updated {day.updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</>}
          </div>
        </div>
        <button type="button" className="btn secondary" onClick={load} disabled={loading}>
          <ArrowsClockwise size={14} weight="bold" /> Refresh
        </button>
      </div>

      <Refreshable
        loading={loading}
        hasData={!!day}
        skeleton={
          <div className="grid ops-tiles">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="card stat"><Block h={64} round="md" /></div>
            ))}
          </div>
        }
      >
        {day && data && (
          <>
            <div className="grid ops-tiles">
              <div className="card stat hero">
                <div className="label">Scripts dispensed today</div>
                <div className="value accent">{day.scripts}</div>
                <div className="hint">
                  {day.lines} line{day.lines === 1 ? "" : "s"} · {day.patients} patient{day.patients === 1 ? "" : "s"}
                </div>
              </div>
              <div className="card stat">
                <div className="label">Lines waiting</div>
                <div className="value">{data.queue_lines}</div>
                <div className="hint">
                  <Link to="/dispense">to the dispensary <ArrowRight size={12} weight="bold" /></Link>
                </div>
              </div>
              <div className="card stat">
                <div className="label">Median wait today</div>
                <div className="value">
                  {day.medianWait === null
                    ? <span className="muted">Nothing dispensed yet</span>
                    : duration(day.medianWait)}
                </div>
                <div className="hint">
                  Capture to dispensed · {day.waitedCount} waited, {day.sameVisit} same visit
                </div>
              </div>
              <div className="card stat">
                <div className="label">On hold now</div>
                <div className={`value${data.open_holds.length ? " warn" : ""}`}>{data.open_holds.length}</div>
                <div className="hint">{day.holdsPlacedToday} placed today</div>
              </div>
              <div className="card stat">
                <div className="label">Dispensed sales voided today</div>
                <div className="value">{day.voidsToday}</div>
                <div className="hint">Whole sales. A single dispensing can&rsquo;t be reversed yet</div>
              </div>
            </div>

            <div className="grid cols-2">
              <div className="card">
                <div className="card-head">
                  <div>
                    <h3>Scripts, hour by hour</h3>
                    <span className="muted small">
                      Each script counted in the hour its first line went out.
                    </span>
                  </div>
                </div>
                {day.scripts ? (
                  <ColumnChart height={220} columns={day.columns}
                    // Scripts are counted whole. On a quiet morning the scale steps
                    // in halves, and rounding the half labelled the axis "1, 1, 0";
                    // a tick between whole scripts is left unlabelled instead.
                    format={(n) => (Number.isInteger(n) ? String(n) : "")} />
                ) : (
                  <p className="muted ops-empty">Nothing has been dispensed yet today.</p>
                )}
              </div>

              <div className="card">
                <div className="card-head">
                  <div>
                    <h3>Who dispensed what</h3>
                    <span className="muted small">Today, by the person who dispensed it.</span>
                  </div>
                </div>
                {day.dispensers.length ? (
                  <table className="ops-table">
                    <thead>
                      <tr><th>Dispenser</th><th className="num">Scripts</th><th className="num">Lines</th></tr>
                    </thead>
                    <tbody>
                      {day.dispensers.map((d) => (
                        <tr key={d.name}>
                          <td>{d.name}</td>
                          <td className="num">{d.scripts}</td>
                          <td className="num">{d.lines}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="muted ops-empty">Nobody has dispensed yet today.</p>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-head">
                <div>
                  <h3>On hold</h3>
                  <span className="muted small">
                    Longest held first. Each is a patient still waiting for something.
                  </span>
                </div>
                <Link className="btn ghost sm" to="/reports?report=dispensing_holds">
                  The holds report <ArrowRight size={12} weight="bold" />
                </Link>
              </div>
              {data.open_holds.length ? (
                <table className="ops-table">
                  <thead>
                    <tr>
                      <th>Script</th><th>Patient</th><th>Why</th><th>Held by</th>
                      <th className="num">Held for</th><th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.open_holds.map((h) => (
                      <tr key={h.id}>
                        <td className="mono">{h.rx_number}</td>
                        <td><Person name={h.patient} /></td>
                        <td>{h.reason}</td>
                        <td><Person name={h.placed_by} absent="Not recorded" /></td>
                        <td className="num">{duration(h.hours_held * 60)}</td>
                        <td className="actions">
                          <Link to={`/dispense?rx=${h.prescription_id}`}>
                            Open <ArrowRight size={12} weight="bold" />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted ops-empty">Nothing is on hold.</p>
              )}
            </div>
          </>
        )}
      </Refreshable>
    </>
  );
}
