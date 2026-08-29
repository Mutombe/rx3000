import { FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { useConfirm } from "../components/Confirm";
import { api, fmtDateTime, errorText  } from "../api";
import DraftEditor from "../components/DraftEditor";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Campaign, Message, Patient, Segment } from "../types";
import Pagination, { Paged } from "../components/Pagination";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import ClaudeIcon from "../components/ClaudeIcon";
import AiPhase from "../components/AiPhase";
import { useAiDraft } from "../hooks/useAiStream";
import { EntityLink } from "../components/Filters";
import { Refreshable, TableSkeleton } from "../components/Skeleton";

type Tab = "compose" | "history";

export default function Marketing() {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(true);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignMeta, setCampaignMeta] = useState<Paged<Campaign> | null>(null);
  const [campaignPage, setCampaignPage] = useState(1);
  const [channel, setChannel] = useState("sms");
  const [segment, setSegment] = useState("all_patients");
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [goal, setGoal] = useState("");
  const [preview, setPreview] = useState<Patient[]>([]);
  const [sentMessages, setSentMessages] = useState<Message[] | null>(null);
  const toast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);

  const TABS: TabDef<Tab>[] = [
    { key: "compose", label: "New campaign" },
    { key: "history", label: "Campaign history", count: campaigns.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "compose");

  function loadSegments() {
    api.get<Segment[]>(`/api/marketing/segments?channel=${channel}`).then(setSegments)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }
  function loadCampaigns() {
    api.get<Paged<Campaign>>(`/api/marketing/campaigns/paged?page=${campaignPage}&per_page=25`)
      .then((res) => {
        setCampaigns(res.items); setCampaignMeta(res);
        if (res.page !== campaignPage) setCampaignPage(res.page);
      });
  }

  useEffect(loadSegments, [channel]);
  useEffect(loadCampaigns, []);
  useEffect(() => {
    api.get<Patient[]>(`/api/marketing/segments/${segment}/preview?channel=${channel}&limit=8`)
      .then(setPreview).catch(() => setPreview([]));
  }, [segment, channel]);

  const chosen = segments.find((s) => s.key === segment);

  const ai = useAiDraft(setBody);
  const draftCopy = () => ai.draft("/api/ai/campaign-copy/stream", {
    name: name || "Pharmacy campaign", channel,
    segment_label: chosen?.label ?? "patients",
    goal: goal || "Encourage patients to visit the pharmacy",
  });

  async function createAndSend(e: FormEvent) {
    e.preventDefault();
    const ok = await confirm({
      title: `Send this ${channel.toUpperCase()}?`,
      body: (
        <>
          It will go to <b>{chosen?.size ?? 0} recipient(s)</b> immediately.
          A message cannot be recalled once sent.
        </>
      ),
      confirmLabel: "Send now",
    });
    if (!ok) return;
    setBusy(true);
    try {
      const campaign = await api.post<Campaign>("/api/marketing/campaigns", {
        name, channel, segment, subject, body,
      });
      const sent = await api.post<Campaign>(`/api/marketing/campaigns/${campaign.id}/send`);
      toast.ok(`"${sent.name}" delivered to ${sent.sent_count} recipient(s)${sent.failed_count ? `, ${sent.failed_count} failed` : ""}.`);
      setName(""); setSubject(""); setBody(""); setGoal("");
      loadCampaigns(); loadSegments();
    } catch (err: any) { toast.error(errorText(err)); } finally { setBusy(false); }
  }

  async function viewMessages(c: Campaign) {
    const msgs = await api.get<Message[]>(`/api/marketing/campaigns/${c.id}/messages`);
    setSentMessages(msgs);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Campaigns</h1>
          <div className="sub">Segment your patient base and run SMS or email campaigns, consent-aware</div>
        </div>
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "compose" && (
      <div className="grid cols-2">
        <div className="card">
          <h3>1 · Choose an audience</h3>
          <div className="field">
            <label>Channel</label>
            <Select
              value={String(channel ?? "")}
              onChange={(__value) => setChannel(__value)}
              options={[{ value: "sms", label: "SMS" }, { value: "email", label: "Email" }]}
            />
          </div>
          {segments.map((s) => (
            // Selection was a white background and a one-pixel border against a
            // near-white card — on screen it was almost impossible to tell which
            // audience was chosen, and choosing the wrong audience sends the
            // campaign to the wrong people.
            <div
              key={s.key}
              className={`product-pick${segment === s.key ? " is-chosen" : ""}`}
              role="radio"
              aria-checked={segment === s.key}
              onClick={() => setSegment(s.key)}
            >
              <span>
                <b>{s.label}</b>
                <div className="muted" style={{ fontSize: 11.5 }}>{s.description}</div>
              </span>
              <span className={`badge ${s.size ? "" : "muted"}`}>{s.size}</span>
            </div>
          ))}
          {preview.length > 0 && (
            <div className="muted" style={{ marginTop: 12, fontSize: 12 }}>
              Sample: {preview.map((p) => `${p.first_name} ${p.last_name}`).join(", ")}
              {chosen && chosen.size > preview.length ? ` … +${chosen.size - preview.length} more` : ""}
            </div>
          )}
        </div>

        <div className="card">
          <h3>2 · Compose &amp; send</h3>
          <form onSubmit={createAndSend}>
            <div className="field"><label>Campaign name</label>
              <input required value={name} onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Flu season 2026" /></div>
            {channel === "email" && (
              <div className="field"><label>Subject line</label>
                <input value={subject} onChange={(e) => setSubject(e.target.value)} /></div>
            )}
            <div className="field">
              <label>Goal (for the AI copywriter)</label>
              <input value={goal} onChange={(e) => setGoal(e.target.value)}
                placeholder="e.g. Drive walk-ins for flu vaccination" />
            </div>
            <div className="field">
              <label>
                Message, merge fields:{" "}
                <span className="mono">{"{first_name} {points} {pharmacy}"}</span>
              </label>
              <DraftEditor rows={5} required value={body} onChange={setBody}
                audience="the customer" placeholder="Hi {first_name}, flu vaccines are now in stock at {pharmacy}…" />
              {channel === "sms" && (
                <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                  {body.length} characters {body.length > 160 && "· over one SMS segment"}
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              {ai.streaming && <AiPhase phase={ai.phase} />}
              <button type="button" className="secondary"
                      onClick={ai.streaming ? ai.stop : draftCopy}>
                {ai.streaming ? "Stop" : <><ClaudeIcon size={14} /> Draft with AI</>}
              </button>
              <button type="submit" disabled={busy || !body.trim() || !(chosen?.size)}>
                {busy ? "Sending…" : `Send to ${chosen?.size ?? 0}`}
              </button>
            </div>
          </form>
        </div>
      </div>
      )}

      {tab === "history" && (
      <div className="card">
        <table>
          <thead>
            <tr><th>Campaign</th><th>Channel</th><th>Segment</th><th className="num">Audience</th>
              <th className="num">Sent</th><th className="num">Failed</th><th>Status</th><th>When</th><th className="actions" /></tr>
          </thead>
          <tbody>
            {campaigns.map((c) => (
              <tr key={c.id}>
                <td><EntityLink kind="campaign" id={c.id}><b>{c.name}</b></EntityLink><div className="muted" style={{ maxWidth: 340 }}>{c.body.slice(0, 90)}…</div></td>
                <td>{c.channel.toUpperCase()}</td>
                <td className="muted">{c.segment.replace(/_/g, " ")}</td>
                <td className="num">{c.audience_size}</td>
                <td className="num">{c.sent_count}</td>
                <td className="num">{c.failed_count > 0 ? <span className="badge danger">{c.failed_count}</span> : 0}</td>
                <td><span className={`badge ${c.status === "sent" ? "ok" : "muted"}`}>{c.status}</span></td>
                <td className="muted">{c.sent_at ? fmtDateTime(c.sent_at) : fmtDateTime(c.created_at)}</td>
                <td className="right">
                  {c.status === "sent" && <IconButton action="view" onClick={() => viewMessages(c)} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
            {campaignMeta && <Pagination meta={campaignMeta} onPage={setCampaignPage} noun="campaigns" />}
        {loading && campaigns.length === 0 && (
          <TableSkeleton cols={9} rows={4} />
        )}
        {!loading && campaigns.length === 0 && (
          <div className="empty">
            <b>No campaigns yet</b>
            <p>
              A campaign goes to a segment — a group of patients the pharmacy
              has a reason to write to. Build the segment first.
            </p>
          </div>
        )}
      </div>
      )}

      {sentMessages && (
        <div className="modal-backdrop" onClick={() => setSentMessages(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Delivered messages</h2>
            <table>
              <thead><tr><th>Patient</th><th>Message</th><th>Status</th></tr></thead>
              <tbody>
                {sentMessages.map((m) => (
                  <tr key={m.id}>
                    <td><EntityLink kind="patient" id={m.patient_id}>{m.patient ? `${m.patient.first_name} ${m.patient.last_name}` : m.patient_id}</EntityLink></td>
                    <td style={{ maxWidth: 380 }}>{m.body}</td>
                    <td><span className={`badge ${m.status === "sent" ? "ok" : "danger"}`}>{m.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="modal-actions">
              <button className="secondary" onClick={() => setSentMessages(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
