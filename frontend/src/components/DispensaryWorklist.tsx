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
import { ArrowsClockwise, Phone } from "@phosphor-icons/react";
import BusyButton from "./BusyButton";
import RepeatValue from "./RepeatValue";
import { DRAFT_SCRIPT_PLURAL } from "../terms";

interface QueueRow {
  item_id: number; prescription_id: number; rx_number: string;
  patient_id: number | null; patient: string; product: string;
  quantity: number; band: number; band_label: string; reason: string;
  booked_for: string; waiting_days: number; schedule: number; chronic: boolean;
  value: number; value_remaining: number;
  /** Whether this line has gone out before, and how much of the script is left.
   *  A repeat is checked differently from a first dispensing, and the queue used
   *  to say nothing — you had to open the script to find out. */
  is_repeat: boolean; repeats_used: number; repeats_allowed: number; repeats_left: number;
}
interface ChronicRow {
  patient_id: number; patient: string; conditions: string;
  next_due: string; days_to_due: number | null; state: string;
  call: string; phone: string;
  /** What this patient's repeat book is worth each cycle. */
  value: number;
}
export interface ReminderRow {
  patient_id: number; patient: string; product: string; due: string;
  days: number; overdue: boolean; call: string; phone: string;
  value: number; value_remaining: number;
  repeats_left: number;
  /** Enough to open the line rather than only read it. */
  item_id: number; prescription_id: number; product_id: number;
  doctor_id: number | null; quantity: number; dosage_instructions: string;
  schedule: number;
}
interface Worklist {
  queue: QueueRow[];
  bands: Record<string, number>;
  chronics: ChronicRow[];
  reminders: ReminderRow[];
  counts: { waiting: number; showing: number; time_critical: number; overdue_repeats: number };
}

export type WorklistPanel = "queue" | "chronics" | "due" | "drafts";
type Panel = WorklistPanel;

/** Band colour. Only the top band is loud — if everything is red, nothing is. */
const BAND_CLASS: Record<number, string> = {
  1: "wl-band-1", 2: "wl-band-2", 3: "wl-band-3", 4: "wl-band-4", 5: "wl-band-5",
};

