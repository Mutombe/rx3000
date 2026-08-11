/** Skeletons — an honest ghost of the screen that is coming.
 *
 *  The rule that makes these worth having is accuracy, not decoration: a
 *  skeleton must reserve the *exact* footprint of the content it stands in for,
 *  so that when data arrives nothing moves. If swapping in the real thing shifts
 *  a single row, the skeleton was wrong and is a bug — not a cosmetic one, since
 *  a page that jumps under a cursor is a page that gets mis-clicked.
 *
 *  Hence one primitive and a set of composed shapes that mirror the real
 *  components, rather than a generic spinner. A table skeleton takes the same
 *  column count; a list takes the same row count; a stat row takes the same
 *  number of tiles.
 *
 *  Two things these deliberately do NOT do:
 *
 *  * They do not appear on refetch. Changing a filter, a date range or a page
 *    keeps the previous results on screen while the next set loads. A skeleton
 *    that flashes between two sets of data is worse than no skeleton — it reads
 *    as the page breaking. `<Refreshable>` below is what handles that case.
 *
 *  * They do not stack more than one motion. One slow pulse, everywhere, so
 *    loading always looks like one system rather than a patchwork.
 */
import { ReactNode } from "react";
import Breadcrumbs, { Crumb } from "./Breadcrumbs";

interface BlockProps {
  /** CSS width — "100%", "8ch", 120. */
  w?: string | number;
  h?: string | number;
  /** Pills for avatars and dots; otherwise the radius matches the real element. */
  round?: "sm" | "md" | "pill";
  className?: string;
}

/** The only primitive. Everything else is composed from it. */
export function Block({ w = "100%", h = 14, round = "sm", className = "" }: BlockProps) {
  return (
    <span
      className={`sk sk-${round} ${className}`.trim()}
      style={{ width: typeof w === "number" ? `${w}px` : w,
               height: typeof h === "number" ? `${h}px` : h }}
      aria-hidden="true"
    />
  );
}

/** A table that will have `cols` columns and `rows` rows. Match both to the real
 *  table or the swap will shift the page. */
