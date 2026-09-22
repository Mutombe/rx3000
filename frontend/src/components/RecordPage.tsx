/** The frame every detail page shares: trail, heading, key figures, panels.
 *
 *  Twelve records went from having no page at all to having one, and twelve
 *  hand-rolled layouts would have drifted apart inside a fortnight — different
 *  breadcrumb wording, different loading behaviour, three ideas about where the
 *  back link goes. The frame is here so each page is only the part that differs.
 *
 *  It handles the three states a record page is actually in — loading, failed,
 *  and loaded — because the failure state is the one that gets forgotten, and a
 *  blank screen with a toast that has already faded tells nobody anything.
 */
import type { ReactNode } from "react";
import Breadcrumbs, { Crumb } from "./Breadcrumbs";
import { DetailSkeleton } from "./Skeleton";
import { Highlights } from "./record";
import { labelTone } from "../entityTone";

export interface Fact {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  /** "ok" | "warn" | "bad" — for a figure that is the wrong way round.
   *
   *  Sparingly. If every highlight is coloured then none of them is, and the
   *  one that means somebody must act today stops being findable. */
  tone?: string;
}

/** An identifier: what this record IS, as against how it is doing.
 *
 *  WHY THIS IS NOT `facts`, AND NOT THE SUBTITLE
 *
 *  A patient's header read "PT260900073 · DOB 03 Mar, 1979 · 07719116611 ·
 *  AHSS Zimbabwe #HD-1166 · 0 loyalty pts": five different kinds of fact run
 *  together in one grey line with dots between them, which is a sentence to
 *  be read rather than a set of fields to be scanned. Nothing said which
 *  number was the profile number, so the eye had to parse the format of each
 *  one to find out.
 *
 *  These are not `facts` either. Facts are the figures a record is judged by
 *  and they get the big strip; an identifier is how somebody finds or quotes
 *  the record, and it belongs with the name.
 */
export interface Meta {
  label: string;
  value: ReactNode;
  /** A code, an account number, a barcode: set in the monospace face so the
   *  digits line up and a transposed pair is visible. */
  mono?: boolean;
}

export default function RecordPage({
  trail, eyebrow, title, subtitle, meta, facts, error, loading, actions,
  children,
}: {
  trail: Crumb[];
  /** What kind of thing this is — "Supplier", "Claim", "Batch". */
  eyebrow: string;
  title: ReactNode;
  subtitle?: ReactNode;
  /** How this record is identified and quoted. Four or five at most: past
   *  that it stops being a header and becomes the record. */
  meta?: Meta[];
  /** The handful of numbers worth reading before anything else. */
  facts?: Fact[];
  error?: string;
  loading?: boolean;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  if (error) {
    return (
      <>
        <Breadcrumbs trail={trail} />
        <div className="alert error">{error}</div>
        <p className="muted">
          Nothing was loaded for this record. It may have been deleted, or the
          connection dropped on the way.
        </p>
      </>
    );
  }
  if (loading) {
    return <DetailSkeleton trail={trail} eyebrow={eyebrow} cards={2} />;
  }
  return (
    <>
      <Breadcrumbs trail={trail} />
      <div className="page-head rp-head">
        {/* ONE LEFT EDGE.
            The breadcrumb, the record type, the name, the identifiers and
            every card below all start at the same pixel. A product page put
            an avatar beside the title, which indented the name 58px further
            in than the trail above it and the card beneath it, and nothing
            on the screen lined up with anything else. */}
        <div className="rp-ident">
          {/* The record type, in its family colour. The word above a record
              page is where somebody confirms what they are looking at. */}
          <div className={`eyebrow ${labelTone(eyebrow)}`.trim()}>{eyebrow}</div>
          <h1>{title}</h1>
          {subtitle && <div className="sub">{subtitle}</div>}
          {meta && meta.length > 0 && (
            <dl className="rp-meta">
              {meta.map((m) => (
                <div key={m.label}>
                  <dt>{m.label}</dt>
                  <dd className={m.mono ? "mono" : undefined}>{m.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        {/* GROUPED, NOT SPREAD.
            `.page-head` lays its children out with space between them, so a
            page passing three actions got them scattered across the width
            with the first one stranded in the middle of the header. Wrapped
            here rather than in each caller, because every record page wants
            the same thing and none of them should have to know this. */}
        {actions && <div className="page-actions">{actions}</div>}
      </div>
      {facts && facts.length > 0 && <Highlights items={facts} />}
      {children}
    </>
  );
}

/** A card with a heading and, when there is nothing in it, a reason. */
export function Panel({ title, count, empty, children, aside }: {
  title: string;
  count?: number;
  /** Said when the panel has nothing — never left blank. */
  empty?: ReactNode;
  children?: ReactNode;
  aside?: ReactNode;
}) {
  const bare = count === 0;
  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}{count !== undefined && count > 0 && (
          <span className="badge muted">{count}</span>)}</h3>
        {aside}
      </div>
      {bare ? <div className="empty"><p>{empty ?? "Nothing here yet."}</p></div> : children}
    </div>
  );
}
