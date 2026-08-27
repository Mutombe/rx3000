/** One message, in full, with everything else sent to the same patient.
 *
 *  Reminder lists truncate the body to a line, which is fine until somebody
 *  rings up about what they were told. The history beside it matters as much:
 *  the usual complaint is not about one message but about three in a week.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDateTime } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useParams } from "react-router-dom";

interface Sibling {
  id: number; channel: string; message_type: string; status: string;
  subject: string; scheduled_for: string; sent_at: string | null;
}
interface Data {
  id: number;
  patient: { id: number | null; name: string; phone: string };
  channel: string; message_type: string; subject: string; body: string;
  status: string; detail: string;
  scheduled_for: string; sent_at: string | null;
  campaign_id: number | null;
  history: Sibling[];
}

const TONE: Record<string, string> = { sent: "ok", failed: "bad", queued: "muted" };

export default function MessageDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/messages/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That message could not be opened.")));
  }, [id]);

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Reminders", to: "/reminders" },
              { label: d?.subject || "This message" }]}
      eyebrow="Message"
      title={d?.subject || "(no subject)"}
      subtitle={d && <>
        <EntityLink kind="patient" id={d.patient.id}>{d.patient.name}</EntityLink>
        {d.patient.phone && ` · ${d.patient.phone}`}
      </>}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Status", value: d.status,
          hint: d.sent_at ? fmtDateTime(d.sent_at) : "not sent" },
        { label: "Channel", value: d.channel },
        { label: "Kind", value: d.message_type },
        { label: "Scheduled", value: fmtDateTime(d.scheduled_for) },
      ] : undefined}
    >
      {d && (
        <>
          {d.status === "failed" && d.detail && (
            <div className="alert error"><b>Not delivered</b> — {d.detail}</div>
          )}

          <Panel title="What was sent"
                 aside={d.campaign_id
                   ? <EntityLink kind="campaign" id={d.campaign_id}>
                       part of a campaign
                     </EntityLink>
                   : undefined}>
            <p className="prose" style={{ whiteSpace: "pre-wrap" }}>
              {d.body || <span className="muted">No body was recorded.</span>}
            </p>
          </Panel>

          <Panel title="Everything else sent to this patient" count={d.history.length}
                 empty="This is the only message on file for them.">
            <table className="dt">
              <thead>
                <tr><th>Subject</th><th>Kind</th><th>Channel</th><th>When</th><th>Status</th></tr>
              </thead>
              <tbody>
                {d.history.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <EntityLink kind="message" id={m.id}>
                        {m.subject || "(no subject)"}
                      </EntityLink>
                    </td>
                    <td>{m.message_type}</td>
                    <td>{m.channel}</td>
                    <td>{fmtDateTime(m.sent_at || m.scheduled_for)}</td>
                    <td><span className={`badge ${TONE[m.status] ?? ""}`}>{m.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
