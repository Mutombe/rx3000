import { useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDate, fmtDateTime, errorText  } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { RegisterEntry } from "../types";
import Pagination, { Paged } from "../components/Pagination";
import Select from "../components/Select";

import { EntityLink } from "../components/Filters";
import { Refreshable, TableSkeleton } from "../components/Skeleton";

/** One label or script printed a second time. */
interface Reprint {
  id: number; kind: string; prescription_id: number | null;
  rx_number: string; sale_id: number | null; reason: string;
  printed_by: string; printed_at: string;
}

export default function Register() {
  const [entries, setEntries] = useState<RegisterEntry[]>([]);
  const [schedule, setSchedule] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [meta, setMeta] = useState<Paged<RegisterEntry> | null>(null);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [reprints, setReprints] = useState<Reprint[]>([]);
  const [loading, setLoading] = useState(true);
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
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, [schedule, dateFrom, dateTo, page, perPage]);

  // Narrowing the filters must return to the first page, or you land past the
  // end of a set that just got smaller.
  useEffect(() => setPage(1), [schedule, dateFrom, dateTo]);

  // The reprint log, which belongs beside the register rather than in a
  // settings screen: its own endpoint says to read it "when a count does not
  // add up", and the count that does not add up is the one on this page.
  useEffect(() => {
    api.get<Reprint[]>("/api/reprints?kind=label&limit=50")
      .then(setReprints).catch(() => setReprints([]));
  }, []);

  /** The register as a document, because an inspector may ask for it on paper.
   *
   *  This is a statutory record. A screen print of it — browser chrome, the
   *  navigation, a table cut through the middle by a page break — is not a
   *  register, and an inspector handed one draws exactly the conclusion you
   *  would expect about the rest of the controls.
   *
   *  The whole filtered range prints, not the visible page: a controlled-drugs
   *  register that stops at row twenty-five is not a register at all.
   */
  async function printRegister() {
    try {
      const q = new URLSearchParams();
      if (schedule) q.set("schedule", String(schedule));
      if (dateFrom) q.set("date_from", dateFrom);
      if (dateTo) q.set("date_to", dateTo);
      // `limit`, not `per_page`: this endpoint answers with a plain list. Set
      // far above any real month so the printed register is the whole filtered
      // range rather than the page on screen.
      q.set("limit", "2000");
      const rows = await api.get<RegisterEntry[]>(`/api/register?${q}`);
      const head = await letterhead();
      printDocument(head, {
        kind: "Controlled substances register",
        meta: [
          { label: "Schedule", value: schedule ? `S${schedule}` : "5 and 6" },
          { label: "From", value: dateFrom ? fmtDate(dateFrom) : "the beginning" },
          { label: "To", value: dateTo ? fmtDate(dateTo) : "today" },
          { label: "Entries", value: String(rows.length) },
        ],
        columns: [
          { key: "when", label: "Date and time", width: "32mm" },
          { key: "substance", label: "Substance" },
          { key: "sched", label: "Sch.", width: "12mm" },
          { key: "type", label: "Entry", width: "22mm" },
          { key: "qty", label: "Qty", numeric: true, width: "16mm" },
          { key: "balance", label: "Balance", numeric: true, width: "18mm" },
          { key: "patient", label: "Patient", width: "34mm" },
          { key: "prescriber", label: "Prescriber", width: "30mm" },
          { key: "reference", label: "Reference", width: "26mm" },
        ],
        rows: rows.map((e) => ({
          when: fmtDateTime(e.created_at),
          substance: `${e.product?.name ?? ""} ${e.product?.strength ?? ""}`.trim(),
          sched: `S${e.schedule}`,
          type: e.entry_type,
          qty: e.quantity_delta > 0 ? `+${e.quantity_delta}` : String(e.quantity_delta),
          balance: String(e.balance_after),
          patient: e.patient ? `${e.patient.first_name} ${e.patient.last_name}` : "—",
          prescriber: e.doctor?.name ?? "—",
          reference: e.reference,
        })),
        note: "Every entry in this register is written once and never altered. "
            + "A correction appears as a further entry, never as a change to an "
            + "existing one.",
      });
    } catch (e) {
      toast.error(errorText(e, "The register could not be printed."));
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Controlled Register</h1>
          <div className="sub">Fully electronic S5 / S6 controlled-substance register, immutable audit trail</div>
        </div>
        <button className="secondary" onClick={printRegister}>Print register</button>
      </div>

      <div className="card">
        <div className="toolbar">
          <Select
            value={String(schedule ?? "")}
            onChange={(__value) => setSchedule(__value)}
            options={[{ value: "", label: "All schedules" }, { value: "5", label: "Schedule 5" }, { value: "6", label: "Schedule 6" }]}
          />
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} style={{ maxWidth: 180 }} />
          <span className="muted">to</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} style={{ maxWidth: 180 }} />
        </div>
        <Refreshable
          loading={loading}
          hasData={entries.length > 0}
          skeleton={<TableSkeleton cols={9} rows={6}
            widths={["16ch", "18ch", "6ch", "8ch", "6ch", "8ch", "16ch", "14ch", "10ch"]} />}
        >
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
                <td><EntityLink kind="product" id={e.product?.id}><b>{e.product?.name}</b> {e.product?.strength}</EntityLink></td>
                <td><span className="badge sched">S{e.schedule}</span></td>
                <td><span className={`badge ${e.entry_type === "dispense" ? "warn" : e.entry_type === "receive" ? "ok" : "muted"}`}>{e.entry_type}</span></td>
                <td className="num">{e.quantity_delta > 0 ? `+${e.quantity_delta}` : e.quantity_delta}</td>
                <td className="num"><b>{e.balance_after}</b></td>
                <td><EntityLink kind="patient" id={e.patient?.id}>{e.patient ? `${e.patient.first_name} ${e.patient.last_name}` : "—"}</EntityLink></td>
                <td><EntityLink kind="prescriber" id={e.doctor?.id}>{e.doctor?.name ?? "—"}</EntityLink></td>
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
        {entries.length === 0 && !loading && (
          <div className="empty">
            <b>No register entries for this filter</b>
            <p>
              The controlled register records every Schedule 5 and 6 movement.
              Widen the dates or clear the schedule to see more.
            </p>
          </div>
        )}
        </Refreshable>
      </div>

      {/* A second label for a controlled substance is the easiest way to make
          one dispensing look like two. The register above counts dispensings;
          this says which of them had a sticker run twice, and why. */}
      <div className="card no-print">
        <div className="card-head">
          <h3>Labels printed again</h3>
          <span className="muted small">
            Read this when a balance above does not agree with the shelf
          </span>
        </div>
        {reprints.length === 0 ? (
          <div className="empty">
            No label has been reprinted. Every dispensing on the register was
            labelled once.
          </div>
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <th>When</th><th>Script</th><th>By</th><th>Why</th>
              </tr>
            </thead>
            <tbody>
              {reprints.map((r) => (
                <tr key={r.id}>
                  <td className="small">{fmtDateTime(r.printed_at)}</td>
                  <td className="mono">
                    {r.prescription_id ? (
                      <EntityLink kind="prescription" id={r.prescription_id}>
                        {r.rx_number || `#${r.prescription_id}`}
                      </EntityLink>
                    ) : "—"}
                  </td>
                  <td>{r.printed_by}</td>
                  <td className="wrap">
                    {r.reason || (
                      <span className="muted">no reason given</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
