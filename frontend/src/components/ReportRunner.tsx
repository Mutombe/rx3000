/** One screen that runs every report.
 *
 *  The system we are replacing has roughly a hundred and twenty reports spread
 *  across four applications, and every one of them was built as its own window.
 *  That is why theirs are inconsistent: the date control sits somewhere
 *  different on each, some export to Excel and some only print, and a person who
 *  has learned one report has learned exactly one report.
 *
 *  Here the report describes itself — its parameters, its columns, the type of
 *  each column, and this renders whatever it is told. Learning one report
 *  teaches you all of them, and adding the hundredth costs nothing on the front
 *  end at all.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDate, money, errorText  } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { TableSkeleton } from "./Skeleton";
import { useToast } from "./Toast";
import Pagination from "./Pagination";
import Checkbox from "./Checkbox";
import Select from "./Select";
import IconButton from "./IconButton";
import {
  ArrowLeft,
  ChartBar,
  Table,
} from "@phosphor-icons/react";
import ReportChart from "./ReportChart";
import BusyButton from "./BusyButton";

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
/** Money if any charted column is money, otherwise plain numbers, so the axis
 *  and the total under it are written the way the report writes them. */
function moneyKind(columns: { kind: string }[]): string {
  return columns.some((c) => c.kind === "money") ? "money" : "number";
}

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
  const [view, setView] = useState<"table" | "chart">("table");
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
      toast.error(errorText(e, "That report could not be run."));
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
      toast.error(errorText(e, "That export could not be produced."));
    }
  }

  /** Print the report as a document, not as a photograph of this screen.
   *
   *  `window.print()` put the browser's own header, the navigation and a page
   *  break through the middle of a table onto paper, and a pharmacy handing
   *  that to an accountant is handing over a screenshot. This is the same
   *  figures on a letterhead, with the parameters it was run under stated —
   *  because a report whose date range is not printed on it is a report nobody
   *  can check a month later.
   *
   *  Every row, not the visible page. A printed report that silently stops at
   *  a hundred lines is worse than one that refuses to print.
   */
  async function printReport() {
    if (!result) return;
    setRunning(true);
    try {
      const q = new URLSearchParams(query);
      q.set("page", "1");
      // The server caps this; asking for more than it allows returns what it
      // allows, and `truncated` below says so rather than hiding it.
      q.set("per_page", "2000");
      if (sort) { q.set("sort", sort); q.set("desc", String(desc)); }
      const full = await api.get<RunResult>(`/api/reports/run/${report.key}?${q}`);
      const head = await letterhead();

      /* The parameters, written the way a person would say them. A document
         that prints "failures_only false" has put a variable on paper. A date
         goes on as a date, a switch that is off is simply not mentioned, and a
         switch that is on says what it did. */
      const stated = report.params
        .map((param) => {
          const raw = values[param.key] ?? "";
          if (raw === "" || raw === "false") return null;
          if (param.kind === "bool") return { label: param.label, value: "Yes" };
          if (param.kind === "date") return { label: param.label, value: fmtDate(raw) };
          return { label: param.label, value: raw };
        })
        .filter(Boolean) as { label: string; value: string }[];

      const truncated = full.rows.length < full.total;

      printDocument(head, {
        kind: report.title,
        meta: [
          ...stated,
          { label: "Rows", value: full.total.toLocaleString() },
          { label: "Run", value: new Date(full.generated_at).toLocaleString() },
        ],
        columns: full.columns.map((c) => ({
          key: c.key,
          label: c.header,
          numeric: c.align === "right" || c.kind === "money" || c.kind === "number",
        })),
        rows: full.rows.map((row) => Object.fromEntries(
          full.columns.map((c) => [c.key, render(row[c.key], c.kind)]))),
        totals: full.columns.some((c) => c.total)
          ? Object.fromEntries(full.columns.map((c, i) => [
              c.key,
              i === 0 ? `Total (${full.total.toLocaleString()})`
                      : c.total ? render(full.totals[c.key], c.kind) : "",
            ]))
          : undefined,
        note: [report.purpose,
               truncated
                 ? `Showing the first ${full.rows.length.toLocaleString()} of `
                   + `${full.total.toLocaleString()} rows. Export to a spreadsheet `
                   + `for the whole set.`
                 : ""].filter(Boolean).join(" "),
      });
    } catch (e) {
      toast.error(errorText(e, "That report could not be printed."));
    } finally {
      setRunning(false);
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
          <button className="btn ghost small" onClick={onBack}><ArrowLeft size={13} weight="bold" /> All reports</button>
          <h3 className="rr-title">{report.title}</h3>
          {report.purpose && <p className="muted rr-purpose">{report.purpose}</p>}
        </div>
        <div className="rr-actions">
          <BusyButton className="secondary small" onClick={() => exportAs("csv")} disabled={!result}>
            CSV
          </BusyButton>
          <BusyButton className="small" onClick={() => exportAs("xlsx")} disabled={!result}>
            Excel
          </BusyButton>
          <IconButton action="print" onClick={printReport} disabled={!result} />
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
                <Select
                  value={String(values[p.key])}
                  onChange={(__value) => { setValues((v) => ({ ...v, [p.key]: __value })); setPage(1); }}
                  options={[...(options[p.key] ?? [{ value: "", label: "All" }]).map((o) => ({ value: String(String(o.value)), label: o.label }))]}
                />
              ) : p.kind === "bool" ? (
                <Checkbox
                  checked={values[p.key] === "true"}
                  onChange={(v) => setValues((cur) => ({ ...cur, [p.key]: String(v) }))}
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
          {/* Same rows, two readings. The table answers "what exactly", the
              chart answers "what shape", and a report that can only be read one
              way makes somebody export it to find out the other. */}
          <div className="view-switch" role="tablist" aria-label="How to read this report">
            {(["table", "chart"] as const).map((v) => (
              <button
                key={v}
                role="tab"
                aria-selected={view === v}
                className={view === v ? "on" : ""}
                onClick={() => setView(v)}
              >
                {v === "table" ? <Table size={14} weight="bold" /> : <ChartBar size={14} weight="bold" />}
                {v === "table" ? "Table" : "Chart"}
              </button>
            ))}
          </div>

          {view === "chart" && (
            <ReportChart
              columns={result.columns}
              rows={result.rows}
              format={(n) => render(n, moneyKind(result.columns)) as string}
            />
          )}

          <div className="rr-scroll" hidden={view === "chart"}>
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
                {result.rows.map((row, i) => {
                  // Where the report says this row leads. A report that names a
                  // product and then makes you go and search for it has answered
                  // half a question.
                  const to = row._drill as string | undefined;
                  return (
                    <tr
                      key={i}
                      className={to ? "is-drillable" : undefined}
                      onClick={to ? () => navigate(to) : undefined}
                      // Reachable without a mouse, since a row is now an action.
                      tabIndex={to ? 0 : undefined}
                      role={to ? "link" : undefined}
                      onKeyDown={to ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          navigate(to);
                        }
                      } : undefined}
                    >
                      {result.columns.map((c) => (
                        <td key={c.key} className={c.align === "right" ? "st-amount mono" : ""}>
                          {render(row[c.key], c.kind)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
              {/* Always shown, even when no column is totalled. The row count
                  is the footer's first job and a statement has no meaningful
                  column sum — dropping the footer with the totals took the
                  count away with it and left the reader unable to see how much
                  had matched. */}
              {(
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
