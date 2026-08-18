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
  /** Clamp the cell to this many characters, full text on hover. Rarely needed
   *  now: cells clip to the column width by default, which is better than a
   *  character count because it cuts where the column actually ends. */
  truncate?: number;
  /** Let this column wrap and grow instead of clipping to one line. For the
   *  occasional column that genuinely holds a sentence. */
  wrap?: boolean;
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

/** How wide each column should be when it does not say.
 *
 *  Fixed layout is what makes a long value clip instead of stretching the table,
 *  but it divides the width equally between unsized columns — which made a
 *  product name the same 95px as a quantity.
 *
 *  Pinning the numeric columns in pixels and giving the name a percentage was the
 *  next attempt and over-subscribed the table: 5 numeric columns at 116px plus a
 *  34% name left 52px for the two columns in between, so "Sched." and "Barcode"
 *  rendered 25px wide. Absolute widths mixed with percentages cannot be reasoned
 *  about without knowing the table's width.
 *
 *  So every unsized column gets a share of one hundred percent, weighted by what
 *  it holds. Nothing can collapse, the total always adds up, and the identifier
 *  still dominates.
 */
const WEIGHT = { first: 3, text: 1.7, center: 1, right: 1.15 };

/** What each kind of column needs to be readable at all.
 *
 *  Shares alone are not enough. Eight columns sharing 956px gave every money
 *  column 90px, which clipped "$5,665,724.50" and cut the row actions in half —
 *  the layout held its shape by hiding the data, which is not the point.
 *
 *  So a table also declares the width below which it stops squeezing and starts
 *  scrolling. `.dt-scroll` already scrolls; it simply never had anything to
 *  scroll, because a fixed-layout table at width:100% cannot exceed its box. The
 *  scroll belongs to the table's container, never to the page. */
const MINIMUM = { first: 200, text: 130, center: 96, right: 136 };

function kindOf<T>(c: Column<T>, firstText: Column<T> | undefined, many: boolean) {
  if (c === firstText && many) return "first" as const;
  if (c.align === "right") return "right" as const;
  if (c.align === "center") return "center" as const;
  return "text" as const;
}

function widthFor<T>(c: Column<T>, columns: Column<T>[]): string | undefined {
  const unsized = columns.filter((x) => !x.width);
  if (!unsized.includes(c)) return undefined;
  const firstText = unsized.find((x) => x.align !== "right" && x.align !== "center");
  const weigh = (x: Column<T>) => WEIGHT[kindOf(x, firstText, unsized.length > 2)];
  const total = unsized.reduce((sum, x) => sum + weigh(x), 0);
  return `${((weigh(c) / total) * 100).toFixed(2)}%`;
}

/** The width at which the table stops squeezing and the container scrolls. */
export function minimumTableWidth<T>(columns: Column<T>[]): number {
  const unsized = columns.filter((x) => !x.width);
  const firstText = unsized.find((x) => x.align !== "right" && x.align !== "center");
  return columns.reduce((sum, c) => sum
    + (c.width ?? MINIMUM[kindOf(c, firstText, unsized.length > 2)]), 0);
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
        <table
          className={`dt dt-${density}`}
          style={{ minWidth: minimumTableWidth(columns) }}
        >
          <thead>
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  className={`${c.align === "right" ? "num" : ""}${canSort(c) ? " sortable" : ""}`}
                  // Fixed layout divides the table equally between columns that
                  // do not state a width, which left a product name the same 95px
                  // as a quantity. Numbers and dates have a natural size and text
                  // does not, so the narrow ones are pinned and the text columns
                  // share what is left — the opposite of equal, and the right way
                  // round.
                  style={{ width: c.width ?? widthFor(c, columns) }}
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
                  // Clipping is the default, not something a column has to ask
                  // for. A guard that must be remembered per column is absent
                  // from the columns nobody thought about — and those are the
                  // ones a 173-character product name lands in.
                  //
                  // The title carries the whole value, so nothing is lost, only
                  // deferred to a hover. It is only set where the text is known
                  // here; a custom `render` may return elements, and stringifying
                  // those would put "[object Object]" in a tooltip.
                  const plain = c.value
                    ? String(c.value(row))
                    : (!c.render ? String(defaultValue(row, c.key)) : "");
                  const numeric = c.align === "right";
                  return (
                    <td key={c.key} className={numeric ? "num" : c.align === "center" ? "center" : ""}>
                      {c.wrap || numeric
                        ? raw
                        : <span className="clip" title={plain || undefined}>{raw}</span>}
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
