import { FormEvent, useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, fmtDateTime } from "../api";
import DraftEditor from "../components/DraftEditor";
import { EntityLink } from "../components/Filters";
import { Avatar, Highlights, Path } from "../components/record";
import { Ticket, User } from "../types";
import Checkbox from "../components/Checkbox";
import Select from "../components/Select";
import ClaudeIcon from "../components/ClaudeIcon";
import AiPhase from "../components/AiPhase";
import { useAiDraft } from "../hooks/useAiStream";
import { ArrowLeft } from "@phosphor-icons/react";

const PRIORITIES: [string, string][] = [
  ["low", "Low"], ["normal", "Normal"], ["high", "High"], ["urgent", "Urgent"],
];
const PATH_STAGES = [
  { key: "open", label: "Open" },
  { key: "pending", label: "Pending" },
  { key: "resolved", label: "Resolved" },
  { key: "closed", label: "Closed" },
];

function slaBadge(t: Ticket) {
  if (!t.due_at) return <span className="badge muted">no SLA</span>;
  if (t.first_response_at) return <span className="badge ok">responded</span>;
  const late = new Date(t.due_at).getTime() < Date.now();
  return late
    ? <span className="badge danger">SLA breached</span>
    : <span className="badge warn">due {fmtDateTime(t.due_at)}</span>;
}

export default function CaseDetail() {
  const { id } = useParams();
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [reply, setReply] = useState("");
  const [internal, setInternal] = useState(false);
  const [error, setError] = useState("");

  function load() {
    api.get<Ticket>(`/api/helpdesk/tickets/${id}`).then(setTicket).catch((e) => setError(e.message));
  }
  useEffect(() => {
    load();
    api.get<User[]>("/api/auth/users").then(setUsers).catch(() => {});
  }, [id]);

  async function patch(body: any) {
    try { setTicket(await api.put<Ticket>(`/api/helpdesk/tickets/${id}`, body)); }
    catch (e: any) { setError(e.message); }
  }

  async function sendReply(e: FormEvent) {
    e.preventDefault();
    if (!reply.trim()) return;
    try {
      setTicket(await api.post<Ticket>(`/api/helpdesk/tickets/${id}/messages`, {
        body: reply, internal_note: internal, from_customer: false,
      }));
      setReply("");
    } catch (err: any) { setError(err.message); }
  }

  /* The draft lands in the box as it is written, so the staff member can start
     reading — and start disagreeing — before it has finished. */
  const ai = useAiDraft(setReply);
  const draftReply = () => ai.draft(`/api/ai/ticket-reply/${id}/stream`, undefined);

  if (error)
    return (
      <div className="page">
        {/* A page that could not load says so in place. A toast over a
            blank screen tells nobody what they were looking at. */}
        <div className="alert error">{error}</div>
        <p className="muted pad">
          Nothing was loaded for this record. Check the connection and try again.
        </p>
      </div>
    );
  if (!ticket) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Help desk", to: "/helpdesk" }, { label: "This record" }]}
        eyebrow="Case"
        cards={2}
      />;

  return (
    <>
      <Breadcrumbs trail={[{ label: "Dashboard", to: "/" }, { label: "Help desk", to: "/helpdesk" }, { label: "This record" }]} />
      <div className="page-head">
        <div className="record-title">
          <Avatar first={ticket.subject} last="" size={44} />
          <div>
            <div className="eyebrow">Case {ticket.ticket_number}</div>
            <h1>{ticket.subject}</h1>
            <div className="sub">
              opened {fmtDateTime(ticket.created_at)}
              {ticket.company && <> · <EntityLink to={`/accounts/${ticket.company.id}`}>{ticket.company.name}</EntityLink></>}
            </div>
          </div>
        </div>
        <Link to="/helpdesk" className="btn secondary"><ArrowLeft size={13} weight="bold" /> Cases</Link>
      </div>

      <div className="card record-hero">
        <Path stages={PATH_STAGES} current={ticket.status} onPick={(s) => patch({ status: s })} />
        <Highlights items={[
          { label: "Priority", value: ticket.priority, hint: slaBadge(ticket) },
          { label: "Category", value: ticket.category.replace(/_/g, " "), hint: ticket.channel || "—" },
          { label: "Assigned to", value: ticket.assigned_to?.full_name ?? "Unassigned",
            hint: ticket.assigned_to?.role ?? "route with an automation rule" },
          { label: "Replies", value: String(ticket.messages.length),
            hint: ticket.first_response_at ? `first reply ${fmtDateTime(ticket.first_response_at)}` : "no reply yet" },
          { label: "CSAT", value: ticket.satisfaction ? `${ticket.satisfaction}/5` : "—",
            hint: "customer rating" },
        ]} />
        <div className="form-row" style={{ marginTop: 14 }}>
          <div className="field">
            <label>Priority</label>
            <Select
              value={String(ticket.priority ?? "")}
              onChange={(__value) => patch({ priority: __value })}
              options={[...PRIORITIES.map(([v, l]) => ({ value: String(v), label: l }))]}
            />
          </div>
          <div className="field">
            <label>Assigned to</label>
            <Select
              value={String(ticket.assigned_to?.id)}
              onChange={(__value) => patch({ assigned_to_id: __value ? Number(__value) : null })}
              options={[{ value: "", label: "Unassigned" }, ...users.map((u) => ({ value: String(u.id), label: u.full_name }))]}
            />
          </div>
          {(ticket.status === "resolved" || ticket.status === "closed") && (
            <div className="field">
              <label>Customer satisfaction</label>
              <Select
                value={String(ticket.satisfaction)}
                onChange={(__value) => patch({ satisfaction: Number(__value) })}
                options={[{ value: "", label: "Rate CSAT…" }, ...[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `${n} / 5` }))]}
              />
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Conversation</h3>
        <div className="thread">
          {ticket.messages.map((m) => (
            <div key={m.id} className={`msg ${m.internal_note ? "note" : m.from_customer ? "customer" : "staff"}`}>
              <div className="who">
                {m.internal_note ? "Internal note" : m.from_customer ? "Customer" : m.author?.full_name ?? "Staff"}
                {" · "}{fmtDateTime(m.created_at)}
              </div>
              {m.body}
            </div>
          ))}
          {ticket.messages.length === 0 && <div className="empty">No messages yet</div>}
        </div>

        <form onSubmit={sendReply}>
          <div className="field">
            <label>Reply</label>
            <DraftEditor rows={4} value={reply} onChange={setReply}
                  audience="the customer" placeholder="Type your response to the customer…" />
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {/* Stops rather than sits disabled: a draft that is going the wrong
                way should be interruptible, not waited out. */}
            {ai.streaming && <AiPhase phase={ai.phase} />}
            <button type="button" className="secondary"
                    onClick={ai.streaming ? ai.stop : draftReply}>
              {ai.streaming ? "Stop" : <><ClaudeIcon size={14} /> Draft reply</>}
            </button>
            <Checkbox checked={internal} onChange={setInternal}>Internal note (not sent to customer)</Checkbox>
            <button type="submit" disabled={!reply.trim()}>Send</button>
          </div>
        </form>
      </div>
    </>
  );
}
