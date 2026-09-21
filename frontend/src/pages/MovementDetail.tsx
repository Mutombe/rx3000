/** One stock movement, and enough around it to answer for itself.
 *
 *  WHY THIS PAGE EXISTS
 *
 *  Nobody opens a stock movement out of curiosity. They open it because a
 *  figure is wrong. What they need is: what happened, who did it, why, and
 *  whether the running balance either side of it makes sense.
 *
 *  The movements table answered the first of those and nothing else. Clicking
 *  a row went to the PRODUCT — the one thing the reader was already looking
 *  at — and the reason and the staff member, both recorded on every movement
 *  since the adjustment dialog was written, appeared nowhere at all.
 *
 *  THE NEIGHBOURS ARE THE POINT
 *
 *  A balance that jumps between two consecutive movements is the signature of
 *  stock changed behind the system's back, and it is invisible until the two
 *  rows are next to each other. So five either side come with it, and the
 *  arithmetic across this row is checked out loud rather than left for
 *  somebody to do in their head.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Warning } from "@phosphor-icons/react";

import { api, errorText, fmtDateTime } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";

interface Neighbour {
  id: number;
  created_at: string | null;
  movement_type: string;
  quantity_delta: number;
  balance_after: number | null;
  reference: string;
}

interface Detail {
  id: number;
  created_at: string | null;
  movement_type: string;
  quantity_delta: number;
  balance_after: number | null;
  reference: string;
  notes: string;
  reason_code: string;
  reason: string;
  product_id: number;
  product: string;
  pack_size: string;
  schedule: number;
  user_id: number | null;
  user: string;
  user_role: string;
  branch_id: number | null;
  branch: string;
  prescription_id: number | null;
  rx_number: string;
  before: Neighbour[];
  after: Neighbour[];
  balance_agrees: boolean;
  balance_expected: number | null;
  says: string;
}

function Delta({ n }: { n: number }) {
  return (
    <span className={n > 0 ? "pos" : n < 0 ? "neg" : undefined}>
      {n > 0 ? `+${n}` : n}
    </span>
  );
}

export default function MovementDetail() {
  const { id } = useParams();
  const [row, setRow] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRow(null);
    setError("");
    api.get<Detail>(`/api/stock/movements/${id}`)
      .then(setRow)
      .catch((e) => setError(errorText(e, "That movement could not be loaded.")));
  }, [id]);

  /** The row itself, drawn the same way as its neighbours so the reader can
   *  compare them without translating between two layouts. */
  const line = (m: Neighbour, isThis = false) => (
    <tr key={m.id} className={isThis ? "is-here" : undefined}>
      <td className="muted small">
        {m.created_at ? fmtDateTime(m.created_at) : "not recorded"}
      </td>
      <td><span className="badge muted">{m.movement_type}</span></td>
      <td className="num"><Delta n={m.quantity_delta} /></td>
      <td className="num">{m.balance_after ?? "—"}</td>
      <td className="mono small">{m.reference || "—"}</td>
      <td className="actions">
        {isThis
          ? <span className="badge">this one</span>
          : <Link className="btn-link small" to={`/movements/${m.id}`}>Open</Link>}
      </td>
    </tr>
  );

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Inventory", to: "/stock" },
              { label: "This movement" }]}
      eyebrow="Stock movement"
      title={row ? row.product || `Movement ${row.id}` : "Movement"}
      subtitle={row?.says}
      loading={!row && !error}
      error={error}
      actions={
        <Link to="/stock" className="btn secondary">
          <ArrowLeft size={13} weight="bold" /> Movements
        </Link>
      }
      facts={row ? [
        { label: "Moved", value: <Delta n={row.quantity_delta} />,
          hint: row.pack_size ? `pack of ${row.pack_size}` : "units" },
        { label: "Balance after", value: row.balance_after ?? "—",
          hint: row.balance_agrees ? "agrees with the movement before"
                                   : "does not agree",
          tone: row.balance_agrees ? undefined : "bad" },
        { label: "Why", value: row.reason || row.movement_type,
          hint: row.reason ? "chosen from the list" : "implied by the type" },
        { label: "Who", value: row.user || "not recorded",
          hint: row.user_role || (row.user ? "" : "written by the system") },
      ] : []}
    >
      {row && (
        <>
          {/* THE ARITHMETIC, SAID OUT LOUD.
              A stored balance can disagree with the movement that produced
              it, and when stock is wrong that disagreement is the whole
              answer. It was previously left for the reader to spot by
              subtracting two numbers in two rows of a table. */}
          {!row.balance_agrees && (
            <div className="alert error">
              <Warning size={15} weight="fill" /> The balance on this movement
              does not follow from the one before it. It should read{" "}
              <b>{row.balance_expected}</b> and it reads{" "}
              <b>{row.balance_after}</b>. Something changed this figure outside
              the movement history, so the running balance from here on is
              carrying that difference.
            </div>
          )}

          <Panel title="What this was">
            <dl className="kv">
              <dt>Medicine</dt>
              <dd>
                <EntityLink to={`/products/${row.product_id}`}>
                  {row.product || "—"}
                </EntityLink>
                {row.schedule >= 3 && (
                  <span className="badge sched">S{row.schedule}</span>
                )}
              </dd>

              <dt>When</dt>
              <dd>{row.created_at ? fmtDateTime(row.created_at)
                                  : <span className="muted">not recorded</span>}</dd>

              <dt>Type</dt>
              <dd><span className="badge muted">{row.movement_type}</span></dd>

              <dt>Reason</dt>
              <dd>
                {row.reason
                  ? <span className="badge">{row.reason}</span>
                  : <span className="muted">
                      none chosen, which is ordinary for a sale or a receipt
                    </span>}
              </dd>

              <dt>Note</dt>
              <dd>{row.notes || <span className="muted">none</span>}</dd>

              <dt>Reference</dt>
              <dd className="mono">{row.reference || <span className="muted">none</span>}</dd>

              <dt>Who</dt>
              <dd>
                {row.user
                  ? <>{row.user}{row.user_role && <span className="muted"> · {row.user_role}</span>}</>
                  : <span className="muted">written by the system, not by a person</span>}
              </dd>

              <dt>Where</dt>
              <dd>{row.branch || <span className="muted">not recorded</span>}</dd>

              {row.prescription_id ? (
                <>
                  <dt>Script</dt>
                  <dd>
                    <EntityLink to={`/prescriptions/${row.prescription_id}`}>
                      {row.rx_number || `#${row.prescription_id}`}
                    </EntityLink>
                  </dd>
                </>
              ) : null}
            </dl>
          </Panel>

          <Panel
            title="Either side of it"
            count={row.before.length + row.after.length}
            empty="Nothing else has moved on this medicine."
            aside={
              <Link className="btn secondary small"
                    to={`/stock?tab=movements&product=${row.product_id}`}>
                All movements for this medicine
              </Link>
            }
          >
            <div className="table-wrap">
              <table className="dt">
                <thead>
                  <tr>
                    <th>When</th><th>Type</th>
                    <th className="num">Δ Qty</th>
                    <th className="num">Balance</th>
                    <th>Reference</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {row.before.map((m) => line(m))}
                  {line({
                    id: row.id, created_at: row.created_at,
                    movement_type: row.movement_type,
                    quantity_delta: row.quantity_delta,
                    balance_after: row.balance_after,
                    reference: row.reference,
                  }, true)}
                  {row.after.map((m) => line(m))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
