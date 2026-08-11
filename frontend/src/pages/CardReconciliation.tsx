import { ChangeEvent, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDateTime, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { CardReconciliationReport, ReconMatch, ReconStatementLine, ReconUnbanked } from "../types";

type Tab = "matched" | "mismatched" | "missing_system" | "missing_statement";

const SAMPLE = `date,auth_code,reference,amount,last4,terminal
2026-08-06,A1B2C3,675659264258,249.90,4468,SIM0001`;

export default function CardReconciliation() {
  const [csv, setCsv] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [report, setReport] = useState<CardReconciliationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "matched", label: "Matched", count: report?.matched.length },
    { key: "mismatched", label: "Amount differs", count: report?.mismatched.length },
    { key: "missing_system", label: "Not in RX3000", count: report?.missing_in_system.length },
    { key: "missing_statement", label: "Not banked", count: report?.missing_in_statement.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "matched");

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) file.text().then((t) => { setCsv(t); setReport(null); });
  }

  async function run() {
    setBusy(true); toast.error("");
    try {
      setReport(await api.post<CardReconciliationReport>("/api/pos/reconciliation/card", {
        csv_text: csv, date_from: from || null, date_to: to || null,
      }));
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  }

  const matchCols: Column<ReconMatch>[] = [
    { key: "sale_number", header: "Sale", sortable: true,
      render: (r) => <EntityLink to={`/sales/${r.sale_id}`}><span className="mono">{r.sale_number}</span></EntityLink> },
    { key: "created_at", header: "When", sortable: true,
      render: (r) => <span className="muted">{fmtDateTime(r.created_at)}</span> },
    { key: "auth_code", header: "Auth code", render: (r) => <span className="mono">{r.auth_code || "—"}</span> },
    { key: "reference", header: "Reference", truncate: 18,
      render: (r) => <span className="mono">{r.reference || "—"}</span> },
    { key: "matched_on", header: "Matched on", sortable: true,
      render: (r) => (
        <span className={`badge ${r.matched_on === "weak" ? "warn" : "ok"}`}>
          {r.matched_on}
        </span>
      ) },
    { key: "sale_total", header: "Till", align: "right", sortable: true,
      render: (r) => money(r.sale_total), total: (r) => r.sale_total, totalRender: (n) => money(n) },
    { key: "statement_amount", header: "Statement", align: "right", sortable: true,
      render: (r) => money(r.statement_amount),
      total: (r) => r.statement_amount, totalRender: (n) => money(n) },
    { key: "difference", header: "Difference", align: "right", sortable: true,
      render: (r) => (Math.abs(r.difference) < 0.005
        ? <span className="muted">—</span>
        : <b className="badge danger">{money(r.difference)}</b>),
      total: (r) => r.difference, totalRender: (n) => money(n) },
  ];

  const stmtCols: Column<ReconStatementLine>[] = [
    { key: "line", header: "Line", align: "right", sortable: true },
    { key: "date", header: "Date", sortable: true, render: (r) => r.txn_date ?? <span className="muted">—</span> },
    { key: "auth_code", header: "Auth code", render: (r) => <span className="mono">{r.auth_code || "—"}</span> },
    { key: "reference", header: "Reference", truncate: 20,
      render: (r) => <span className="mono">{r.reference || "—"}</span> },
    { key: "last4", header: "Card", render: (r) => (r.last4 ? `**** ${r.last4}` : "—") },
    { key: "terminal", header: "Terminal", render: (r) => r.terminal || "—" },
    { key: "amount", header: "Amount", align: "right", sortable: true,
      render: (r) => <b>{money(r.amount)}</b>, total: (r) => r.amount, totalRender: (n) => money(n) },
  ];

  const unbankedCols: Column<ReconUnbanked>[] = [
    { key: "sale_number", header: "Sale", sortable: true,
      render: (r) => <EntityLink to={`/sales/${r.sale_id}`}><span className="mono">{r.sale_number}</span></EntityLink> },
    { key: "created_at", header: "When", sortable: true,
      render: (r) => <span className="muted">{fmtDateTime(r.created_at)}</span> },
    { key: "auth_code", header: "Auth code",
      render: (r) => (r.auth_code
        ? <span className="mono">{r.auth_code}</span>
        : <span className="badge warn">not captured</span>) },
    { key: "terminal_id", header: "Terminal", render: (r) => r.terminal_id || "—" },
    { key: "sale_total", header: "Amount", align: "right", sortable: true,
      render: (r) => <b>{money(r.sale_total)}</b>, total: (r) => r.sale_total, totalRender: (n) => money(n) },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Card Reconciliation</h1>
          <div className="sub">Match an acquirer settlement file against the card takings on record</div>
        </div>
      </div>

      <div className="card">
        <h3>Settlement file</h3>
        <p className="muted">
          Upload or paste the acquirer's CSV. Column names are matched loosely, so
          <span className="mono"> auth_code / authcode / approval</span> and
          <span className="mono"> amount / value / total</span> are all understood.
          Lines are matched on auth code first, then reference, then a same-day amount —
          amount-only matches are flagged <span className="badge warn">weak</span> for review.
        </p>
        <div className="form-row">
          <div className="field"><label>File</label><input type="file" accept=".csv,text/csv" onChange={onFile} /></div>
          <div className="field" style={{ maxWidth: 190 }}><label>From</label>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
          <div className="field" style={{ maxWidth: 190 }}><label>To</label>
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
        </div>
        <div className="field">
          <label>CSV content</label>
          <textarea rows={5} value={csv} onChange={(e) => { setCsv(e.target.value); setReport(null); }}
            placeholder={SAMPLE} />
        </div>
        <button onClick={run} disabled={busy || !csv.trim()}>
          {busy ? "Matching…" : "Reconcile"}
        </button>
      </div>

      {report && (
        <>
          {report.warnings.length > 0 && (
            <div className="error-banner">{report.warnings.join(" · ")}</div>
          )}

          <div className="grid cols-4">
            <div className="card stat hero">
              <div className="label">Variance</div>
              <div className="value">{money(report.variance)}</div>
              <div className="hint">till {money(report.system_total)} vs bank {money(report.statement_total)}</div>
            </div>
            <div className="card stat">
              <div className="label">Matched</div>
              <div className="value">{report.matched.length}</div>
              <div className="hint">
                {report.weak_matches > 0 ? `${report.weak_matches} on amount only` : "all on auth code or reference"}
              </div>
            </div>
            <div className="card stat">
              <div className="label">Not in RX3000</div>
              <div className="value">{report.missing_in_system.length}</div>
              <div className="hint">banked but never rung up</div>
            </div>
            <div className="card stat">
              <div className="label">Not banked</div>
              <div className="value">{report.missing_in_statement.length}</div>
              <div className="hint">card sales with no settlement line</div>
            </div>
          </div>

          <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

          {tab === "matched" && (
            <DataTable columns={matchCols} rows={report.matched} rowKey={(r) => r.sale_id} totals
              initialSort={{ key: "created_at", dir: "desc" }}
              empty="Nothing matched — check the date range and the column names" />
          )}
          {tab === "mismatched" && (
            <DataTable columns={matchCols} rows={report.mismatched} rowKey={(r) => r.sale_id} totals
              empty="Every matched line agrees to the cent" />
          )}
          {tab === "missing_system" && (
            <DataTable columns={stmtCols} rows={report.missing_in_system} rowKey={(r) => r.line} totals
              empty="Every settlement line has a sale behind it" />
          )}
          {tab === "missing_statement" && (
            <DataTable columns={unbankedCols} rows={report.missing_in_statement} rowKey={(r) => r.sale_id} totals
              empty="Every card sale in this period appears on the statement" />
          )}
        </>
      )}
    </>
  );
}
