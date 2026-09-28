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
import { Figure, GhostRows } from "../components/Skeleton";
import { useParams } from "react-router-dom";
import Person from "../components/Person";
import Th from "../components/Th";

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
        <EntityLink kind="patient" id={d.patient.id}><Person name={d.patient.name} /></EntityLink>
        {d.patient.phone && ` · ${d.patient.phone}`}
      </>}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Status", value: d.status,
          hint: d.sent_at ? fmtDateTime(d.sent_at) : "Not sent" },
        { label: "Channel", value: d.channel },
        { label: "Kind", value: d.message_type },
        { label: "Scheduled", value: fmtDateTime(d.scheduled_for) },
      ] : undefined}
    >
      {/* The gate that stood here withheld both card headings and the five
          column names of the history table until the message came back. The
          usual complaint is not about one message but about three in a week,
          and the shape of the answer to that is known before it arrives.
          Only the words of the message and the rows beneath it pulse. */}
      {d && d.status === "failed" && d.detail && (
        <div className="alert error"><b>Not delivered</b>: {d.detail}</div>
      )}

      <Panel title="What was sent"
             aside={d?.campaign_id
               ? <EntityLink kind="campaign" id={d.campaign_id}>
                   part of a campaign
                 </EntityLink>
               : undefined}>
        <p className="prose" style={{ whiteSpace: "pre-wrap" }}>
          <Figure ready={!!d} w="40ch">
            {d && (d.body || <span className="muted">No body was recorded.</span>)}
          </Figure>
        </p>
      </Panel>

      <Panel title="Everything else sent to this patient" count={d?.history.length}
             /* Only once the history is in hand. "The only message on file"
                is a conclusion about the patient, not about the wait. */
             empty={d ? "This is the only message on file for them." : undefined}>
        <table className="dt">
          <thead>
            <tr><Th>Subject</Th><Th>Kind</Th><Th>Channel</Th><Th>When</Th><Th>Status</Th></tr>
          </thead>
          {!d ? (
            <GhostRows cols={5} rows={3}
                       widths={["75%", "45%", "40%", "60%", "40%"]} />
          ) : (
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
          )}
        </table>
      </Panel>
    </RecordPage>
  );
}
