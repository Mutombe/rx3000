/** What the dispensary has to do, beside the screen where it gets done.
 *
 *  This sits down the right of the dispensary rather than on a page of its own,
 *  because a queue you have to navigate to is a queue you check twice a day. The
 *  whole point is that it is in view while the work is happening.
 *
 *  Three panels, in the order a dispenser needs them: what is waiting and how
 *  urgent, which chronic patients are drifting, and who is due a repeat. Every
 *  row is truncated at the source — a name that pushes the quantity out of a
 *  narrow column makes the panel useless at exactly the width it has to live at.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { useToast } from "./Toast";

interface QueueRow {
  item_id: number; prescription_id: number; rx_number: string;
  patient_id: number | null; patient: string; product: string;
  quantity: number; band: number; band_label: string; reason: string;
  booked_for: string; waiting_days: number; schedule: number; chronic: boolean;
}
interface ChronicRow {
  patient_id: number; patient: string; conditions: string;
  next_due: string; days_to_due: number | null; state: string;
  call: string; phone: string;
}
interface ReminderRow {
  patient_id: number; patient: string; product: string; due: string;
  days: number; overdue: boolean; call: string; phone: string;
  repeats_left: number;
}
interface Worklist {
  queue: QueueRow[];
  bands: Record<string, number>;
  chronics: ChronicRow[];
  reminders: ReminderRow[];
  counts: { waiting: number; showing: number; time_critical: number; overdue_repeats: number };
}

type Panel = "queue" | "chronics" | "due";

/** Band colour. Only the top band is loud — if everything is red, nothing is. */
const BAND_CLASS: Record<number, string> = {
  1: "wl-band-1", 2: "wl-band-2", 3: "wl-band-3", 4: "wl-band-4", 5: "wl-band-5",
};

