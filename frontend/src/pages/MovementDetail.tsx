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
import { useScheduleCodes } from "../schedules";
import { Link, useParams } from "react-router-dom";
import { Warning } from "@phosphor-icons/react";

import { api, errorText, fmtDateTime } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { Figure, GhostRows } from "../components/Skeleton";
import Th from "../components/Th";

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
  const sched = useScheduleCodes();
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
        {m.created_at ? fmtDateTime(m.created_at) : "Not recorded"}
      </td>
      <td><span className="badge muted">{m.movement_type}</span></td>
      <td className="num"><Delta n={m.quantity_delta} /></td>
      <td className="num">{m.balance_after ?? "none"}</td>
      <td className="mono small">{m.reference || "none"}</td>
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
              { label: "Movement history", to: "/stock?tab=movements" },
              { label: row ? row.product || `Movement ${row.id}` : "This movement" }]}
      eyebrow="Stock movement"
      title={row ? row.product || `Movement ${row.id}` : "Movement"}
      subtitle={row?.says}
      loading={!row && !error}
      error={error}
      actions={
        <>
          {/* The breadcrumb carries the way back, from the trail. What
              belongs here is the record this movement is about. */}
          {row?.product_id ? (
            <Link to={`/products/${row.product_id}`} className="btn secondary">
              The medicine
            </Link>
          ) : null}
          {row?.user_id ? (
            <Link to={`/staff/${row.user_id}`} className="btn secondary">
              Who did it
            </Link>
          ) : null}
        </>
      }
      facts={row ? [
        { label: "Moved", value: <Delta n={row.quantity_delta} />,
          hint: row.pack_size ? `pack of ${row.pack_size}` : "units" },
        { label: "Balance after", value: row.balance_after ?? "Not recorded",
          hint: row.balance_agrees ? "agrees with the movement before"
                                   : "does not agree",
          tone: row.balance_agrees ? undefined : "bad" },
        { label: "Why", value: row.reason || row.movement_type,
          hint: row.reason ? "chosen from the list" : "implied by the type" },
        { label: "Who", value: row.user || "Not recorded",
          hint: row.user_role || (row.user ? "" : "written by the system") },
      ] : []}
    >
      {/* THE ARITHMETIC, SAID OUT LOUD.
          A stored balance can disagree with the movement that produced
          it, and when stock is wrong that disagreement is the whole
          answer. It was previously left for the reader to spot by
          subtracting two numbers in two rows of a table.

          This one really does wait for the answer: an accusation cannot be
          made before the figures that support it have arrived. */}
      {row && !row.balance_agrees && (
        <div className="alert error">
          <Warning size={15} weight="fill" /> The balance on this movement
          does not follow from the one before it. It should read{" "}
          <b>{row.balance_expected}</b> and it reads{" "}
          <b>{row.balance_after}</b>. Something changed this figure outside
          the movement history, so the running balance from here on is
          carrying that difference.
        </div>
      )}

      {/* Both panel headings, the eight field labels and the six column heads
          of the neighbour table describe every stock movement there is, so
          none of them was ever waiting on this one. Behind the gate the page
          showed nothing at all and then unfolded in a single jump, which on a
          page somebody opens because a figure is wrong is the wrong first
          impression. Only the values pulse now. */}
      <Panel title="What this was">
        <dl className="kv">
          <dt>Medicine</dt>
          <dd>
            <Figure ready={!!row} w="20ch">
              {row && (
                <>
                  <EntityLink to={`/products/${row.product_id}`}>
                    {row.product || "unnamed"}
                  </EntityLink>
                  {row.schedule >= 3 && (
                    <span className="badge sched">{sched(row.schedule)}</span>
                  )}
                </>
              )}
            </Figure>
          </dd>

          <dt>When</dt>
          <dd>
            <Figure ready={!!row} w="16ch">
              {row && (row.created_at
                ? fmtDateTime(row.created_at)
                : <span className="muted">Not recorded</span>)}
            </Figure>
          </dd>

          <dt>Type</dt>
          <dd>
            <Figure ready={!!row} w="10ch">
              {row && <span className="badge muted">{row.movement_type}</span>}
            </Figure>
          </dd>

          <dt>Reason</dt>
          <dd>
            <Figure ready={!!row} w="24ch">
              {row && (row.reason
                ? <span className="badge">{row.reason}</span>
                : <span className="muted">
                    none chosen, which is ordinary for a sale or a receipt
                  </span>)}
            </Figure>
          </dd>

          <dt>Note</dt>
          <dd>
            <Figure ready={!!row} w="30ch">
              {row && (row.notes || <span className="muted">None</span>)}
            </Figure>
          </dd>

          <dt>Reference</dt>
          <dd className="mono">
            <Figure ready={!!row} w="14ch">
              {row && (row.reference || <span className="muted">None</span>)}
            </Figure>
          </dd>

          <dt>Who</dt>
          <dd>
            <Figure ready={!!row} w="18ch">
              {row && (row.user
                ? <>{row.user}{row.user_role && <span className="muted"> · {row.user_role}</span>}</>
                : <span className="muted">written by the system, not by a person</span>)}
            </Figure>
          </dd>

          <dt>Where</dt>
          <dd>
            <Figure ready={!!row} w="16ch">
              {row && (row.branch || <span className="muted">Not recorded</span>)}
            </Figure>
          </dd>

          {/* Only movements that came off a script carry this pair, so whether
              the row exists at all is genuinely part of the answer. */}
          {row?.prescription_id ? (
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
        count={row ? row.before.length + row.after.length : undefined}
        /* Said only once the neighbours have been counted. A page that has not
           heard back cannot know whether this medicine has ever moved. */
        empty={row ? "Nothing else has moved on this medicine." : undefined}
        aside={row ? (
          <Link className="btn secondary small"
                to={`/stock?tab=movements&product=${row.product_id}`}>
            All movements for this medicine
          </Link>
        ) : undefined}
      >
        <div className="table-wrap">
          <table className="dt">
            <thead>
              <tr>
                <Th>When</Th><Th>Type</Th>
                <th className="num">Δ Qty</th>
                <Th className="num">Balance</Th>
                <Th>Reference</Th><th className="actions" />
              </tr>
            </thead>
            {!row ? (
              <GhostRows cols={6} rows={3}
                         widths={["70%", "50%", "30%", "40%", "60%", "40%"]} />
            ) : (
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
            )}
          </table>
        </div>
      </Panel>
    </RecordPage>
  );
}
