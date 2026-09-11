/** What this patient has been prescribed and what they have been given.
 *
 *  Opened from the patient box on the dispensary, so the question "have they
 *  had this before, and when" is answered without leaving the script being
 *  built. Two tables, because they are two different records:
 *
 *    Dispensed  what actually went over the counter — medicine, quantity,
 *               directions, new or repeat, the script, who handed it over
 *    Scripts    what was written — date, Rx, prescriber, medicines, how many
 *               repeats are used, and where the script stands
 *
 *  Dispensed opens first: at the counter, what somebody took home matters more
 *  than what they were once prescribed. Rows are read here, not followed — a
 *  link out of the dispensary would drop the script on the screen behind it.
 */
import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import type { Patient, Prescription } from "../types";

interface HistoryLine {
  id: number;
  date: string;
  collected_at: string | null;
  product: string;
  strength: string;
  quantity: number;
  dosage: string;
  is_repeat: boolean;
  rx_number: string;
  dispensed_by: string;
}

type Tab = "dispensed" | "scripts";

/** Placeholder rows in the table's own columns, so the table is the table's
 *  size before a single row has arrived. Widths follow what each column holds. */
const SKELETON: Record<Tab, { head: string[]; num: number[]; widths: string[] }> = {
  dispensed: {
    head: ["When", "Medicine", "Qty", "Directions", "Type", "Rx", "By"],
    num: [2],
    widths: ["70%", "85%", "35%", "90%", "55%", "80%", "60%"],
  },
  scripts: {
    head: ["Date", "Rx", "Prescriber", "Medicines", "Repeats", "Status"],
    num: [4],
    widths: ["70%", "80%", "75%", "90%", "40%", "50%"],
  },
};

function SkeletonTable({ tab }: { tab: Tab }) {
  const shape = SKELETON[tab];
  return (
    <table className="pt-table" aria-busy="true" aria-label="Loading">
      <thead>
        <tr>{shape.head.map((h, i) => (
          <th key={h} className={shape.num.includes(i) ? "num" : undefined}>{h}</th>
        ))}</tr>
      </thead>
      <tbody>
        {Array.from({ length: 8 }).map((_, r) => (
          <tr key={r} className="is-skel">
            {shape.widths.map((w, i) => (
              <td key={i} className={shape.num.includes(i) ? "num" : undefined}>
                <span className="skel" style={{ width: w }} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function PatientHistoryModal({ patient, onClose }: {
  patient: Patient;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("dispensed");
  const [lines, setLines] = useState<HistoryLine[] | null>(null);
  const [scripts, setScripts] = useState<Prescription[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    api.get<HistoryLine[]>(`/api/reports/patient/${patient.id}/history`)
      .then((r) => { if (live) setLines(r); })
      .catch((e) => { if (live) { setLines([]); setError(e.message); } });
    api.get<Prescription[]>(`/api/prescriptions?patient_id=${patient.id}&limit=50`)
      .then((r) => { if (live) setScripts(r); })
      .catch((e) => { if (live) { setScripts([]); setError(e.message); } });
    return () => { live = false; };
  }, [patient.id]);

  const last = lines && lines.length ? lines[0].date : null;
  const name = `${patient.first_name} ${patient.last_name}`;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`History: ${name}`}
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal pt-modal pt-history">
        <h2>
          Prescription history
          <span className="disp-entry-of">{name} · ID {patient.id_number || "not on file"}</span>
        </h2>

        {error && <div className="alert error">{error}</div>}

        <div className="fin-stats">
          <div className="fin-stat"><b>{lines ? lines.length : <span className="skel skel-num" />}</b><span>dispensed</span></div>
          <div className="fin-stat"><b>{scripts ? scripts.length : <span className="skel skel-num" />}</b><span>scripts</span></div>
          <div className="fin-stat"><b>{lines === null ? <span className="skel skel-num is-wide" /> : last ? fmtDate(last) : "—"}</b><span>last dispensed</span></div>
        </div>

        <div className="seg pt-tabs" role="tablist" aria-label="Which record">
          <button type="button" role="tab" aria-selected={tab === "dispensed"}
                  className={tab === "dispensed" ? "on" : ""} onClick={() => setTab("dispensed")}>
            Dispensed
          </button>
          <button type="button" role="tab" aria-selected={tab === "scripts"}
                  className={tab === "scripts" ? "on" : ""} onClick={() => setTab("scripts")}>
            Scripts
          </button>
        </div>

        <div className="pt-scroll">
          {tab === "dispensed" ? (
            lines === null ? <SkeletonTable tab="dispensed" />
              : lines.length === 0 ? <p className="pt-empty">Nothing has been dispensed to {patient.first_name} yet.</p>
              : (
                <table className="pt-table">
                  <thead>
                    <tr>
                      <th>When</th><th>Medicine</th><th className="num">Qty</th>
                      <th>Directions</th><th>Type</th><th>Rx</th><th>By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l) => {
                      const med = `${l.product} ${l.strength || ""}`.trim();
                      return (
                        <tr key={l.id}>
                          <td className="nowrap">{fmtDate(l.date)}</td>
                          <td className="pt-clip" title={med}><b>{med}</b></td>
                          <td className="num">{l.quantity}</td>
                          <td className="pt-clip" title={l.dosage}>{l.dosage || <span className="muted">—</span>}</td>
                          <td>
                            <span className={`badge ${l.is_repeat ? "muted" : "ok"}`}>
                              {l.is_repeat ? "Repeat" : "New"}
                            </span>
                          </td>
                          <td className="mono nowrap">{l.rx_number || "—"}</td>
                          <td className="pt-clip" title={l.dispensed_by}>{l.dispensed_by || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )
          ) : (
            scripts === null ? <SkeletonTable tab="scripts" />
              : scripts.length === 0 ? <p className="pt-empty">No scripts on file for {patient.first_name}.</p>
              : (
                <table className="pt-table">
                  <thead>
                    <tr>
                      <th>Date</th><th>Rx</th><th>Prescriber</th>
                      <th>Medicines</th><th className="num">Repeats</th><th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scripts.map((rx) => {
                      const meds = (rx.items ?? [])
                        .map((i: any) => `${i.product?.name ?? ""} ${i.product?.strength ?? ""}`.trim())
                        .filter(Boolean).join(", ");
                      const used = (rx.items ?? []).reduce((n: number, i: any) => n + (i.repeats_used || 0), 0);
                      const allowed = (rx.items ?? []).reduce((n: number, i: any) => n + (i.repeats_allowed || 0), 0);
                      return (
                        <tr key={rx.id}>
                          <td className="nowrap">{fmtDate((rx as any).date_prescribed)}</td>
                          <td className="mono nowrap">{rx.rx_number || (rx as any).draft_ref || `#${rx.id}`}</td>
                          <td className="pt-clip" title={(rx as any).doctor?.name ?? ""}>
                            {(rx as any).doctor?.name ?? <span className="muted">—</span>}
                          </td>
                          <td className="pt-clip" title={meds}>{meds || <span className="muted">—</span>}</td>
                          <td className="num">{allowed ? `${used}/${allowed}` : "—"}</td>
                          <td>
                            <span className={`badge ${(rx as any).status === "draft" ? "warn" : "muted"}`}>
                              {(rx as any).status}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )
          )}
        </div>

        <div className="disp-edit-actions">
          <span className="finish-spacer" />
          <button type="button" className="btn primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
