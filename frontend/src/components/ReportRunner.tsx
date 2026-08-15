/** One screen that runs every report.
 *
 *  The system we are replacing has roughly a hundred and twenty reports spread
 *  across four applications, and every one of them was built as its own window.
 *  That is why theirs are inconsistent: the date control sits somewhere
 *  different on each, some export to Excel and some only print, and a person who
 *  has learned one report has learned exactly one report.
 *
 *  Here the report describes itself — its parameters, its columns, the type of
 *  each column — and this renders whatever it is told. Learning one report
 *  teaches you all of them, and adding the hundredth costs nothing on the front
 *  end at all.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDate, money } from "../api";
import { TableSkeleton } from "./Skeleton";
import { useToast } from "./Toast";
import Pagination from "./Pagination";

export interface ParamDef {
  key: string; label: string; kind: string;
  required: boolean; default: unknown; help: string;
}
export interface ReportDef {
  key: string; title: string; module: string; purpose: string;
  step_up: boolean; params: ParamDef[];
}
interface ColumnDef {
  key: string; header: string; kind: string; align: string; total: boolean;
}
interface RunResult {
  key: string; title: string; purpose: string;
  columns: ColumnDef[];
  rows: Record<string, any>[];
  totals: Record<string, number>;
  page: number; per_page: number; total: number; pages: number;
  generated_at: string;
}

/** Format by declared type, so a figure looks the same here, in the
 *  spreadsheet and on paper. */
function render(value: any, kind: string) {
  if (value === null || value === undefined || value === "") return "—";
  switch (kind) {
    case "money": return money(Number(value));
    case "percent": return `${Number(value).toFixed(1)}%`;
    case "number": return Number(value).toLocaleString();
    case "date": return fmtDate(String(value));
    default: return String(value);
  }
}

