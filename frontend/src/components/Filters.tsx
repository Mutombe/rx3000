/** Multi-dimensional filter controls and cross-entity hyperlinks. */
import { ReactNode, useMemo, useState } from "react";
import { Check } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import Select from "./Select";
import { toneClass } from "../entityTone";
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

/** A yes-or-no filter, shaped like the controls beside it.
 *
 *  It was a bare `<Checkbox>` dropped into a row of styled dropdowns, so the
 *  one filter that is not a list looked like it had been left unfinished.
 *  Worse, a tick box states one side of the choice and leaves the reader to
 *  work out the other: "Low stock only" unticked does not say "everything",
 *  it says nothing at all.
 *
 *  `aria-pressed` rather than a checkbox role, because that is what it is: a
 *  control with an on state, in a toolbar.
 */
export function FilterToggle({ checked, onChange, children, hint }: {
  checked: boolean;
  onChange: (on: boolean) => void;
  children: ReactNode;
  /** What it means when it is on, for the people who hover. */
  hint?: string;
}) {
  return (
    <button
      type="button"
      className={`filter-toggle${checked ? " on" : ""}`}
      aria-pressed={checked}
      title={hint}
      onClick={() => onChange(!checked)}
    >
      <span className="filter-tick" aria-hidden>
        {checked && <Check size={11} weight="bold" />}
      </span>
      {children}
    </button>
  );
}

export function FilterBar({ value, onChange, placeholder, showDates, dimensions, extras, children }: {
  value: FilterState;
  onChange: (next: FilterState) => void;
  placeholder?: string;
  showDates?: boolean;
  /** Each dimension becomes its own select — combine freely. */
  dimensions?: { key: string; label: string; options: [string, string][] }[];
  /** Filters this bar does not own, so that Clear tells the truth.
   *
   *  The button used to test only the search, the dates and the dimensions.
   *  A screen with its own toggle beside them — "Low stock only", "Expiring
   *  within 90 days" — could be filtering hard with no Clear offered at all,
   *  and pressing Clear when it did appear left that toggle on. A control
   *  that says it clears the filters has to clear the filters. */
  extras?: { active: boolean; clear: () => void };
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
      {(hasAnyFilter(value) || extras?.active) && (
        <button className="ghost small filter-clear"
                onClick={() => { onChange(emptyFilters); extras?.clear(); }}>
          Clear
        </button>
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
  // The colour language. A patient reads the same on the dispensing screen, in
  // the repeats table and on a claim, so it is learnt once rather than per
  // screen. See frontend/src/entityTone.ts.
  return (
    <Link to={href}
          className={`entity-link ${toneClass(kind)}${muted ? " muted" : ""}`.trim()}
          onClick={(e) => e.stopPropagation()}>
      {children}
    </Link>
  );
}

/** A search over one hand-written table's rows.
 *
 *  WHY THIS EXISTS
 *
 *  `FilterBar` is for a screen with dimensions to filter on: a status, a
 *  supplier, a date range. Twenty-two screens in this product have none of
 *  that and a single long list: the chart of accounts, a patient's dispensing
 *  history, the bags on the will-call shelf. Every one of them rendered its
 *  rows and offered no way to find one, so the answer to "is hers on the
 *  shelf" was to read 645 rows.
 *
 *  They are hand-written tables rather than `DataTable`, so there was nothing
 *  to add a search to centrally. This is the smallest piece that lets a
 *  screen add one honestly: the caller says which fields are searchable, and
 *  the count says how much of the list is being shown so a narrow search
 *  never looks like an empty table.
 */
export function useSearch<T>(
  rows: T[],
  fields: (row: T) => (string | number | null | undefined)[],
) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      fields(row).filter((v) => v !== null && v !== undefined && v !== "")
        .join(" ").toLowerCase().includes(needle));
    // `fields` is deliberately not a dependency. Callers pass an inline
    // arrow, which is a new function on every render, and including it would
    // rebuild the list on every keystroke of every other state on the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, q]);
  return { q, setQ, shown };
}

/** The control that goes with it, in the same shape as every other filter
 *  row in the product. */
export function TableSearch({ value, onChange, placeholder, shown, total, children }: {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  shown: number;
  total: number;
  children?: ReactNode;
}) {
  return (
    <div className="dt-filters">
      <input type="search" className="filter-search" value={value}
             placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)} />
      {children}
      {value && (
        <button type="button" className="ghost small filter-clear"
                onClick={() => onChange("")}>
          Clear
        </button>
      )}
      {/* Said always, not only when filtering: a list that shows 25 of 645
          without saying so is a list somebody reads as complete. */}
      <span className="dt-count muted">
        {shown === total ? `${total}` : `${shown} of ${total}`}
      </span>
    </div>
  );
}
