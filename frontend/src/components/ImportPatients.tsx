/** Bring a pharmacy's patient list in from wherever it already is.
 *
 *  A pharmacy arriving on this system has its patients somewhere already: the
 *  system it is leaving, a spreadsheet a receptionist has kept for nine years,
 *  or a scheme's membership file. Typing four thousand of them in is not a
 *  migration plan, it is a reason to stay where they are.
 *
 *  TWO PHASES, AND THE FIRST ONE IS MOST OF THE VALUE.
 *
 *  Choosing a file reads it and says what WOULD happen, row by row, without
 *  writing anything. That is where somebody discovers that column D is a date
 *  in American order, or that half the file is already on file. A bulk write
 *  nobody can preview is a bulk write nobody dares run.
 *
 *  The second phase is one button, and it says how many it is about to make.
 */
import { useState } from "react";
import { UploadSimple, X } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

interface Line { row: number; what: string; who: string; why: string }
interface Plan {
  applied: boolean; rows: number; new: number; already: number;
  skipped: number; unchecked: number; plan: Line[];
}

export default function ImportPatients({ onClose, onDone }: {
  onClose: () => void;
  /** Called after rows are written, so the list behind can reload. */
  onDone: () => void;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [name, setName] = useState("");
  const [reading, setReading] = useState(false);
  const toast = useToast();

  async function read(file: File) {
    setName(file.name);
    setReading(true);
    setPlan(null);
    const body = new FormData();
    body.append("file", file);
    body.append("apply", "false");
    try {
      setPlan(await api.post<Plan>("/api/patients/import", body));
    } catch (e) {
      toast.error(errorText(e, "That file could not be read."));
      setName("");
    } finally {
      setReading(false);
    }
  }

  async function write() {
    const input = document.getElementById("imp-file") as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("apply", "true");
    try {
      const done = await api.post<Plan>("/api/patients/import", body);
      toast.ok(`${done.new} patient${done.new === 1 ? "" : "s"} added.`);
      onDone();
      onClose();
    } catch (e) {
      toast.error(errorText(e, "Nothing was imported."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal imp" onClick={(e) => e.stopPropagation()}>
        <div className="imp-head">
          <h2>Bring in a patient list</h2>
          <button className="btn ghost sm" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>

        <p className="muted">
          An Excel file or a CSV. The columns can be named whatever the other
          system called them: surname, DOB, member number and the rest are all
          recognised. Nothing is written until you say so.
        </p>

        <label className="imp-drop">
          <UploadSimple size={20} />
          <span>{name || "Choose a file"}</span>
          <input id="imp-file" type="file" accept=".csv,.xlsx,.xlsm"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) read(f); }} />
        </label>

        {reading && <p className="muted">Reading it…</p>}

        {plan && (
          <>
            {/* The counts first, because that is the decision. The lines under
                them are for the row somebody does not believe. */}
            <div className="wc-bands imp-counts">
              <div className="wl-stat"><b>{plan.new}</b><span>to be added</span></div>
              <div className="wl-stat"><b>{plan.already}</b><span>already on file</span></div>
              <div className={`wl-stat${plan.skipped ? " wc-stale" : ""}`}>
                <b>{plan.skipped}</b><span>cannot be read</span>
              </div>
              {/* The one worth knowing before pressing, not after: a row with
                  no identity number cannot be checked against the list, so
                  importing this file twice would add that person twice. */}
              <div className={`wl-stat${plan.unchecked ? " wc-stale" : ""}`}>
                <b>{plan.unchecked}</b><span>cannot be checked for duplicates</span>
              </div>
            </div>

            <div className="imp-lines">
              <table className="dt">
                <thead><tr><th>Row</th><th>Who</th><th>What happens</th></tr></thead>
                <tbody>
                  {plan.plan.map((l) => (
                    <tr key={l.row}>
                      <td className="mono">{l.row}</td>
                      <td>{l.who || <span className="muted">No name</span>}</td>
                      <td>
                        <span className={`state ${l.what === "new patient" ? "ok"
                          : l.what === "skipped" ? "warn" : "idle"}`}>{l.what}</span>
                        {l.why && <span className="muted small"> · {l.why}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="modal-actions">
              <button className="btn ghost" onClick={onClose}>Not now</button>
              <BusyButton className="btn primary" onClick={write}
                          disabled={!plan.new} busyLabel="Adding them…">
                Add {plan.new} patient{plan.new === 1 ? "" : "s"}
              </BusyButton>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
