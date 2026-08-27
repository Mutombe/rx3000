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

export interface Fact {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}

export default function RecordPage({
  trail, eyebrow, title, subtitle, facts, error, loading, actions, children,
}: {
  trail: Crumb[];
  /** What kind of thing this is — "Supplier", "Claim", "Batch". */
  eyebrow: string;
  title: ReactNode;
  subtitle?: ReactNode;
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
      <div className="page-head">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          {subtitle && <div className="sub">{subtitle}</div>}
        </div>
        {actions}
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
