/** Fiscalisation: the trading day, and proof that every receipt was filed.
 *
 *  This existed as nine endpoints and no screen. In Zimbabwe that is not a
 *  missing convenience — a pharmacy may not legally trade unfiscalised, and a
 *  fiscal day that is never closed files no Z-report. The API could open and
 *  close a day, requeue receipts the authority rejected and walk the hash chain;
 *  nobody could reach any of it.
 *
 *  Ordered by what someone is here to do. Opening and closing the day is the
 *  daily act, so it is at the top and unmissable. Everything below it is
 *  evidence: queued and rejected receipts, the chain, and the history of closed
 *  days with their Z-report references.
 *
 *  The route — who actually files with ZIMRA — is stated rather than assumed.
 *  There is no driver to install, and which of the three arrangements a pharmacy
 *  is on is a decision they make before this software arrives. A screen that
 *  hides that behind the word "fiscalised" invites a pharmacy to believe it is
 *  compliant because a tick is green.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDateTime, money } from "../api";
import { useConfirm } from "../components/Confirm";
import { TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import Pagination, { Paged } from "../components/Pagination";
import Select from "../components/Select";
import { EntityLink } from "../components/Filters";

interface FiscalReceipt {
  id: number; sale_id: number; receipt_type: string; global_counter: number;
  receipt_counter: number; currency_code: string; total: number;
  vat_amount: number; status: string; submitted_at: string | null;
  response_message: string; verification_url: string; created_at: string;
  reverses_receipt_id: number | null;
}

/** What a receipt register is opened to answer. Credit notes first, because
 *  that is what an auditor asks about and what a manager checks up on. */
const FILTERS = [
  { value: "", label: "Every receipt" },
  { value: "type:credit_note", label: "Credit notes only" },
  { value: "status:queued", label: "Waiting to file" },
  { value: "status:rejected", label: "Refused by ZIMRA" },
  { value: "status:accepted", label: "Accepted" },
];

interface Route {
  route: string; who_files: string; suits: string; setup: string;
}
interface OpenDay {
  id: number; day_number: number; opened_at: string;
  receipt_count: number; total_sales: number; total_vat: number;
  total_credit_notes: number;
}
interface Status {
  required: boolean;
  regime: string;
  route: Route;
  routes_available: Record<string, Route>;
  device: Record<string, unknown>;
  open_day: OpenDay | null;
  queued_receipts: number;
  rejected_receipts: number;
  chain: {
    ok: boolean; checked: number; total: number; partial: boolean;
    broken_at: number | null; reason: string;
    /** The sentence, from the server — it is the only thing that knows how
     *  much of the register was actually read. */
    says?: string;
  };
}
interface Day {
  id: number; day_number: number; status: string;
  opened_at: string; closed_at: string | null;
  receipt_count: number; total_sales: number; total_vat: number;
  total_credit_notes: number; response_ref: string; error: string;
}

/** Two months of trading days: enough to answer "when did we last close?" and
 *  short enough to read. The reports hold the full history. */
const DAY_LIMIT = 60;