export default function DispensaryWorklist({
  onPick,
  onPickDraft,
  onPickRepeat,
  panel: panelProp,
  onPanelChange,
  reloadOn,
}: {
  /** Changes when the page has done something the queue should reflect.
   *  Without it the rail refreshed on a two-minute timer, so dispensing a line
   *  left the count unchanged for up to two minutes — after the one action that
   *  should visibly move it. */
  reloadOn?: number;
  /** Segment to show. Optional: the rail governs itself unless told otherwise,
   *  which is what lets a keyboard shortcut on the page open "Due". */
  panel?: Panel;
  onPanelChange?: (panel: Panel) => void;
  /** Called when a dispenser opens an N-Repeat — a script captured but not
   *  yet finished, so it holds no Rx number. */
  onPickDraft?: (draft: any) => void;
  /** Called when a dispenser clicks a queued line, so the page can open it. */
  onPick?: (row: QueueRow) => void;
  /** Called when a dispenser clicks a repeat that is due. */
  onPickRepeat?: (row: ReminderRow) => void;
}) {
  const toast = useToast();
  const [data, setData] = useState<Worklist | null>(null);
  /** Scripts somebody started and did not finish.
   *
   *  Its endpoint says it plainly, oldest first, the stalest is the risk, and
   *  nothing showed them. A draft is a patient who was served halfway: the
   *  medicine is not dispensed, the queue does not know about it because it has
   *  no Rx number yet, and the only person who knows is whoever walked away
   *  from it. */
  const [drafts, setDrafts] = useState<any[]>([]);
  const [ownPanel, setOwnPanel] = useState<Panel>("queue");
  const panel = panelProp ?? ownPanel;
  const setPanel = (next: Panel) => { setOwnPanel(next); onPanelChange?.(next); };
  const [failed, setFailed] = useState("");

  /* Returns the promise rather than dropping it.
     Without the `return` the refresh button had nothing to wait on: it resolved
     the instant it was pressed, so the spin lasted one frame and the control was
     back to looking idle while the request was still in flight. Anything that
     wants to know when a load has finished, a busy control, a test, needs the
     promise handed back, not started and forgotten. */
  const load = useCallback(() => {
    // The drafts are read alongside the queue rather than only when their tab
    // is opened: the count is on the tab, and a tab that says nothing until
    // you press it is a tab nobody presses.
    api.get<any[]>("/api/prescriptions/queue/unfinished?limit=50")
      .then(setDrafts).catch(() => setDrafts([]));
    return api.get<Worklist>("/api/dispensary/worklist")
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

  // And immediately when the page says something changed.
  useEffect(() => { if (reloadOn) load(); }, [reloadOn, load]);

  if (failed) {
    return (
      <aside className="wl">
        <div className="wl-head"><span>Worklist</span></div>
        <p className="wl-empty">{failed}</p>
        <BusyButton className="btn ghost small" onClick={load} icon={ArrowsClockwise} busyLabel="Trying…">
          Try again
        </BusyButton>
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
        {/* Turns while it is loading. A refresh that looks identical before and
            after the press is why people press it four times. */}
        <BusyButton
          className="btn ghost small"
          onClick={load}
          icon={ArrowsClockwise}
          title="Refresh"
          aria-label="Refresh the worklist"
        />
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

      {/* Label and count as separate elements rather than one string.
          The count is the half that changes and the half worth reading, and
          keeping them apart lets the number stay legible when the rail is
          narrow enough to clip the word. */}
      <div className="wl-tabs">
        {([["queue", "Queue", counts.waiting],
           ["chronics", "Chronic", data.chronics.length],
           ["due", "Due", data.reminders.length],
           ["drafts", DRAFT_SCRIPT_PLURAL, drafts.length]] as [Panel, string, number][])
          .map(([key, label, n]) => (
          <button
            key={key}
            className={panel === key ? "on" : ""}
            onClick={() => setPanel(key)}
            title={`${label} — ${n}`}
          >
            <span>{label}</span>
            <span className="wl-tab-n">{n}</span>
          </button>
        ))}
      </div>

      {panel === "drafts" && (
        <div className="wl-list">
          {drafts.length === 0 && (
            <p className="wl-empty">
              Nothing was left half-captured. Every script started has been
              finished or cancelled.
            </p>
          )}
          {drafts.map((d) => (
            <button
              key={d.id}
              className="wl-row"
              onClick={() => onPickDraft?.(d)}
              title="Started and never finished"
            >
              <span className="wl-row-top">
                <span className="wl-patient">
                  {d.patient
                    ? `${d.patient.first_name} ${d.patient.last_name}`
                    : "No patient yet"}
                </span>
                <span className="wl-qty">
                  {(d.items?.length ?? 0)} item{(d.items?.length ?? 0) === 1 ? "" : "s"}
                </span>
              </span>
              <span className="wl-row-sub">
                {d.draft_ref || "draft"}
                {d.updated_at && ` · last touched ${new Date(d.updated_at).toLocaleDateString()}`}
              </span>
            </button>
          ))}
        </div>
      )}

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
                {/* Beside the quantity, where the eye already goes for a
                    number. The rail listed two hundred names and no money, so
                    it could not be worked in the order that pays, which on a
                    short-staffed morning is the only question. */}
                <span className="wl-qty">
                  <RepeatValue value={row.value} size="chip" />
                  {" "}×{row.quantity}
                </span>
              </span>
              <span className="wl-row-mid">{row.product}</span>
              <span className="wl-row-foot">
                <span className="wl-tag">{row.band_label}</span>
                {row.is_repeat && (
                  <span className="wl-tag wl-tag-repeat"
                        title={`Repeat ${row.repeats_used} of ${row.repeats_allowed}`
                               + (row.value_remaining
                                  ? ` · ${row.repeats_left} left, worth `
                                    + row.value_remaining.toFixed(2)
                                  : "")}>
                    repeat {row.repeats_used}/{row.repeats_allowed}
                  </span>
                )}
                {row.schedule >= 5 && <span className="wl-tag wl-tag-sched">S{row.schedule}</span>}
                {/* Days waiting, not the date. "8 days" is actionable; a date
                    means arithmetic. */}
                <span className={`wl-wait${row.waiting_days > 14 ? " is-stale" : ""}`}
                      title={row.waiting_days <= 0
                        ? "Booked in today"
                        : `Waiting ${row.waiting_days} days`}>
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
                {/* A chronic list ordered by name treats a patient worth four
                    dollars a month and one worth ninety exactly alike. */}
                <RepeatValue value={row.value} size="chip" />
                <span className="wl-tag">{row.state}</span>
              </span>
              <span className="wl-row-mid">{row.conditions}</span>
              <span className="wl-row-foot">
                {/* Who to ring, which for a chronic patient is often not them. */}
                {row.phone
                  ? <a href={`tel:${row.phone}`} className="wl-call"><Phone size={11} weight="fill" /> {row.call}</a>
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
            <p className="wl-empty">No repeats due in the next fortnight.</p>
          )}
          {/* A button, like every other row in this rail. These were <div>s: the
              panel told a dispenser a repeat was due and then gave them no way
              to act on it, so the only route to the work was to go and find the
              patient by hand. Clicking now loads the line into the form, where
              the checking pharmacist's initials are captured, which is why the
              old shortcut button could never have worked. */}
          {data.reminders.map((row, i) => (
            <button
              key={`${row.patient_id}-${i}`}
              className={`wl-row${row.overdue ? " wl-band-1" : ""}`}
              onClick={() => onPickRepeat?.(row)}
              title={`Open ${row.product} for ${row.patient}`}
            >
              <span className="wl-row-top">
                <span className="wl-patient">{row.patient}</span>
                {/* What this collection is worth. A call sheet without money
                    cannot be worked in the order that pays, and a
                    short-staffed morning is exactly when that order matters. */}
                <span className="wl-qty">
                  <RepeatValue value={row.value} size="chip" />
                  {" "}{row.repeats_left} left
                </span>
              </span>
              <span className="wl-row-mid">{row.product}</span>
              <span className="wl-row-foot">
                {/* Named with the same word the queue uses. A panel headed "Due"
                    and a tag reading "repeat" are the same thing said twice in
                    two vocabularies; one word, used everywhere, is how somebody
                    learns the screen once. */}
                <span className="wl-tag wl-tag-repeat"
                      title={row.value_remaining
                        ? `${row.repeats_left} repeat(s) left, worth `
                          + row.value_remaining.toFixed(2)
                          + " if this patient keeps coming back"
                        : "A repeat"}>
                  repeat
                </span>
                {row.phone
                  ? (
                    // The row opens the work; the number rings the patient.
                    // Two destinations in one row, so the call must not also
                    // navigate.
                    <a href={`tel:${row.phone}`} className="wl-call"
                       onClick={(e) => e.stopPropagation()}><Phone size={11} weight="fill" /> {row.call}</a>
                  )
                  : <span className="wl-wait">no number on file</span>}
                <span className={row.overdue ? "wl-tag" : "wl-wait"}>
                  {row.overdue ? `${Math.abs(row.days)}d overdue` : `in ${row.days}d`}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
