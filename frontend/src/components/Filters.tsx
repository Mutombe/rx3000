/** Multi-dimensional filter controls and cross-entity hyperlinks. */
import { ReactNode } from "react";
import { Link } from "react-router-dom";
import Select from "./Select";
import { entityHref, type EntityKind } from "../entityRoutes";

export interface FilterState {
  q: string;
  from: string;
  to: string;
  /** Arbitrary named dimensions — status, category, schedule, owner… */
  dims: Record<string, string>;
}

export const emptyFilters: FilterState = { q: "", from: "", to: "", dims: {} };

export function hasAnyFilter(f: FilterState) {
  return Boolean(f.q || f.from || f.to || Object.values(f.dims).some(Boolean));
}

/** Apply the generic dimensions of a filter to a row. Screens supply the
 *  accessors; the search term is matched against every searchable field and
 *  the date range against one nominated timestamp. */
export function applyFilters<T>(rows: T[], f: FilterState, opts: {
  search?: (row: T) => (string | null | undefined)[];
  date?: (row: T) => string | null | undefined;
  dims?: Record<string, (row: T) => string | null | undefined>;
}) {
  const needle = f.q.trim().toLowerCase();
  return rows.filter((row) => {
    if (needle && opts.search) {
      const hay = opts.search(row).filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    if ((f.from || f.to) && opts.date) {
      const raw = opts.date(row);
      if (!raw) return false;
      const day = raw.slice(0, 10);
      if (f.from && day < f.from) return false;
      if (f.to && day > f.to) return false;
    }
    for (const [key, want] of Object.entries(f.dims)) {
      if (!want) continue;
      const get = opts.dims?.[key];
      if (!get) continue;
      if (String(get(row) ?? "") !== want) return false;
    }
    return true;
  });
}

export function FilterBar({ value, onChange, placeholder, showDates, dimensions, children }: {
  value: FilterState;
  onChange: (next: FilterState) => void;
  placeholder?: string;
  showDates?: boolean;
  /** Each dimension becomes its own select — combine freely. */
  dimensions?: { key: string; label: string; options: [string, string][] }[];
  children?: ReactNode;
}) {
  const set = (patch: Partial<FilterState>) => onChange({ ...value, ...patch });
  const setDim = (key: string, v: string) => onChange({ ...value, dims: { ...value.dims, [key]: v } });

  return (
    <>
      <input
        type="search"
        className="filter-search"
        placeholder={placeholder ?? "Search…"}
        value={value.q}
        onChange={(e) => set({ q: e.target.value })}
      />
      {showDates && (
        <span className="filter-range">
          <input type="date" value={value.from} onChange={(e) => set({ from: e.target.value })} title="From" />
          <span className="muted">to</span>
          <input type="date" value={value.to} onChange={(e) => set({ to: e.target.value })} title="To" />
        </span>
      )}
      {dimensions?.map((d) => (
        <span key={d.key} className="filter-dim">
          <Select
            value={value.dims[d.key] ?? ""}
            onChange={(v) => setDim(d.key, v)}
            ariaLabel={d.label}
            placeholder={`${d.label}: all`}
            options={[
              { value: "", label: `${d.label}: all` },
              ...d.options.map(([v, l]) => ({ value: v, label: l })),
            ]}
          />
        </span>
      ))}
      {children}
      {hasAnyFilter(value) && (
        <button className="ghost small" onClick={() => onChange(emptyFilters)}>Clear</button>
      )}
    </>
  );
}

/** A name in a table you can click through to the record itself.
 *
 *  Stops propagation, so it works inside a clickable row without also firing
 *  the row's own navigation.
 *
 *  Takes either an explicit `to`, or a `kind` and an `id` resolved through the
 *  route map — the second form is what most tables want, and it means a renamed
 *  route is one edit rather than eighty.
 *
 *  A missing id renders plain text rather than a link. Walk-in sales have no
 *  patient, batches may have no supplier recorded, and a hand-keyed line may
 *  name a medicine that is not in the catalogue. None of those is an error, and
 *  none of them should produce a link to `/patients/undefined`.
 */
export function EntityLink({ to, kind, id, children, muted }: {
  to?: string;
  kind?: EntityKind;
  id?: string | number | null;
  children: ReactNode;
  muted?: boolean;
}) {
  const href = to ?? (kind && id !== null && id !== undefined && id !== 0 && id !== ""
    ? entityHref(kind, id) : "");
  if (!href) return <>{children}</>;
  return (
    <Link to={href} className={`entity-link${muted ? " muted" : ""}`} onClick={(e) => e.stopPropagation()}>
      {children}
    </Link>
  );
}