export function TableSkeleton({ cols, rows = 6, widths }: {
  cols: number;
  rows?: number;
  /** Per-column widths, so a narrow numeric column does not ghost as a wide one. */
  widths?: (string | number)[];
}) {
  return (
    <table className="dt sk-table" aria-busy="true">
      <thead>
        <tr>
          {Array.from({ length: cols }).map((_, i) => (
            <th key={i}><Block w={widths?.[i] ?? "60%"} h={12} /></th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }).map((_, r) => (
          <tr key={r}>
            {Array.from({ length: cols }).map((_, c) => (
              <td key={c}><Block w={widths?.[c] ?? "80%"} /></td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function StatsSkeleton({ tiles = 4 }: { tiles?: number }) {
  return (
    <div className="sk-stats" aria-busy="true">
      {Array.from({ length: tiles }).map((_, i) => (
        <div key={i} className="card sk-stat">
          <Block w="45%" h={11} />
          <Block w="70%" h={26} />
        </div>
      ))}
    </div>
  );
}

export function ListSkeleton({ rows = 5, avatar = false }: {
  rows?: number;
  avatar?: boolean;
}) {
  return (
    <ul className="sk-list" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i}>
          {avatar && <Block w={32} h={32} round="pill" />}
          <span className="sk-list-lines">
            <Block w="40%" />
            <Block w="65%" h={11} />
          </span>
        </li>
      ))}
    </ul>
  );
}

export function FormSkeleton({ fields = 5 }: { fields?: number }) {
  return (
    <div className="sk-form" aria-busy="true">
      {Array.from({ length: fields }).map((_, i) => (
        <label key={i}>
          <Block w="30%" h={11} />
          <Block h={38} round="md" />
        </label>
      ))}
    </div>
  );
}

/** Keeps the previous results on screen while the next set loads.
 *
 *  This is the component that stops a filter change from blanking the table.
 *  A skeleton is shown only when there is genuinely nothing to display yet —
 *  the first paint — and after that a refetch merely dims what is already
 *  there. Blanking a populated table to re-show it a moment later reads as the
 *  page breaking, not as progress.
 */
export function Refreshable({
  loading,
  hasData,
  skeleton,
  children,
}: {
  loading: boolean;
  hasData: boolean;
  skeleton: ReactNode;
  children: ReactNode;
}) {
  if (loading && !hasData) return <>{skeleton}</>;
  return (
    <div className={loading ? "is-refreshing" : undefined} aria-busy={loading}>
      {children}
    </div>
  );
}

/** The two states an optimistic row can be in.
 *
 *  A row that does not exist on the server yet must not be actionable — it has
 *  no id to act on — so `pending` also marks it non-interactive rather than
 *  merely faded.
 */
export function RowState({ state }: { state: "creating" | "saving" | null }) {
  if (!state) return null;
  return (
    <span className={`row-state row-state-${state}`}>
      <span className="spinner" aria-hidden="true" />
      {state === "creating" ? "Creating…" : "Saving…"}
    </span>
  );
}

/** The stand-in for a record that has not arrived yet.
 *
 *  Loading here is *scoped*: only the parts that depend on the fetch are
 *  ghosted. Everything the page already knows before the request is sent — the
 *  breadcrumb trail, the record type, the tab labels, the card headings — is
 *  rendered for real, immediately.
 *
 *  This matters beyond looking tidy. The trail is derived from the route, not
 *  from the response, so ghosting it withholds information the app already has
 *  and makes the page feel slower than it is. It also leaves the reader unable
 *  to navigate away while they wait, which is precisely when they most want to:
 *  a record that is slow to load is the one you are most likely to have opened
 *  by mistake. Real crumbs stay clickable throughout.
 *
 *  Only three things are genuinely unknown before the response: the record's
 *  name, its subtitle, and the contents of its cards. Those, and nothing else,
 *  are what pulse.
 */
export function DetailSkeleton({
  trail,
  eyebrow,
  tabs,
  cards = 1,
  avatar = false,
  table,
}: {
  /** The real trail. Rendered as working links, not ghosted. */
  trail?: Crumb[];
  /** The record type — "Patient", "Contact". Known from the route. */
  eyebrow?: string;
  /** Real tab labels, shown inert until the record they describe exists. */
  tabs?: string[];
  cards?: number;
  /** Records fronted by a person or product carry one; documents do not. */
  avatar?: boolean;
  /** Columns of the first table inside the body, if there is one. */
  table?: number;
}) {
  return (
    <>
      {trail && <Breadcrumbs trail={trail} />}
      <div className="page-head">
        <div className="record-title">
          {avatar && <Block w={44} h={44} round="pill" />}
          <div style={{ display: "grid", gap: "var(--s2)" }}>
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            {/* The name and subtitle are the only unknowns in this header. */}
            <Block w="20ch" h={26} />
            <Block w="30ch" h={12} />
          </div>
        </div>
      </div>
      {tabs && tabs.length > 0 && (
        // The real strip with the real labels. Inert, because there is nothing
        // yet to switch between, but readable — so the reader learns what this
        // record offers while it arrives.
        <div className="pill-tabs sk-tabs" aria-hidden="true">
          {tabs.map((t) => (
            <span key={t} className="sk-tab">{t}</span>
          ))}
        </div>
      )}
      <div aria-busy="true">
        {Array.from({ length: cards }).map((_, i) => (
          <section key={i} className="card sk-card">
            <Block w="14ch" h={14} />
            {i === 0 && table ? (
              <TableSkeleton cols={table} rows={4} />
            ) : (
              <>
                <Block w="100%" />
                <Block w="82%" />
                <Block w="60%" />
              </>
            )}
          </section>
        ))}
      </div>
    </>
  );
}

/** The stand-in while a page's code and data arrive.
 *
 *  Shaped like a page rather than like nothing: a heading, a line of context,
 *  and a table. It is what the Suspense boundary inside Layout falls back to,
 *  so the chrome stays put and only this area changes.
 */
export function PageSkeleton() {
  return (
    <div className="page" aria-busy="true">
      <header className="page-head">
        <div style={{ display: "grid", gap: "var(--s2)" }}>
          <Block w="22ch" h={26} />
          <Block w="38ch" h={12} />
        </div>
      </header>
      <TableSkeleton cols={6} rows={6} />
    </div>
  );
}
