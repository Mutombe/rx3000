/** One audit entry, and what surrounded it.
 *
 *  An audit row on its own rarely answers anything. "Who voided this sale" is
 *  followed immediately by "and what else were they doing at the time", and
 *  that question could not be asked: the rows were not clickable and there was
 *  no endpoint behind them.
 *
 *  So the twenty nearest entries from the same person come with it, in time
 *  order, with this one marked. A void at two in the morning means one thing
 *  on its own and quite another surrounded by nine other voids.
 *
 *  WHO WAS REALLY DOING IT
 *
 *  When head office signs in as a branch user, every row they write is
 *  attributed to that user. The model has carried `acted_as` since
 *  impersonation was built, with a comment saying an impersonated action "has
 *  to name both people or the audit log is actively misleading". It was not in
 *  the response, so the log was exactly that. It is named here, loudly,
 *  because it is the one fact that changes what the entry means.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, UserSwitch, Warning } from "@phosphor-icons/react";

import { api, errorText, fmtDateTime } from "../api";
import RecordPage, { Panel } from "../components/RecordPage";
import { Figure, GhostRows } from "../components/Skeleton";
import Th from "../components/Th";

interface Entry {
  id: number;
  user_id: number | null;
  username: string;
  action: string;
  path: string;
  summary: string;
  status_code: number;
  ip_address: string;
  created_at: string;
  acted_as_id: number | null;
  acted_as: string;
}

interface Detail extends Entry {
  says: string;
  before: Entry[];
  after: Entry[];
}

function Status({ code }: { code: number }) {
  const bad = code >= 400;
  return (
    <span className={`badge ${bad ? "danger" : "ok"}`}>{code || "none"}</span>
  );
}

export default function AuditDetail() {
  const { id } = useParams();
  const [row, setRow] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRow(null);
    setError("");
    api.get<Detail>(`/api/admin/audit/${id}`)
      .then(setRow)
      .catch((e) => setError(errorText(e, "That entry could not be loaded.")));
  }, [id]);

  const line = (e: Entry, isThis = false) => (
    <tr key={e.id} className={isThis ? "is-here" : undefined}>
      <td className="muted small">{fmtDateTime(e.created_at)}</td>
      <td><span className="badge muted">{e.action}</span></td>
      <td className="mono small wrap">{e.path}</td>
      <td><Status code={e.status_code} /></td>
      <td className="actions">
        {isThis
          ? <span className="badge">this one</span>
          : <Link className="btn-link small" to={`/audit/${e.id}`}>Open</Link>}
      </td>
    </tr>
  );

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Control panel", to: "/admin" },
              { label: "This entry" }]}
      eyebrow="Audit entry"
      title={row ? `${row.action} ${row.path}` : "Audit entry"}
      subtitle={row?.says}
      loading={!row && !error}
      error={error}
      actions={
        <Link to="/admin" className="btn secondary">
          <ArrowLeft size={13} weight="bold" /> Audit log
        </Link>
      }
      facts={row ? [
        { label: "Signed in as", value: row.username || "Not recorded" },
        { label: "Really", value: row.acted_as || row.username || "none",
          hint: row.acted_as ? "head office acting as somebody" : "themselves",
          tone: row.acted_as ? "warn" : undefined },
        { label: "Answer", value: row.status_code || "none",
          hint: row.status_code >= 400 ? "the server refused it" : "accepted",
          tone: row.status_code >= 400 ? "bad" : undefined },
        { label: "When", value: fmtDateTime(row.created_at),
          hint: row.ip_address || "" },
      ] : []}
    >
      {/* The gate that stood here held back both panel headings, the six
          labels under "What was asked" and the whole head of the table beneath
          them until the entry came back. Not one of those is fetched: an audit
          entry always has an action, an endpoint, an answer and a time, and
          the reader waiting on a slow one should at least be able to see what
          they are waiting for. Only the values beside the labels pulse. */}
      {/* THE ONE FACT THAT CHANGES WHAT THE ENTRY MEANS.
          Without it the trail says a cashier in Bulawayo voided a sale at
          two in the morning when it was somebody at head office. */}
      {row?.acted_as && (
        <div className="alert warn">
          <UserSwitch size={15} weight="fill" /> This was done by{" "}
          <b>{row.username}</b> while signed in as <b>{row.acted_as}</b>.
          The action is recorded against {row.acted_as}, and the person who
          actually took it is {row.username}.
        </div>
      )}

      {row && row.status_code >= 400 && (
        <div className="alert error">
          <Warning size={15} weight="fill" /> The server refused this with{" "}
          {row.status_code}, so whatever it asked for did not happen.
        </div>
      )}

      <Panel title="What was asked">
        <dl className="kv">
          <dt>Action</dt>
          <dd>
            <Figure ready={!!row} w="6ch">
              {row && <span className="badge muted">{row.action}</span>}
            </Figure>
          </dd>

          <dt>Endpoint</dt>
          <dd className="mono wrap">
            <Figure ready={!!row} w="30ch">{row?.path}</Figure>
          </dd>

          <dt>Summary</dt>
          <dd>
            <Figure ready={!!row} w="36ch">
              {row && (row.summary
                || <span className="muted">None recorded</span>)}
            </Figure>
          </dd>

          <dt>Answer</dt>
          <dd>
            <Figure ready={!!row} w="4ch">
              {row && <Status code={row.status_code} />}
            </Figure>
          </dd>

          <dt>From</dt>
          <dd className="mono">
            <Figure ready={!!row} w="12ch">
              {row && (row.ip_address
                || <span className="muted">Not recorded</span>)}
            </Figure>
          </dd>

          <dt>When</dt>
          <dd>
            <Figure ready={!!row} w="16ch">
              {row && fmtDateTime(row.created_at)}
            </Figure>
          </dd>
        </dl>
      </Panel>

      <Panel
        // Named where there is a name, neutral where there is not:
        // "What they was doing around it" is what a fallback inside a
        // sentence gets you. Before the entry arrives nobody has a name
        // either, so the neutral wording carries the wait as well.
        title={row?.username
          ? `What ${row.username} was doing around it`
          : "What else happened around it"}
        count={row ? row.before.length + row.after.length : undefined}
        // Only once the neighbours are actually in hand. A screen that has
        // been told nothing must not announce that there is nothing.
        empty={row ? "Nothing else is recorded for this person." : undefined}
      >
        <div className="table-wrap">
          <table className="dt">
            <thead>
              <tr>
                <Th>When</Th><Th>Action</Th><Th>Endpoint</Th>
                <Th>Answer</Th><th className="actions" />
              </tr>
            </thead>
            {!row ? (
              <GhostRows cols={5} rows={3}
                         widths={["70%", "40%", "85%", "30%", "40%"]} />
            ) : (
              <tbody>
                {row.before.map((e) => line(e))}
                {line(row, true)}
                {row.after.map((e) => line(e))}
              </tbody>
            )}
          </table>
        </div>
      </Panel>
    </RecordPage>
  );
}
