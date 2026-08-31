/** A campaign and what it actually sent.
 *
 *  The campaign list showed an audience size and a sent count, which says how
 *  many went out and nothing about how many arrived. The breakdown by status is
 *  the number that matters: a campaign that "sent" four hundred and failed a
 *  hundred and eighty is not a campaign that worked.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDateTime } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import BusyButton from "../components/BusyButton";
import { useAsk, useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";
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

  const load = useCallback(() => {
    api.get<Data>(`/api/marketing/campaigns/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That campaign could not be opened.")));
  }, [id]);
  useEffect(load, [load]);

  const failed = d?.by_status.failed ?? 0;

  const toast = useToast();
  const confirm = useConfirm();
  /** Send it. The endpoint existed and only the campaigns list reached it. */
  async function send() {
    if (!d) return;
    const ok = await confirm({
      title: `Send "${d.name}"?`,
      body: (
        <>
          <p>
            It goes by {d.channel} to everybody in the {d.segment} segment.
            This cannot be recalled once it has gone.
          </p>
          {d.sent_count > 0 && (
            <p className="muted">
              {d.sent_count} message(s) have already gone out on this campaign.
            </p>
          )}
        </>
      ),
      confirmLabel: "Send it",
    });
    if (!ok) return;
    try {
      await api.post(`/api/campaigns/${d.id}/send`, {});
      toast.ok("Queued for sending.");
      load();
    } catch (e) {
      toast.error(errorText(e, "That campaign could not be sent."));
    }
  }
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
      actions={d && (
        <div className="page-actions">
          {d.status !== "sent" && (
            <BusyButton className="btn primary" onClick={send}
                        busyLabel="Sending…">
              Send it
            </BusyButton>
          )}
        </div>
      )}
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
