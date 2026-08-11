/** Governed data table.
 *
 *  One component owns how every list in RX3000 behaves: how much of a value is
 *  shown before it is clamped, how many rows appear at once, how the set is
 *  sorted and filtered, and where a row goes when you click it. Screens declare
 *  columns; they do not re-implement table mechanics.
 */
import { ReactNode, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Select from "./Select";

export interface Column<T> {
  key: string;
  header: string;
  /** Cell content. Falls back to the raw field value when omitted. */
  render?: (row: T) => ReactNode;
  /** Value used for sorting and for the plain-text search index. */
  value?: (row: T) => string | number;
  align?: "left" | "right" | "center";
  sortable?: boolean;
  /** Clamp the cell to this many characters, full text on hover. */
  truncate?: number;
  width?: number;
  /** Column total shown in the footer when `totals` is on. */
  total?: (row: T) => number;
  totalRender?: (sum: number) => ReactNode;
}

type Density = "compact" | "comfortable" | "spacious";
const DENSITIES: Density[] = ["compact", "comfortable", "spacious"];
const PAGE_SIZES = [10, 25, 50, 100];

/** Clamp a long value and keep the whole thing available on hover. */
export function Truncate({ text, at = 40 }: { text: string; at?: number }) {
  if (!text) return <span className="muted">—</span>;
  if (text.length <= at) return <>{text}</>;
  return <span title={text}>{text.slice(0, at - 1).trimEnd()}…</span>;
}

function defaultValue<T>(row: T, key: string) {
  const v = (row as any)[key];
  return v === null || v === undefined ? "" : v;
}

export default function DataTable<T>({
  columns, rows, rowKey, rowHref, onRowClick, empty = "Nothing to show",
  toolbar, totals = false, initialSort, pageSize: initialPageSize = 25, dense, server,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  /** Row click navigates here — this is what makes every row a record. */
  rowHref?: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
  /** Filter controls rendered above the table. */
  toolbar?: ReactNode;
  totals?: boolean;
  initialSort?: { key: string; dir: "asc" | "desc" };
  pageSize?: number;
  dense?: boolean;
  /** Server-side paging.
   *
   *  When present, `rows` is one page that the server has already sliced, and
   *  this table must not slice it again — otherwise the inner pager reports
   *  "Page 1 of 1" over fifty rows while thousands exist, which is a second
   *  pager contradicting the first. Passing this switches the footer to the
   *  server's numbers and hands the controls back to the caller.
   *
   *  Sorting also changes meaning here: sorting one page of a large set sorts
   *  the wrong thing, so column sort is disabled unless `onSort` is supplied to
   *  re-query the server. Silently sorting fifty of five thousand rows would be
   *  a lie the user cannot see.
   */
  server?: {
    total: number;
    page: number;
    pages: number;
    per_page: number;
    showing_from: number;
    showing_to: number;
    onPage: (page: number) => void;
    onPerPage?: (size: number) => void;
    onSort?: (key: string, dir: "asc" | "desc") => void;
  };
}) {
  const navigate = useNavigate();
  const [sort, setSort] = useState(initialSort ?? null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [density, setDensity] = useState<Density>(() => {
    if (dense) return "compact";
    try { return (localStorage.getItem("rx3000_density") as Density) || "comfortable"; }
    catch { return "comfortable"; }
  });

  function cycleDensity() {
    const next = DENSITIES[(DENSITIES.indexOf(density) + 1) % DENSITIES.length];
    setDensity(next);
    try { localStorage.setItem("rx3000_density", next); } catch { /* private mode */ }
  }

  // Any change to the underlying set can shrink the page count — go back to
  // page one rather than stranding the user on a page that no longer exists.
  useEffect(() => { if (!server) setPage(1); }, [rows.length, pageSize, server]);

  const sorted = useMemo(() => {
    // The server has already ordered this page; re-sorting it here would
    // only shuffle the rows in hand.
    if (server || !sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    const read = (r: T) => (col.value ? col.value(r) : defaultValue(r, col.key));
    return [...rows].sort((a, b) => {
      const x = read(a), y = read(b);
      if (typeof x === "number" && typeof y === "number") {
        return sort.dir === "asc" ? x - y : y - x;
      }
      const cmp = String(x).localeCompare(String(y), undefined, { numeric: true });
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [rows, sort, columns, server]);

  const pageCount = server ? server.pages : Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = server ? server.page : Math.min(page, pageCount);
  // The server already sliced this page. Slicing again would hide rows the
  // server deliberately sent.
  const view = server ? sorted : sorted.slice((current - 1) * pageSize, current * pageSize);

  const sums = useMemo(() => {
    if (!totals) return {};
    const out: Record<string, number> = {};
    columns.forEach((c) => {
      if (c.total) out[c.key] = sorted.reduce((s, r) => s + (c.total!(r) || 0), 0);
    });
    return out;
  }, [sorted, columns, totals]);

  // A column is only really sortable if sorting it would sort the whole set.
  // On a server-paged table without `onSort`, it would reorder the fifty rows
  // in hand and present the result as "sorted by price" — visibly plausible and
  // completely wrong. Better to offer no sort than a false one.
  const canSort = (col: Column<T>) => !!col.sortable && (!server || !!server.onSort);

  function toggleSort(col: Column<T>) {
    if (!canSort(col)) return;
    const next: { key: string; dir: "asc" | "desc" } =
      sort?.key === col.key
        ? { key: col.key, dir: sort.dir === "asc" ? "desc" : "asc" }
        : { key: col.key, dir: "asc" };
    setSort(next);
    // Let the server re-query; sorting in the browser would only touch this page.
    if (server?.onSort) server.onSort(next.key, next.dir);
  }

  function open(row: T) {
    if (onRowClick) return onRowClick(row);
    if (rowHref) navigate(rowHref(row));
  }

  const clickable = Boolean(rowHref || onRowClick);

  return (
    <div className="card datatable">
      <div className="dt-toolbar">
        <div className="dt-filters">{toolbar}</div>
        <div className="dt-tools">
          <span className="muted dt-count">
            {sorted.length} record{sorted.length === 1 ? "" : "s"}
          </span>
          <button className="ghost small" onClick={cycleDensity} title={`Row height: ${density}`}>
            {density === "compact" ? "▤" : density === "comfortable" ? "▥" : "▦"}
          </button>
        </div>
      </div>

      <div className="dt-scroll">
        <table className={`dt dt-${density}`}>
          <thead>
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  className={`${c.align === "right" ? "num" : ""}${canSort(c) ? " sortable" : ""}`}
                  style={c.width ? { width: c.width } : undefined}
                  onClick={() => toggleSort(c)}
                  aria-sort={sort?.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
                >
                  {c.header}
                  {canSort(c) && (
                    <span className="dt-sort">
                      {sort?.key === c.key ? (sort.dir === "asc" ? "▲" : "▼") : "⇅"}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.map((row) => (
              <tr
                key={rowKey(row)}
                className={clickable ? "row-click" : undefined}
                onClick={clickable ? () => open(row) : undefined}
              >
                {columns.map((c) => {
                  const raw = c.render
                    ? c.render(row)
                    : c.truncate
                      ? <Truncate text={String(defaultValue(row, c.key))} at={c.truncate} />
                      : String(defaultValue(row, c.key));
                  return (
                    <td key={c.key} className={c.align === "right" ? "num" : c.align === "center" ? "center" : ""}>
                      {raw}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
          {totals && view.length > 0 && (
            <tfoot>
              <tr>
                {columns.map((c, i) => (
                  <td key={c.key} className={c.align === "right" ? "num" : ""}>
                    {c.total !== undefined && sums[c.key] !== undefined
                      ? (c.totalRender ? c.totalRender(sums[c.key]) : sums[c.key].toLocaleString("en-ZA"))
                      : i === 0 ? "Total" : ""}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {sorted.length === 0 && <div className="empty">{empty}</div>}

      {/* Server-paged: always shown, even on a single page, because the count is
          the thing that confirms nothing is hidden. Client-paged: only when
          there is more than one page, since the row count is already visible. */}
      {(server || sorted.length > pageSize) && (
        <div className="dt-pager">
          <span className="muted">
            {server
              ? `${server.showing_from}–${server.showing_to} of ${server.total.toLocaleString()}`
              : `${(current - 1) * pageSize + 1}–${Math.min(current * pageSize, sorted.length)} of ${sorted.length}`}
          </span>
          <div className="dt-pager-controls">
            <span className="dt-pagesize">
              <Select
                value={String(server ? server.per_page : pageSize)}
                onChange={(v) =>
                  server ? server.onPerPage?.(Number(v)) : setPageSize(Number(v))}
                ariaLabel="Rows per page"
                options={PAGE_SIZES.map((n) => ({ value: String(n), label: `${n} per page` }))}
              />
            </span>
            <button className="ghost small" disabled={current <= 1}
              onClick={() => (server ? server.onPage(current - 1) : setPage(current - 1))}>‹</button>
            <span className="muted">Page {current} of {pageCount}</span>
            <button className="ghost small" disabled={current >= pageCount}
              onClick={() => (server ? server.onPage(current + 1) : setPage(current + 1))}>›</button>
          </div>
        </div>
      )}
    </div>
  );
}