export default function Fiscal() {
  const toast = useToast();
  const confirm = useConfirm();
  const [status, setStatus] = useState<Status | null>(null);
  const [days, setDays] = useState<Day[]>([]);
  const [busy, setBusy] = useState("");
  const [receipts, setReceipts] = useState<Paged<FiscalReceipt> | null>(null);
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    api.get<Status>("/api/fiscal/status")
      .then(setStatus)
      .catch((e) => toast.error(errorText(e, "The fiscal status could not be read.")));
    api.get<Day[]>(`/api/fiscal/days?limit=${DAY_LIMIT}`)
      .then(setDays)
      .catch(() => undefined);
  }, [toast]);

  useEffect(load, [load]);

  // The register is paged on the server. These are the records ZIMRA can ask
  // to see, and the hash chain only means anything if the whole of it can be
  // walked — a view that stopped at the newest 200 could not answer a question
  // about last month.
  useEffect(() => {
    const [kind, value] = filter ? filter.split(":") : ["", ""];
    const q = new URLSearchParams({ page: String(page), per_page: "25" });
    if (kind === "status") q.set("status_filter", value);
    if (kind === "type") q.set("receipt_type", value);
    api.get<Paged<FiscalReceipt>>(`/api/fiscal/receipts/paged?${q}`)
      .then(setReceipts).catch(() => setReceipts(null));
  }, [filter, page]);

  async function act(what: string, path: string, done: string) {
    setBusy(what);
    try {
      await api.post(path, {});
      toast.ok(done);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function closeDay() {
    const day = status?.open_day;
    // Closing files the Z-report, and a day cannot be reopened. The figures are
    // in the question because they are what is being filed.
    const ok = await confirm({
      title: `Close fiscal day ${day?.day_number ?? ""}?`,
      body: `This files the Z-report for ${day?.receipt_count ?? 0} receipt(s), `
          + `${money(day?.total_sales ?? 0)} in sales and ${money(day?.total_vat ?? 0)} VAT. `
          + `A closed day cannot be reopened.`,
      confirmLabel: "Close the day",
    });
    if (!ok) return;
    act("close", "/api/fiscal/day/close", "Fiscal day closed and the Z-report filed.");
  }

  if (!status) return <div className="card"><TableSkeleton cols={4} rows={6} /></div>;

  const day = status.open_day;
  const problems = status.queued_receipts + status.rejected_receipts;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Fiscalisation</h1>
          <div className="sub">
            The trading day, the receipts filed with the authority, and proof that
            none has been altered
          </div>
        </div>
      </div>

      {!status.required && (
        <p className="st-note">
          This jurisdiction does not require fiscalisation, so nothing here is
          filed. The day and the chain are still kept, because they are useful
          records on their own.
        </p>
      )}

      {/* Who files. Never implied. */}
      <div className="card">
        <h3>How this till files</h3>
        <p className="fs-route">{status.route.route}</p>
        <dl className="fs-facts">
          <div><dt>Who files</dt><dd>{status.route.who_files}</dd></div>
          <div><dt>Suits</dt><dd>{status.route.suits}</dd></div>
          <div><dt>Regime</dt><dd className="mono">{status.regime}</dd></div>
        </dl>
        <p className="muted small">{status.route.setup}</p>
      </div>

      <div className="card">
        <h3>The trading day</h3>
        {day ? (
          <>
            <div className="fs-day">
              <div>
                <span className="fs-daynum">Day {day.day_number}</span>
                <span className="badge ok">open</span>
              </div>
              <div className="muted">Opened {fmtDateTime(day.opened_at)}</div>
            </div>
            <div className="stat-row">
              <div className="stat"><span className="stat-label">Receipts</span>
                <span className="stat-value">{day.receipt_count}</span></div>
              <div className="stat"><span className="stat-label">Sales</span>
                <span className="stat-value">{money(day.total_sales)}</span></div>
              <div className="stat"><span className="stat-label">VAT</span>
                <span className="stat-value">{money(day.total_vat)}</span></div>
              <div className="stat"><span className="stat-label">Credit notes</span>
                <span className="stat-value">{money(day.total_credit_notes)}</span></div>
            </div>
            <div className="cu-actions">
              <button className="btn primary" disabled={busy === "close"} onClick={closeDay}>
                {busy === "close" ? "Closing…" : "Close the day and file the Z-report"}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="muted">
              No day is open. Sales cannot be fiscalised until one is, so this is
              the first thing to do when the pharmacy opens.
            </p>
            <div className="cu-actions">
              <button
                className="btn primary" disabled={busy === "open"}
                onClick={() => act("open", "/api/fiscal/day/open", "Fiscal day opened.")}
              >
                {busy === "open" ? "Opening…" : "Open the trading day"}
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h3>Receipts waiting or refused</h3>
        {problems === 0 ? (
          <p className="st-note is-ok">
            Every receipt has been filed and accepted.
          </p>
        ) : (
          <>
            <div className="stat-row">
              <div className="stat">
                <span className="stat-label">Queued</span>
                <span className="stat-value">{status.queued_receipts}</span>
              </div>
              <div className="stat">
                <span className="stat-label">Rejected</span>
                <span className={`stat-value${status.rejected_receipts ? " is-bad" : ""}`}>
                  {status.rejected_receipts}
                </span>
              </div>
            </div>
            <p className="muted small">
              Queued receipts are sales made while the authority was unreachable —
              trading continues and they file when it returns. Rejected ones were
              refused and need looking at; they do not clear themselves.
            </p>
            <div className="cu-actions">
              <button
                className="btn" disabled={busy === "flush"}
                onClick={() => act("flush", "/api/fiscal/flush", "Queued receipts re-filed.")}
              >
                {busy === "flush" ? "Filing…" : "File the queue now"}
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h3>Receipt chain</h3>
        {/* Each receipt carries the hash of the one before it, so a deleted or
            edited receipt breaks the chain at a known point. That is the whole
            evidentiary value, and it is worth stating what "ok" means. */}
        {/* The sentence comes from the server now, because the server is the
            only thing that knows how much it actually read.

            This used to be assembled here as "All N receipts verify" — and N
            was the CAPPED count, from a check that read the first five
            thousand. So a register of twelve thousand reported a clean bill
            over five thousand of the oldest receipts, and every recent one,
            which is the only kind anybody edits, went unchecked under a
            sentence promising otherwise. */}
        <p className={`st-note ${status.chain.ok
          ? (status.chain.partial ? "is-warn" : "is-ok") : "is-bad"}`}>
          {status.chain.says
            ?? (status.chain.ok
              ? `${status.chain.checked.toLocaleString()} receipts verify.`
              : `The chain breaks at receipt ${status.chain.broken_at}. `
                + `${status.chain.reason}`)}
        </p>
      </div>

      {/* The register itself. Everything above summarises it; nothing until now
          could show a single receipt. */}
      <div className="card">
        <div className="card-head">
          <h3>Receipt register</h3>
          <Select value={filter}
                  onChange={(v) => { setFilter(v); setPage(1); }}
                  options={FILTERS} />
        </div>
        {!receipts || receipts.items.length === 0 ? (
          <div className="empty">
            {filter
              ? "No receipt matches that."
              : "No receipt has been filed yet."}
          </div>
        ) : (
          <>
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>No.</th><th>Type</th><th>Filed</th>
                    <th className="num">Total</th><th className="num">VAT</th>
                    <th>Status</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {receipts.items.map((r) => (
                    <tr key={r.id} className={r.status === "rejected" ? "row-flag" : ""}>
                      <td className="mono">
                        {r.global_counter}
                        {r.reverses_receipt_id && (
                          <div className="muted small">reverses one earlier</div>
                        )}
                      </td>
                      <td>
                        {r.receipt_type === "credit_note"
                          ? <span className="badge warn">credit note</span>
                          : "sale"}
                      </td>
                      <td className="small">
                        {r.submitted_at ? fmtDateTime(r.submitted_at)
                          : <span className="muted">not filed</span>}
                      </td>
                      <td className="num">{money(r.total)}</td>
                      <td className="num muted">{money(r.vat_amount)}</td>
                      <td>
                        <span className={`badge ${r.status === "accepted" ? "ok"
                          : r.status === "rejected" ? "danger" : "warn"}`}>
                          {r.status}
                        </span>
                        {r.status === "rejected" && r.response_message && (
                          <div className="muted small wrap">{r.response_message}</div>
                        )}
                      </td>
                      <td className="actions">
                        {r.sale_id && (
                          <EntityLink to={`/sales/${r.sale_id}`}>
                            <button className="btn small secondary">The sale</button>
                          </EntityLink>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination meta={receipts} onPage={setPage} noun="receipts" />
          </>
        )}
      </div>

      <div className="card">
        <h3>Closed days</h3>
        {days.length === 0 ? (
          <div className="empty">No fiscal days yet.</div>
        ) : (
          <>
          {/* The endpoint caps at what was asked for, and a full page reads as
              the whole history. Two months of trading days is the right amount to
              show; saying so is what stops it being a silent truncation. */}
          {days.length >= DAY_LIMIT && (
            <p className="muted small">
              The {DAY_LIMIT} most recent days. Older ones are in the fiscal
              reports.
            </p>
          )}
          <div className="cu-scroll">
            <table>
              <thead>
                <tr>
                  <th>Day</th><th>Opened</th><th>Closed</th>
                  <th className="num">Receipts</th><th className="num">Sales</th>
                  <th className="num">VAT</th><th className="num">Credit notes</th>
                  <th>Z-report</th>
                </tr>
              </thead>
              <tbody>
                {days.map((d) => (
                  <tr key={d.id}>
                    <td className="mono">{d.day_number}</td>
                    <td>{fmtDateTime(d.opened_at)}</td>
                    <td>
                      {d.closed_at ? fmtDateTime(d.closed_at)
                        : <span className="badge ok">open</span>}
                    </td>
                    <td className="num">{d.receipt_count}</td>
                    <td className="num">{money(d.total_sales)}</td>
                    <td className="num">{money(d.total_vat)}</td>
                    <td className="num">{money(d.total_credit_notes)}</td>
                    <td>
                      {d.error
                        ? <span className="badge danger" title={d.error}>failed</span>
                        : d.response_ref
                          ? <span className="mono">{d.response_ref}</span>
                          : <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>
    </>
  );
}