export default function ReportRunner({
  report, onBack,
}: { report: ReportDef; onBack: () => void }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [values, setValues] = useState<Record<string, string>>({});
  const [options, setOptions] = useState<Record<string, { value: any; label: string }[]>>({});
  const [result, setResult] = useState<RunResult | null>(null);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("");
  const [desc, setDesc] = useState(false);
  const [running, setRunning] = useState(false);

  // Seed from the report's own defaults so it runs on open rather than making
  // the operator fill a form before seeing anything.
  useEffect(() => {
    const seed: Record<string, string> = {};
    report.params.forEach((p) => {
      if (p.default !== null && p.default !== undefined) seed[p.key] = String(p.default);
    });
    setValues(seed);
    setResult(null);
    setPage(1);
  }, [report.key]);

  const query = useMemo(() => {
    const q = new URLSearchParams();
    Object.entries(values).forEach(([k, v]) => { if (v !== "") q.set(k, v); });
    return q;
  }, [values]);

  const run = useCallback(async () => {
    setRunning(true);
    try {
      const q = new URLSearchParams(query);
      q.set("page", String(page));
      q.set("per_page", "100");
      if (sort) { q.set("sort", sort); q.set("desc", String(desc)); }
      setResult(await api.get<RunResult>(`/api/reports/run/${report.key}?${q}`));
    } catch (e: any) {
      toast.error(e?.message || "That report could not be run.");
      setResult(null);
    } finally {
      setRunning(false);
    }
  }, [report.key, query, page, sort, desc, toast]);

  useEffect(() => { run(); }, [run]);

  // Selects whose options come from the database.
  useEffect(() => {
    report.params.filter((p) => p.kind === "select").forEach((p) => {
      if (p.key === "branch_id" && !options[p.key]) {
        api.get<any[]>("/api/branches")
          .then((rows) => setOptions((o) => ({
            ...o,
            [p.key]: [{ value: "", label: "All branches" },
                      ...rows.map((b) => ({ value: b.id, label: b.name }))],
          })))
          .catch(() => {});
      }
    });
  }, [report.key]);

  async function exportAs(format: "xlsx" | "csv") {
    const q = new URLSearchParams(query);
    q.set("format", format);
    if (sort) { q.set("sort", sort); q.set("desc", String(desc)); }
    try {
      // Fetched rather than navigated to. A plain link cannot carry the
      // Authorization header, and the alternative — putting the token in the
      // query string — writes it into every access log and browser history it
      // passes through. So the file is fetched, turned into a blob, and handed
      // to a synthetic link.
      const blob = await api.blob(`/api/reports/export/${report.key}?${q}`);
      const url = URL.createObjectURL(blob.body);
      const link = document.createElement("a");
      link.href = url;
      link.download = blob.filename || `${report.key}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Revoked on the next tick: released immediately, Safari cancels the
      // download it has not started yet.
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e: any) {
      toast.error(e?.message || "That export could not be produced.");
    }
  }

  function toggleSort(key: string) {
    if (sort === key) setDesc((d) => !d);
    else { setSort(key); setDesc(true); }
    setPage(1);
  }

  return (
    <div className="card">
      <div className="rr-head">
        <div>
          <button className="btn ghost small" onClick={onBack}>← All reports</button>
          <h3 className="rr-title">{report.title}</h3>
          {report.purpose && <p className="muted rr-purpose">{report.purpose}</p>}
        </div>
        <div className="rr-actions">
          <button className="secondary small" onClick={() => exportAs("csv")} disabled={!result}>
            CSV
          </button>
          <button className="small" onClick={() => exportAs("xlsx")} disabled={!result}>
            Excel
          </button>
          <button className="secondary small" onClick={() => window.print()} disabled={!result}>
            Print
          </button>
        </div>
      </div>

      {report.params.length > 0 && (
        <div className="rr-params">
          {report.params.map((p) => (
            <label key={p.key} className="rr-param">
              <span>{p.label}</span>
              {p.kind === "date" ? (
                <input
                  type="date"
                  value={values[p.key] ?? ""}
                  onChange={(e) => { setValues((v) => ({ ...v, [p.key]: e.target.value })); setPage(1); }}
                />
              ) : p.kind === "select" ? (
                <select
                  value={values[p.key] ?? ""}
                  onChange={(e) => { setValues((v) => ({ ...v, [p.key]: e.target.value })); setPage(1); }}
                >
                  {(options[p.key] ?? [{ value: "", label: "All" }]).map((o) => (
                    <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
                  ))}
                </select>
              ) : p.kind === "bool" ? (
                <input
                  type="checkbox"
                  checked={values[p.key] === "true"}
                  onChange={(e) => setValues((v) => ({ ...v, [p.key]: String(e.target.checked) }))}
                />
              ) : (
                <input
                  value={values[p.key] ?? ""}
                  onChange={(e) => { setValues((v) => ({ ...v, [p.key]: e.target.value })); setPage(1); }}
                  placeholder={p.help}
                />
              )}
            </label>
          ))}
        </div>
      )}

      {!result ? (
        <TableSkeleton cols={report.params.length ? 6 : 5} rows={8} />
      ) : result.total === 0 ? (
        <div className="empty">
          Nothing matched. {report.params.length > 0 && "Try a wider date range."}
        </div>
      ) : (
        <>
          <div className="rr-scroll">
            <table className="rr-table">
              <thead>
                <tr>
                  {result.columns.map((c) => (
                    <th
                      key={c.key}
                      className={`${c.align === "right" ? "st-amount" : ""} is-sortable${
                        sort === c.key ? " is-sorted" : ""}`}
                      onClick={() => toggleSort(c.key)}
                    >
                      {c.header}
                      {sort === c.key && <span className="rr-arrow">{desc ? "▾" : "▴"}</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i}>
                    {result.columns.map((c) => (
                      <td key={c.key} className={c.align === "right" ? "st-amount mono" : ""}>
                        {render(row[c.key], c.kind)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              {Object.keys(result.totals).length > 0 && (
                <tfoot>
                  <tr>
                    {result.columns.map((c, i) => (
                      <td key={c.key} className={c.align === "right" ? "st-amount mono" : ""}>
                        {/* The footer totals every row the report matched, not
                            the hundred on this page. A footer that silently
                            totals the page is the most misleading thing a
                            report can do. */}
                        {i === 0 ? `Total (${result.total.toLocaleString()})`
                          : c.total ? render(result.totals[c.key], c.kind) : ""}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>

          {result.pages > 1 && (
            <Pagination
              meta={{
                total: result.total, page: result.page, pages: result.pages,
                per_page: result.per_page,
                showing_from: (result.page - 1) * result.per_page + 1,
                showing_to: Math.min(result.page * result.per_page, result.total),
              }}
              onPage={setPage}
              noun="rows"
            />
          )}
        </>
      )}
      {running && result && <div className="rr-running">Refreshing…</div>}
    </div>
  );
}
