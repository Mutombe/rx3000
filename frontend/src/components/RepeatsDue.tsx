/** What else this patient has due, while they are standing in front of you.
 *
 *  Every other repeat screen in this system is a report: who to telephone, what
 *  the book is worth, how much of it was lost last month. All of them describe
 *  something that has already happened. A repeat is lost silently — nobody
 *  cancels, the line simply stops appearing next month, so by the time it is
 *  on a report the patient has already collected somewhere else.
 *
 *  This is the one place it can still be prevented, and it costs nothing: the
 *  patient is already here, the script already exists, and the medicine is
 *  either on the shelf or it is not. Adding a line is one press.
 *
 *  Deliberately not automatic. Dispensing somebody's repeat because the screen
 *  offered it is how a patient goes home with two months of medicine and the
 *  scheme rejects the second claim. The dispenser decides; this only makes sure
 *  they were asked.
 */
import { useEffect, useState } from "react";
import RepeatValue from "./RepeatValue";
import { ArrowClockwise, Plus, Warning } from "@phosphor-icons/react";
import { api, fmtDate, money } from "../api";
import { overdueTone } from "../tone";

export interface DueRepeat {
  item_id: number; prescription_id: number; rx_number: string;
  product_id: number; product: string; quantity: number;
  dosage_instructions: string; icd10_code: string;
  repeats_allowed: number; repeats_used: number; repeats_left: number;
  repeat_interval_days: number;
  due: string; days_overdue: number; value: number;
  can_supply: boolean; on_hand: number;
}
interface Payload {
  patient_id: number; due: number; value: number;
  overdue: number; overdue_value: number; cannot_supply: number;
  items: DueRepeat[];
}

export default function RepeatsDue({ patientId, onAdd, alreadyOn, variant = "list", onOpen }: {
  /** "chip": one line saying how many and what they are worth, for a lane. */
  variant?: "list" | "chip" | "icon";
  onOpen?: () => void;
  patientId: number | null;
  /** Put this repeat on the script being written. */
  onAdd: (repeat: DueRepeat) => void;
  /** Product ids already in the basket, so nothing is offered twice. */
  alreadyOn: number[];
}) {
  const [data, setData] = useState<Payload | null>(null);

  useEffect(() => {
    if (!patientId) { setData(null); return; }
    let live = true;
    api.get<Payload>(`/api/patients/${patientId}/repeats`)
      .then((d) => { if (live) setData(d); })
      // A repeat list that cannot be read must never stop somebody dispensing.
      // The panel simply does not appear.
      .catch(() => { if (live) setData(null); });
    return () => { live = false; };
  }, [patientId]);

  // An icon for a toolbar. Always there, muted when nothing is due, so it stays
  // in the same place for the hand that reaches for it.
  if (variant === "icon") {
    const due = (data?.items ?? []).filter((r) => !alreadyOn.includes(r.product_id));
    const worth = due.reduce((n, r) => n + r.value, 0);
    const late = due.filter((r) => r.days_overdue > 0).length;
    const label = due.length
      ? `${due.length} repeat${due.length === 1 ? "" : "s"} due \u00b7 ${money(worth)}`
        + (late ? ` \u00b7 ${late} overdue` : "")
      : "No repeats due";
    return (
      <button type="button"
              className={`lane-tool is-repeats${due.length ? (late ? " is-warn" : " is-counted") : ""}`}
              disabled={due.length === 0} onClick={onOpen} title={label} aria-label={label}>
        <ArrowClockwise size={15} weight="bold" />
        {due.length > 0 && <span className="lane-tool-count">{due.length}</span>}
      </button>
    );
  }

  if (!data || data.items.length === 0) return null;

  const outstanding = data.items.filter((r) => !alreadyOn.includes(r.product_id));
  if (outstanding.length === 0) return null;

  const worth = outstanding.reduce((n, r) => n + r.value, 0);

  if (variant === "chip") {
    return (
      <button type="button"
              className={`ctx-chip rd-chip${data.overdue ? " is-overdue" : ""}`}
              onClick={onOpen}
              title={`${money(worth)} on the shelf they have not collected`
                + (data.overdue ? ` · ${data.overdue} already overdue` : "")}>
        <ArrowClockwise size={13} weight="bold" />
        {outstanding.length} repeat{outstanding.length === 1 ? "" : "s"} due · {money(worth)}
        {data.overdue > 0 && <span className="ctx-chip-sub">&nbsp;· {data.overdue} overdue</span>}
      </button>
    );
  }

  return (
    <section className={`rd${data.overdue ? " is-overdue" : ""}`}>
      <div className="rd-head">
        <div>
          <b>
            <ArrowClockwise size={15} weight="bold" />{" "}
            {outstanding.length} repeat{outstanding.length === 1 ? "" : "s"} due
            for this patient
          </b>
          <span className="muted small">
            {money(worth)} on the shelf they have not collected
            {data.overdue > 0 && ` · ${data.overdue} already overdue`}
          </span>
        </div>
      </div>

      {data.cannot_supply > 0 && (
        <p className="rd-short">
          <Warning size={14} weight="fill" />
          {data.cannot_supply} of these cannot be supplied from stock today.
          That is the one kind of lost repeat the pharmacy causes itself — order
          it now rather than finding out from a report next month.
        </p>
      )}

      <ul className="rd-list">
        {outstanding.map((r) => (
          <li key={r.item_id} className={`rd-item row-${overdueTone(r.days_overdue)}`}>
            <div className="rd-what">
              <b>{r.product}</b>
              <span className="muted small">
                {r.quantity} · {r.dosage_instructions || "no directions recorded"}
                {" · "}{r.repeats_left} repeat{r.repeats_left === 1 ? "" : "s"} left
              </span>
            </div>
            <div className="rd-when">
              {r.days_overdue > 0
                ? <b>{r.days_overdue} day{r.days_overdue === 1 ? "" : "s"} late</b>
                : <span className="muted">due today</span>}
              <span className="muted small">{fmtDate(r.due)}</span>
            </div>
            <div className="rd-worth">
              {/* The shared chip rather than a bare figure, so this reads
                  the same as the queue, the call sheet and the repeats table.
                  Six spellings of "worth" is how two screens come to disagree
                  about money. */}
              <RepeatValue value={r.value}
                remaining={r.value * (r.repeats_left ?? 0)}
                used={(r.repeats_allowed ?? 0) - (r.repeats_left ?? 0)}
                allowed={r.repeats_allowed} />
              {!r.can_supply && (
                // Stock can be negative when more has gone out than the system
                // knew it had. "only -7 on hand" is arithmetic showing through;
                // what a dispenser needs to read is that there is none.
                <span className="badge bad">
                  {r.on_hand > 0 ? `only ${r.on_hand} on hand` : "none on hand"}
                </span>
              )}
            </div>
            <button className="btn small" onClick={() => onAdd(r)}
                    title="Put it on this script">
              <Plus size={13} weight="bold" /> Add
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
