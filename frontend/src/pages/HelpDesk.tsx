import { FormEvent, useEffect, useMemo, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDateTime, errorText  } from "../api";
import DraftEditor from "../components/DraftEditor";
import DataTable, { Column, Truncate } from "../components/DataTable";
import { applyFilters, emptyFilters, EntityLink, FilterBar, FilterState } from "../components/Filters";
import { HelpdeskStats, Patient, Ticket, User } from "../types";
import Checkbox from "../components/Checkbox";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import ClaudeIcon from "../components/ClaudeIcon";
import AiPhase from "../components/AiPhase";
import { useAiDraft } from "../hooks/useAiStream";

const CATEGORIES = [
  ["query", "General query"], ["complaint", "Complaint"], ["refund", "Refund"],
  ["script_issue", "Script issue"], ["delivery", "Delivery"], ["stock", "Stock"], ["other", "Other"],
];
const PRIORITIES = [["low", "Low"], ["normal", "Normal"], ["high", "High"], ["urgent", "Urgent"]];

function slaBadge(t: Ticket) {
  if (t.status === "resolved" || t.status === "closed") return <span className="badge ok">resolved</span>;
  if (!t.due_at) return null;
  const mins = Math.round((new Date(t.due_at).getTime() - Date.now()) / 60000);
  if (mins < 0) return <span className="badge danger">SLA breached</span>;
  if (mins < 120) return <span className="badge warn">due in {mins}m</span>;
  return <span className="badge ok">{Math.round(mins / 60)}h left</span>;
}

