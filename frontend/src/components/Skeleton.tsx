/** Skeletons: an honest ghost of the screen that is coming.
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
import { useLocation } from "react-router-dom";
import { pageNameFor } from "./Layout";
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
export function TableSkeleton({ cols, rows = 6, widths, secondLine, head = true,
                               rowHeight, headers }: {
  cols: number;
  /** The REAL column names, when the caller knows them.
   *
   *  It nearly always does: a table declares its headings a few lines below
   *  the skeleton that stands in for it, and they are the same on every visit.
   *  Ghosting them meant a reader waiting on a slow answer could not even see
   *  what they were waiting for, which is the one thing the screen could have
   *  told them for free.
   *
   *  Given, the head is drawn for real and only the rows pulse. Omitted, the
   *  old grey head is drawn, because a few tables really are shaped by their
   *  answer and inventing names for those would be worse. */
  headers?: string[];
  rows?: number;
  /** Per-column widths, so a narrow numeric column does not ghost as a wide one. */
  widths?: (string | number)[];
  /** What one real row of this table measures, in pixels.
   *
   *  A bare ghost row is 39px and almost no real row is: badges, a second line,
   *  a row of buttons and an avatar all make the real thing taller, and by
   *  wildly different amounts from one table to the next. Guessed at, every
   *  table lifts when its data lands.
   *
   *  So it is passed in rather than assumed, taken from what the table actually
   *  measures, and qa/no-empty-flash.mjs holds each page's answers back and
   *  compares the two. A hard number that a test checks is worth more than a
   *  clever one that drifts unnoticed. */
  rowHeight?: number;
  /** Zero-based columns whose real cells carry a second, quieter line beneath
   *  the first — a script number with "repeat" under it, a patient with their
   *  prescriber. Without these the ghost rows are shorter than the real ones
   *  and the whole table lifts when the data lands, which is the one thing a
   *  skeleton exists to prevent. */
  secondLine?: number[];
  /** Some tables are headerless: a log of icons and text, for instance. */
  head?: boolean;
}) {
  const under = new Set(secondLine ?? []);
  return (
    <table className="dt sk-table" aria-busy="true">
      {head && (
        <thead>
          <tr>
            {Array.from({ length: cols }).map((_, i) => (
              <th key={i}>
                {headers?.[i] !== undefined
                  ? headers[i]
                  : <Block w={widths?.[i] ?? "60%"} h={12} />}
              </th>
            ))}
          </tr>
        </thead>
      )}
      <tbody>
        {Array.from({ length: rows }).map((_, r) => (
          <tr key={r} style={rowHeight ? { height: `${rowHeight}px` } : undefined}>
            {Array.from({ length: cols }).map((_, c) => (
              <td key={c}>
                <Block w={widths?.[c] ?? "80%"} />
                {under.has(c) && (
                  <Block w="55%" h={10} className="sk-under" />
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One figure that has not arrived yet, and nothing else.
 *
 *  THIS IS THE WHOLE OF SCOPED LOADING, IN ONE COMPONENT.
 *
 *  A stat card is a label, a figure and a hint. Two of those three are written
 *  in the source and are true before the request is sent: "Lines waiting" is
 *  going to say "Lines waiting" whatever the server answers. Ghosting the card
 *  ghosts all three, so opening a screen shows a grid of grey rectangles that
 *  say nothing, and then the words arrive as if they had been fetched. They
 *  had not. They were always there and were being withheld.
 *
 *  So the label stays, the hint stays, the card stays, and the figure alone
 *  pulses. `height: 1em` means the block is the size of the type it stands in,
 *  so the same component is right inside a 26px stat value and a 13px table
 *  cell without being told which it is.
 *
 *  `w` is the width of the number that is coming, in `ch`, so the block is the
 *  size of its answer rather than a generic bar. Give it the widest plausible
 *  value: a queue depth is 3ch, a money figure 8ch. Too narrow and the card
 *  twitches when the figure lands, which is the one thing a skeleton exists to
 *  prevent.
 */
export function Figure({ ready, w = "3ch", children }: {
  /** True once the value below is real. */
  ready: boolean;
  w?: string | number;
  children: ReactNode;
}) {
  if (ready) return <>{children}</>;
  return <Block w={w} h="1em" className="sk-val" />;
}

/** Ghost rows for a table that has already drawn its own head.
 *
 *  `TableSkeleton` draws a head of grey blocks, which is right when the table
 *  itself is not on the screen yet and wrong the moment it is: column headings
 *  are written in the source, like every other label, and a table that knows
 *  it has a Patient column knows it before the patients arrive. This goes
 *  inside the real `<table>`, under the real `<thead>`, so the reader can read
 *  what is coming while it comes.
 */
export function GhostRows({ cols, rows = 6, widths, secondLine, rowHeight }: {
  cols: number;
  rows?: number;
  widths?: (string | number)[];
  secondLine?: number[];
  rowHeight?: number;
}) {
  const under = new Set(secondLine ?? []);
  return (
    <tbody aria-busy="true">
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} style={rowHeight ? { height: `${rowHeight}px` } : undefined}>
          {Array.from({ length: cols }).map((_, c) => (
            <td key={c}>
              <Block w={widths?.[c] ?? "80%"} />
              {under.has(c) && <Block w="55%" h={10} className="sk-under" />}
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  );
}

export function StatsSkeleton({ tiles = 4, labels }: {
  tiles?: number;
  /** The REAL tile labels. "Owed to suppliers" is going to say "Owed to
   *  suppliers" whatever the server answers, so it is drawn, and only the
   *  figure under it pulses. `tiles` is ignored when these are given: the
   *  number of tiles is the number of labels, which is one fewer thing that
   *  can be told wrong. */
  labels?: string[];
}) {
  const n = labels?.length ?? tiles;
  return (
    <div className="sk-stats" aria-busy="true">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="card sk-stat">
          {labels?.[i] !== undefined
            ? <div className="label">{labels[i]}</div>
            : <Block w="45%" h={11} />}
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
 *  the first paint, and after that a refetch merely dims what is already
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
    /* Named, so it can be spaced. This div is a page block on most screens —
       it wraps the table — and it declared no bottom margin, so anything that
       appeared after it sat flush on it: on Licences, the branch register that
       opens when you click a branch landed on the table with no air at all.
       Every other page block carries the page's rhythm; this one had no way to
       be told about it. */
    <div className={`refreshable${loading ? " is-refreshing" : ""}`}
         aria-busy={loading}>
      {children}
    </div>
  );
}

/** The two states an optimistic row can be in.
 *
 *  A row that does not exist on the server yet must not be actionable — it has
 *  no id to act on, so `pending` also marks it non-interactive rather than
 *  merely faded.
 */
/* `RowState` used to sit here — a "Creating…/Saving…" pill for an optimistic
 * layer nothing had been wired to. `useOptimisticList` marks the row itself
 * now, which is better: a five-row save shows five quiet bars rather than five
 * spinners with five labels, and a list of those is a list nobody can read. */

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
        // yet to switch between, but readable, so the reader learns what this
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
 *  THE HEADING IS NOT A LOADING STATE.
 *
 *  This drew two grey blocks where the title and subtitle go, which made the
 *  one thing on the screen that was never in doubt — the name of the page you
 *  just clicked — arrive as a skeleton. A page's title is static: it does not
 *  depend on the code, the data or the network, and it is already written down
 *  in the rail's own table.
 *
 *  So the name is real from the first frame. It is the same string the rail
 *  highlights, so clicking "Suppliers" puts the word Suppliers on the page
 *  immediately and the only thing that pulses is the part nobody can know yet.
 *
 *  The subtitle is not here, because it is not in the rail and inventing a
 *  grey bar for it would be the same fault one line down. Its line is held
 *  open so the page does not jump when the real sentence arrives.
 */
export function PageSkeleton() {
  const { pathname } = useLocation();
  const name = pageNameFor(pathname);
  return (
    <div className="page" aria-busy="true">
      <header className="page-head">
        {/* The same wrapper the real head uses, so the title lands in the
            same place and at the same size and nothing moves when the page
            takes over. */}
        <div className="page-head-said">
          {name
            ? <h1>{name}</h1>
            /* A route the rail does not carry — a record page reached by a
               link. Nothing is claimed rather than a name being guessed. */
            : <Block w="22ch" h={26} />}
          {/* The subtitle's line, held open and empty. */}
          <div className="sub sk-sub" />
        </div>
      </header>
      <TableSkeleton cols={6} rows={6} />
    </div>
  );
}
