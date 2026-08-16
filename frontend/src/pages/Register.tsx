import { useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDateTime, errorText  } from "../api";
import { RegisterEntry } from "../types";
import Pagination, { Paged } from "../components/Pagination";

export default function Register() {
  const [entries, setEntries] = useState<RegisterEntry[]>([]);
  const [schedule, setSchedule] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [meta, setMeta] = useState<Paged<RegisterEntry> | null>(null);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const toast = useToast();

  useEffect(() => {
    const params = new URLSearchParams();
    if (schedule) params.set("schedule", schedule);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    params.set("page", String(page));
    params.set("per_page", String(perPage));
    api
      .get<Paged<RegisterEntry>>(`/api/register/paged?${params}`)
      .then((r) => {
        setEntries(r.items);
        setMeta(r);
        if (r.page !== page) setPage(r.page);
      })
      .catch((e) => toast.error(errorText(e)));
  }, [schedule, dateFrom, dateTo, page, perPage]);

  // Narrowing the filters must return to the first page, or you land past the
  // end of a set that just got smaller.
  useEffect(() => setPage(1), [schedule, dateFrom, dateTo]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Controlled Register</h1>
          <div className="sub">Fully electronic S5 / S6 controlled-substance register — immutable audit trail</div>
        </div>
        <button className="secondary" onClick={() => window.print()}>Print register</button>
      </div>

      <div className="card">
        <div className="toolbar">
          <select value={schedule} onChange={(e) => setSchedule(e.target.value)}>
            <option value="">All schedules</option>
            <option value="5">Schedule 5</option>
            <option value="6">Schedule 6</option>
          </select>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} style={{ maxWidth: 180 }} />
          <span className="muted">to</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} style={{ maxWidth: 180 }} />
        </div>
        <table>
          <thead>
            <tr>
              <th>Date &amp; time</th><th>Substance</th><th>Sched.</th><th>Entry</th>
              <th className="num">Qty</th><th className="num">Balance</th>
              <th>Patient</th><th>Prescriber</th><th>Reference</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td>{fmtDateTime(e.created_at)}</td>
                <td><b>{e.product?.name}</b> {e.product?.strength}</td>
                <td><span className="badge sched">S{e.schedule}</span></td>
                <td><span className={`badge ${e.entry_type === "dispense" ? "warn" : e.entry_type === "receive" ? "ok" : "muted"}`}>{e.entry_type}</span></td>
                <td className="num">{e.quantity_delta > 0 ? `+${e.quantity_delta}` : e.quantity_delta}</td>
                <td className="num"><b>{e.balance_after}</b></td>
                <td>{e.patient ? `${e.patient.first_name} ${e.patient.last_name}` : "—"}</td>
                <td>{e.doctor?.name ?? "—"}</td>
                <td className="mono">{e.reference}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {meta && (
          <Pagination
            meta={meta}
            noun="register entries"
            onPage={setPage}
            onPerPage={(n) => { setPerPage(n); setPage(1); }}
          />
        )}
        {entries.length === 0 && <div className="empty">No register entries for this filter</div>}
      </div>
    </>
  );
}
