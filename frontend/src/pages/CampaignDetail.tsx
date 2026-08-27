/** A campaign and what it actually sent.
 *
 *  The campaign list showed an audience size and a sent count, which says how
 *  many went out and nothing about how many arrived. The breakdown by status is
 *  the number that matters: a campaign that "sent" four hundred and failed a
 *  hundred and eighty is not a campaign that worked.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDateTime } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useParams } from "react-router-dom";

interface Sent {
  id: number; status: string; channel: string;
  scheduled_for: string; sent_at: string | null;
  patient: { id: number | null; name: string };
}
interface Data {
  id: number; name: string; channel: string; segment: string;
  subject: string; body: string; status: string; created_at: string | null;
  sent_count: number; by_status: Record<string, number>; messages: Sent[];
}

const TONE: Record<string, string> = { sent: "ok", failed: "bad", queued: "muted" };

export default function CampaignDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/marketing/campaigns/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That campaign could not be opened.")));
  }, [id]);

  const failed = d?.by_status.failed ?? 0;

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Campaigns", to: "/marketing" },
              { label: d?.name ?? "This campaign" }]}
      eyebrow="Campaign"
      title={d?.name ?? ""}
      subtitle={d && `${d.channel} · ${d.segment}`}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Messages", value: d.sent_count },
        { label: "Delivered", value: d.by_status.sent ?? 0 },
        { label: "Failed", value: failed,
          hint: failed ? "did not reach anybody" : undefined },
        { label: "Status", value: d.status },
      ] : undefined}
    >
      {d && (
        <>
          <Panel title="What it said">
            <dl className="kv">
              <dt>Subject</dt><dd>{d.subject || "—"}</dd>
              <dt>Audience</dt><dd>{d.segment}</dd>
              <dt>Channel</dt><dd>{d.channel}</dd>
              <dt>Created</dt>
              <dd>{d.created_at ? fmtDateTime(d.created_at) : "—"}</dd>
            </dl>
            <p className="prose" style={{ whiteSpace: "pre-wrap" }}>
              {d.body || <span className="muted">No body was recorded.</span>}
            </p>
          </Panel>

          <Panel title="Who it went to" count={d.messages.length}
                 empty="This campaign has not sent anything yet.">
            <div className="dt-scroll" style={{ maxHeight: "50vh" }}>
              <table className="dt">
                <thead>
                  <tr><th>Patient</th><th>Channel</th><th>When</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {d.messages.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <EntityLink kind="patient" id={m.patient.id}>
                          {m.patient.name}
                        </EntityLink>
                      </td>
                      <td>{m.channel}</td>
                      <td>
                        <EntityLink kind="message" id={m.id}>
                          {fmtDateTime(m.sent_at || m.scheduled_for)}
                        </EntityLink>
                      </td>
                      <td><span className={`badge ${TONE[m.status] ?? ""}`}>{m.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
