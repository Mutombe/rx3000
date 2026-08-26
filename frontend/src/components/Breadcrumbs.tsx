/** Breadcrumbs and Back — knowing where you are without the browser button.
 *
 *  A detail page reached from a report, a search result or a link in an email
 *  has no context of its own. The trail is what turns it from somewhere you
 *  landed into somewhere in a structure.
 *
 *  Back is deliberately *not* `history.back()` by default. History goes where
 *  you came from, which after three sideways jumps between related records is
 *  not the same as where this record lives. The parent is a property of the
 *  page; history is a property of the session, and only the first is reliable.
 *  Where they differ, the parent is the useful one.
 */
import { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft } from "@phosphor-icons/react";

export interface Crumb {
  label: string;
  to?: string;
}

export default function Breadcrumbs({
  trail,
  actions,
}: {
  /** Root first, this page last. The last crumb is never a link. */
  trail: Crumb[];
  actions?: ReactNode;
}) {
  const navigate = useNavigate();
  const parent = [...trail].reverse().find((c) => c.to);

  return (
    <div className="crumbs-bar">
      <nav className="crumbs" aria-label="Breadcrumb">
        <ol>
          {trail.map((c, i) => {
            const last = i === trail.length - 1;
            return (
              <li key={`${c.label}-${i}`} aria-current={last ? "page" : undefined}>
                {c.to && !last ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
                {!last && <span className="crumb-sep" aria-hidden="true">›</span>}
              </li>
            );
          })}
        </ol>
      </nav>
      <div className="crumbs-actions">
        {actions}
        {parent && (
          <button
            className="btn ghost sm"
            onClick={() => navigate(parent.to!)}
            title={`Back to ${parent.label}`}
          >
            <ArrowLeft size={13} weight="bold" /> {parent.label}
          </button>
        )}
      </div>
    </div>
  );
}