export default function HelpDesk() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<HelpdeskStats | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [filter, setFilter] = useState("open");
  const [filters, setFilters] = useState<FilterState>(emptyFilters);

  const shownTickets = useMemo(() => applyFilters(tickets, filters, {
    search: (t) => [t.subject, t.ticket_number, t.patient?.first_name, t.patient?.last_name,
                    t.contact?.first_name, t.contact?.last_name, t.company?.name],
    date: (t) => t.created_at,
    dims: { category: (t) => t.category, priority: (t) => t.priority },
  }), [tickets, filters]);

  const caseCols: Column<Ticket>[] = [
    { key: "subject", header: "Case", sortable: true, value: (t) => t.subject,
      render: (t) => (
        <>
          <EntityLink to={`/cases/${t.id}`}><Truncate text={t.subject} at={54} /></EntityLink>
          <div className="muted mono" style={{ fontSize: 11 }}>
            {t.ticket_number} · {t.channel.replace("_", " ")}
          </div>
        </>
      ) },
    { key: "customer", header: "Customer", sortable: true,
      value: (t) => t.patient ? `${t.patient.last_name}` : t.contact ? `${t.contact.last_name}` : t.company?.name ?? "",
      render: (t) => (
        t.patient ? <EntityLink to={`/patients/${t.patient.id}`} muted>{t.patient.first_name} {t.patient.last_name}</EntityLink>
        : t.contact ? <EntityLink to={`/contacts/${t.contact.id}`} muted>{t.contact.first_name} {t.contact.last_name}</EntityLink>
        : t.company ? <EntityLink to={`/accounts/${t.company.id}`} muted>{t.company.name}</EntityLink>
        : <span className="muted">—</span>
      ) },
    { key: "category", header: "Category", sortable: true,
      render: (t) => <span className="badge muted">{t.category.replace(/_/g, " ")}</span> },
    { key: "priority", header: "Priority", sortable: true,
      render: (t) => (
        <span className={`badge ${t.priority === "urgent" ? "danger" : t.priority === "high" ? "warn" : "muted"}`}>
          {t.priority}
        </span>
      ) },
    { key: "sla", header: "SLA", render: (t) => slaBadge(t) },
    { key: "assigned", header: "Assigned", sortable: true, value: (t) => t.assigned_to?.full_name ?? "",
      render: (t) => t.assigned_to?.full_name ?? <span className="muted">unassigned</span> },
    { key: "status", header: "Status", sortable: true,
      render: (t) => (
        <span className={`badge ${t.status === "open" ? "warn" : t.status === "pending" ? "muted" : "ok"}`}>
          {t.status}
        </span>
      ) },
    { key: "created_at", header: "Opened", sortable: true, value: (t) => t.created_at,
      render: (t) => <span className="muted">{fmtDateTime(t.created_at)}</span> },
  ];
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [reply, setReply] = useState("");
  const [internal, setInternal] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patientQ, setPatientQ] = useState("");
  const [form, setForm] = useState<any>({
    subject: "", description: "", category: "query", priority: "normal",
    channel: "walk_in", patient_id: null as number | null,
    // Who the case is really for. A pharmacy serving corporate accounts takes
    // cases from the account as often as from a patient — "Delta's invoice is
    // wrong" is not about anybody's medicine — and the endpoint has always
    // accepted both. Without them every such case was filed against nobody.
    company_id: null as number | null,
    contact_id: null as number | null,
  });
  const [companies, setCompanies] = useState<any[]>([]);
  const [contacts, setContacts] = useState<any[]>([]);
  const toast = useToast();

  function load() {
    const q = filter === "breached" ? "breached=true" : `status=${filter}`;
    api.get<Ticket[]>(`/api/helpdesk/tickets?${q}`).then(setTickets).catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
    api.get<HelpdeskStats>("/api/helpdesk/stats").then(setStats);
  }

  useEffect(load, [filter]);
  useEffect(() => { api.get<User[]>("/api/auth/users").then(setUsers).catch(() => {}); }, []);
  useEffect(() => {
    api.get<any>("/api/crm/companies?limit=200")
      .then((d) => setCompanies(d.items ?? d ?? [])).catch(() => setCompanies([]));
  }, []);
  // The people at the account this case belongs to, so the picker never offers
  // somebody from a different company.
  useEffect(() => {
    if (!form.company_id) { setContacts([]); return; }
    api.get<any>(`/api/crm/contacts?company_id=${form.company_id}&limit=100`)
      .then((d) => setContacts(d.items ?? d ?? [])).catch(() => setContacts([]));
  }, [form.company_id]);
  useEffect(() => {
    if (patientQ.length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=6`).then(setPatients);
  }, [patientQ]);

  async function open(t: Ticket) {
    const full = await api.get<Ticket>(`/api/helpdesk/tickets/${t.id}`);
    setSelected(full); setReply(""); setInternal(false);
  }

  async function sendReply(e: FormEvent) {
    e.preventDefault();
    if (!selected || !reply.trim()) return;
    try {
      const updated = await api.post<Ticket>(`/api/helpdesk/tickets/${selected.id}/messages`, {
        body: reply, internal_note: internal,
      });
      setSelected(updated); setReply(""); setInternal(false);
      load();
    } catch (err: any) { toast.error(errorText(err)); }
  }

  async function patch(patchBody: Record<string, unknown>) {
    if (!selected) return;
    try {
      const updated = await api.put<Ticket>(`/api/helpdesk/tickets/${selected.id}`, patchBody);
      setSelected(updated);
      load();
    } catch (err: any) { toast.error(errorText(err)); }
  }

  const ai = useAiDraft(setReply);
  const draftReply = () => {
    if (!selected) return;
    ai.draft(`/api/ai/ticket-reply/${selected.id}/stream`, undefined);
  };

  async function createTicket(e: FormEvent) {
    e.preventDefault();
    try {
      const t = await api.post<Ticket>("/api/helpdesk/tickets", form);
      setShowNew(false);
      setForm({ subject: "", description: "", category: "query", priority: "normal",
                channel: "walk_in", patient_id: null, company_id: null, contact_id: null });
      setPatientQ("");
      load();
      open(t);
    } catch (err: any) { toast.error(errorText(err)); }
  }

  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.value });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Cases</h1>
          <div className="sub">Customer service tickets with SLA targets, threaded replies and CSAT</div>
        </div>
        <button onClick={() => setShowNew(true)}>+ New Ticket</button>
      </div>

      {stats && (
        <div className="grid cols-4">
          <div className="card stat hero">
            <div className="label">Open tickets</div>
            <div className="value">{stats.open}</div>
            <div className="hint">{stats.awaiting_first_response} awaiting first reply</div>
          </div>
          <div className="card stat">
            <div className="label">SLA breached</div>
            <div className="value" style={{ color: stats.sla_breached ? "var(--danger)" : undefined }}>
              {stats.sla_breached}
            </div>
            <div className="hint">{stats.due_within_2h} due within 2h</div>
          </div>
          <div className="card stat">
            <div className="label">Avg first response</div>
            <div className="value">{stats.avg_first_response_mins ?? "—"}<span style={{ fontSize: 15 }}>{stats.avg_first_response_mins ? "m" : ""}</span></div>
            <div className="hint">resolution {stats.avg_resolution_hours ?? "—"}{stats.avg_resolution_hours ? "h" : ""}</div>
          </div>
          <div className="card stat">
            <div className="label">Satisfaction</div>
            <div className="value">{stats.csat ?? "—"}<span style={{ fontSize: 15 }}>{stats.csat ? " / 5" : ""}</span></div>
            <div className="hint">{stats.resolved_total} resolved all-time</div>
          </div>
        </div>
      )}

      <div className="pill-tabs">
        {[["open", "Open"], ["breached", "SLA breached"], ["pending", "Pending"],
          ["resolved", "Resolved"], ["", "All"]].map(([v, l]) => (
          <button key={v} className={filter === v ? "active" : ""} onClick={() => setFilter(v)}>{l}</button>
        ))}
      </div>

      <DataTable
          loading={loading}
        columns={caseCols}
        rows={shownTickets}
        rowKey={(t) => t.id}
        rowHref={(t) => `/cases/${t.id}`}
        initialSort={{ key: "created_at", dir: "desc" }}
        empty="No cases in this view"
        toolbar={
          <FilterBar
            value={filters} onChange={setFilters} placeholder="Search subject, number, customer…"
            showDates
            dimensions={[
              { key: "category", label: "Category",
                options: CATEGORIES as [string, string][] },
              { key: "priority", label: "Priority",
                options: [["urgent", "Urgent"], ["high", "High"], ["normal", "Normal"], ["low", "Low"]] },
            ]}
          />
        }
      />

      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 760 }}>
            <h2>{selected.subject}</h2>
            <div className="muted mono" style={{ marginTop: -10, marginBottom: 14 }}>
              {selected.ticket_number} · opened {fmtDateTime(selected.created_at)} · {slaBadge(selected)}
            </div>

            <div className="form-row">
              <div className="field">
                <label>Status</label>
                <Select
                  value={String(selected.status ?? "")}
                  onChange={(__value) => patch({ status: __value })}
                  options={[{ value: "open", label: "Open" }, { value: "pending", label: "Pending" }, { value: "resolved", label: "Resolved" }, { value: "closed", label: "Closed" }]}
                />
              </div>
              <div className="field">
                <label>Priority</label>
                <Select
                  value={String(selected.priority ?? "")}
                  onChange={(__value) => patch({ priority: __value })}
                  options={[...PRIORITIES.map(([v, l]) => ({ value: String(v), label: l }))]}
                />
              </div>
              <div className="field">
                <label>Assigned to</label>
                <Select
                  value={String(selected.assigned_to?.id)}
                  onChange={(__value) => patch({ assigned_to_id: __value ? Number(__value) : null })}
                  options={[{ value: "", label: "Unassigned" }, ...users.map((u) => ({ value: String(u.id), label: u.full_name }))]}
                />
              </div>
            </div>

            <div className="thread">
              {selected.messages.map((m) => (
                <div key={m.id} className={`msg ${m.internal_note ? "note" : m.from_customer ? "customer" : "staff"}`}>
                  <div className="who">
                    {m.internal_note ? "Internal note" : m.from_customer ? "Customer" : m.author?.full_name ?? "Staff"}
                    {" · "}{fmtDateTime(m.created_at)}
                  </div>
                  {m.body}
                </div>
              ))}
            </div>

            <form onSubmit={sendReply}>
              <div className="field">
                <label>Reply</label>
                <DraftEditor rows={4} value={reply} onChange={setReply}
                  audience="the customer" placeholder="Type your response to the customer…" />
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                {ai.streaming && <AiPhase phase={ai.phase} />}
                <button type="button" className="secondary"
                        onClick={ai.streaming ? ai.stop : draftReply}>
                  {ai.streaming ? "Stop" : <><ClaudeIcon size={14} /> Draft reply</>}
                </button>
                <Checkbox checked={internal} onChange={setInternal}>Internal note (not sent to customer)</Checkbox>
                <div className="spacer" />
                {(selected.status === "resolved" || selected.status === "closed") && (
                  <Select
                    value={String(selected.satisfaction)}
                    onChange={(__value) => patch({ satisfaction: Number(__value) })}
                    options={[{ value: "", label: "Rate CSAT…" }, ...[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `${n} / 5` }))]}
                  />
                )}
                <button type="submit" disabled={!reply.trim()}>Send</button>
              </div>
            </form>

            <div className="modal-actions">
              <button className="secondary" onClick={() => setSelected(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {showNew && (
        <div className="modal-backdrop" onClick={() => setShowNew(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>New ticket</h2>
            <form onSubmit={createTicket}>
              <div className="field"><label>Subject</label>
                <input required value={form.subject} onChange={set("subject")} /></div>
              <div className="field"><label>What happened?</label>
                <textarea rows={3} value={form.description} onChange={set("description")} /></div>
              <div className="form-row">
                <div className="field">
                  <label>Category</label>
                  <Select
                    value={String(form.category ?? "")}
                    onChange={(__value) => set("category")({ target: { value: __value } } as any)}
                    options={[...CATEGORIES.map(([v, l]) => ({ value: String(v), label: l }))]}
                  />
                </div>
                <div className="field">
                  <label>Priority</label>
                  <Select
                    value={String(form.priority ?? "")}
                    onChange={(__value) => set("priority")({ target: { value: __value } } as any)}
                    options={[...PRIORITIES.map(([v, l]) => ({ value: String(v), label: l }))]}
                  />
                </div>
                <div className="field">
                  <label>Channel</label>
                  <Select
                    value={String(form.channel ?? "")}
                    onChange={(__value) => set("channel")({ target: { value: __value } } as any)}
                    options={[{ value: "walk_in", label: "Walk-in" }, { value: "phone", label: "Phone" }, { value: "email", label: "Email" }, { value: "sms", label: "SMS" }, { value: "web", label: "Web" }]}
                  />
                </div>
              </div>
              <div className="field">
                <label>Link a patient (optional)</label>
                {form.patient_id ? (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <b>{patients.find((p) => p.id === form.patient_id)?.first_name ?? "Patient"} linked</b>
                    <IconButton action="remove" onClick={() => setForm({ ...form, patient_id: null })} type="button" />
                  </div>
                ) : (
                  <>
                    <input type="search" placeholder="Search patient…" value={patientQ}
                      onChange={(e) => setPatientQ(e.target.value)} />
                    {patients.map((p) => (
                      <div key={p.id} className="product-pick"
                        onClick={() => { setForm({ ...form, patient_id: p.id }); setPatientQ(""); }}>
                        <span>{p.last_name}, {p.first_name}</span>
                        <span className="muted">{p.phone}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>

              {/* Or the account it belongs to. A case about an invoice, a
                  delivery or a contract is the account's, not a patient's, and
                  filing it against nobody is how it stops being anybody's. */}
              <div className="field">
                <label>Account (optional)</label>
                <Select
                  value={form.company_id ? String(form.company_id) : ""}
                  onChange={(v) => setForm({
                    ...form,
                    company_id: v ? Number(v) : null,
                    // The contact belonged to the old account.
                    contact_id: null,
                  })}
                  options={[{ value: "", label: "Not about an account" },
                            ...companies.map((c: any) => ({
                              value: String(c.id), label: c.name }))]}
                />
              </div>
              {form.company_id && contacts.length > 0 && (
                <div className="field">
                  <label>Who raised it</label>
                  <Select
                    value={form.contact_id ? String(form.contact_id) : ""}
                    onChange={(v) => setForm({ ...form, contact_id: v ? Number(v) : null })}
                    options={[{ value: "", label: "Nobody in particular" },
                              ...contacts.map((c: any) => ({
                                value: String(c.id),
                                label: `${c.first_name} ${c.last_name}`.trim(),
                                hint: c.job_title || undefined }))]}
                  />
                </div>
              )}

              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowNew(false)}>Cancel</button>
                <button type="submit">Create ticket</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