export default function DispensaryWorklist({
  onPick,
}: {
  /** Called when a dispenser clicks a queued line, so the page can open it. */
  onPick?: (row: QueueRow) => void;
}) {
  const toast = useToast();
  const [data, setData] = useState<Worklist | null>(null);
  const [panel, setPanel] = useState<Panel>("queue");
  const [failed, setFailed] = useState("");

  const load = useCallback(() => {
    api.get<Worklist>("/api/dispensary/worklist")
      .then((w) => { setData(w); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "The worklist could not be loaded.")));
  }, []);

  useEffect(() => {
    load();
    // Refreshed rather than left stale: a queue that was right an hour ago is
    // worse than an empty one, because it reads as current.
    const timer = window.setInterval(load, 120_000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (failed) {
    return (
      <aside className="wl">
        <div className="wl-head"><span>Worklist</span></div>
        <p className="wl-empty">{failed}</p>
        <button className="btn ghost small" onClick={load}>Try again</button>
      </aside>
    );
  }

  if (!data) {
    return (
      <aside className="wl">
        <div className="wl-head"><span>Worklist</span></div>
        <div className="wl-skeleton" aria-hidden="true">
          {Array.from({ length: 6 }).map((_, i) => <span key={i} />)}
        </div>
      </aside>
    );
  }

  const { counts } = data;

  return (
    <aside className="wl">
      <div className="wl-head">
        <span>Worklist</span>
        <button className="btn ghost small" onClick={load} title="Refresh">↻</button>
      </div>

      {/* The three numbers a dispenser acts on, before any list. */}
      <div className="wl-stats">
        <button
          className={`wl-stat${panel === "queue" ? " is-on" : ""}`}
          onClick={() => setPanel("queue")}
        >
          <b>{counts.waiting}</b>
          <span>waiting</span>
        </button>
        <button
          className={`wl-stat${panel === "queue" ? "" : ""}${counts.time_critical ? " is-urgent" : ""}`}
          onClick={() => setPanel("queue")}
        >
          <b>{counts.time_critical}</b>
          <span>time-critical</span>
        </button>
        <button
          className={`wl-stat${panel === "due" ? " is-on" : ""}${counts.overdue_repeats ? " is-urgent" : ""}`}
          onClick={() => setPanel("due")}
        >
          <b>{counts.overdue_repeats}</b>
          <span>overdue</span>
        </button>
      </div>

      <div className="wl-tabs">
        {([["queue", `Queue ${counts.waiting}`],
           ["chronics", `Chronic ${data.chronics.length}`],
           ["due", `Due ${data.reminders.length}`]] as [Panel, string][]).map(([key, label]) => (
          <button
            key={key}
            className={panel === key ? "on" : ""}
            onClick={() => setPanel(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {panel === "queue" && (
        <div className="wl-list">
          {data.queue.length === 0 && <p className="wl-empty">Nothing waiting to be dispensed.</p>}
          {data.queue.map((row) => (
            <button
              key={row.item_id}
              className={`wl-row ${BAND_CLASS[row.band]}`}
              onClick={() => onPick?.(row)}
              title={`${row.reason} · booked ${row.booked_for}`}
            >
              <span className="wl-row-top">
                <span className="wl-patient">{row.patient}</span>
                <span className="wl-qty">×{row.quantity}</span>
              </span>
              <span className="wl-row-mid">{row.product}</span>
              <span className="wl-row-foot">
                <span className="wl-tag">{row.band_label}</span>
                {row.schedule >= 5 && <span className="wl-tag wl-tag-sched">S{row.schedule}</span>}
                {/* Days waiting, not the date. "8 days" is actionable; a date
                    means arithmetic. */}
                <span className="wl-wait">
                  {row.waiting_days <= 0 ? "today" : `${row.waiting_days}d`}
                </span>
              </span>
            </button>
          ))}
          {counts.showing < counts.waiting && (
            // Said plainly. A list that quietly shows 200 of 258 is the same
            // lie as a total that reports its own cap.
            <p className="wl-empty">
              Showing the {counts.showing} most urgent of {counts.waiting}.
            </p>
          )}
        </div>
      )}

      {panel === "chronics" && (
        <div className="wl-list">
          {data.chronics.length === 0 && <p className="wl-empty">No chronic patients on file.</p>}
          {data.chronics.map((row) => (
            <div key={row.patient_id} className={`wl-row wl-state-${row.state.replace(/\s+/g, "-")}`}>
              <span className="wl-row-top">
                <span className="wl-patient">{row.patient}</span>
                <span className="wl-tag">{row.state}</span>
              </span>
              <span className="wl-row-mid">{row.conditions}</span>
              <span className="wl-row-foot">
                {/* Who to ring, which for a chronic patient is often not them. */}
                {row.phone
                  ? <a href={`tel:${row.phone}`} className="wl-call">☎ {row.call}</a>
                  : <span className="wl-wait">no number on file</span>}
                {row.next_due && <span className="wl-wait">due {row.next_due}</span>}
              </span>
            </div>
          ))}
        </div>
      )}

      {panel === "due" && (
        <div className="wl-list">
          {data.reminders.length === 0 && (
            <p className="wl-empty">No repeats due in the next week.</p>
          )}
          {data.reminders.map((row, i) => (
            <div key={`${row.patient_id}-${i}`} className={`wl-row${row.overdue ? " wl-band-1" : ""}`}>
              <span className="wl-row-top">
                <span className="wl-patient">{row.patient}</span>
                <span className="wl-qty">{row.repeats_left} left</span>
              </span>
              <span className="wl-row-mid">{row.product}</span>
              <span className="wl-row-foot">
                {row.phone
                  ? <a href={`tel:${row.phone}`} className="wl-call">☎ {row.call}</a>
                  : <span className="wl-wait">no number on file</span>}
                <span className={row.overdue ? "wl-tag" : "wl-wait"}>
                  {row.overdue ? `${Math.abs(row.days)}d overdue` : `in ${row.days}d`}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
