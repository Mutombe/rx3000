import { FormEvent, useEffect, useMemo, useState } from "react";
import { useToast } from "../components/Toast";
import { useNavigate } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money } from "../api";
import { Avatar, Path, ScoreRing } from "../components/record";
import { DuplicateWarning, Lead, LeadScoreExplanation, User } from "../types";

const SOURCES = [
  ["referral", "Referral"], ["event", "Event / expo"], ["campaign", "Campaign"],
  ["web", "Website"], ["phone", "Phone"], ["walk_in", "Walk-in"],
];

/** Saved list views — the rail down the left, Salesforce-style. */
const VIEWS: { key: string; label: string; match: (l: Lead) => boolean }[] = [
  { key: "open", label: "Open leads", match: (l) => !["converted", "disqualified"].includes(l.status) },
  { key: "hot", label: "Hot & unworked", match: (l) => l.rating === "hot" && l.status === "new" },
  { key: "new", label: "New", match: (l) => l.status === "new" },
  { key: "working", label: "Working", match: (l) => l.status === "working" },
  { key: "nurturing", label: "Nurturing", match: (l) => l.status === "nurturing" },
  { key: "unassigned", label: "Unassigned", match: (l) => !l.owner_id && l.status !== "converted" },
  { key: "converted", label: "Converted", match: (l) => l.status === "converted" },
  { key: "disqualified", label: "Disqualified", match: (l) => l.status === "disqualified" },
  { key: "all", label: "All leads", match: () => true },
];

const PIPE_STAGES = [
  { key: "new", label: "New" },
  { key: "working", label: "Working" },
  { key: "nurturing", label: "Nurturing" },
  { key: "converted", label: "Converted" },
];

const EMPTY = {
  first_name: "", last_name: "", company_name: "", job_title: "", email: "", phone: "",
  source: "referral", interest: "", estimated_value: 0, marketing_opt_in: false,
};

function statusClass(s: string) {
  return s === "converted" ? "ok" : s === "disqualified" ? "danger" : s === "working" ? "warn" : "muted";
}

export default function Leads() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [view, setView] = useState("open");
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"list" | "board">("list");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [checked, setChecked] = useState<number[]>([]);
  const [explain, setExplain] = useState<LeadScoreExplanation | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<any>({ ...EMPTY });
  const [dupes, setDupes] = useState<DuplicateWarning[]>([]);
  const [converting, setConverting] = useState<Lead | null>(null);
  const [convertForm, setConvertForm] = useState({
    create_company: true, create_deal: true, deal_title: "", deal_value: 0, account_type: "business",
  });
  const toast = useToast();
  const navigate = useNavigate();

  function load() {
    api.get<Lead[]>("/api/crm/leads?status=").then(setLeads).catch((e) => toast.error(e.message));
  }
  useEffect(() => {
    load();
    api.get<User[]>("/api/auth/users").then(setUsers).catch(() => {});
  }, []);

  // live duplicate warning while typing contact details
  useEffect(() => {
    if (!showForm || (!form.email && !form.phone)) { setDupes([]); return; }
    const t = setTimeout(() => {
      api.get<DuplicateWarning[]>(
        `/api/crm/leads/duplicates?email=${encodeURIComponent(form.email)}&phone=${encodeURIComponent(form.phone)}`,
      ).then(setDupes).catch(() => setDupes([]));
    }, 400);
    return () => clearTimeout(t);
  }, [form.email, form.phone, showForm]);

  const rows = useMemo(() => {
    const matcher = VIEWS.find((v) => v.key === view)!.match;
    const needle = q.trim().toLowerCase();
    return leads
      .filter(matcher)
      .filter((l) => !needle || [l.first_name, l.last_name, l.company_name, l.email, l.phone, l.interest]
        .some((f) => (f ?? "").toLowerCase().includes(needle)))
      .sort((a, b) => b.score - a.score || b.id - a.id);
  }, [leads, view, q]);

  const selected = rows.find((l) => l.id === selectedId) ?? rows[0] ?? null;

  useEffect(() => {
    if (!selected) { setExplain(null); return; }
    setExplain(null);
    api.get<LeadScoreExplanation>(`/api/crm/leads/${selected.id}/score`).then(setExplain).catch(() => {});
  }, [selected?.id]);

  const stats = useMemo(() => {
    const open = leads.filter((l) => !["converted", "disqualified"].includes(l.status));
    const closed = leads.filter((l) => ["converted", "disqualified"].includes(l.status));
    const converted = leads.filter((l) => l.status === "converted");
    return {
      open: open.length,
      value: open.reduce((s, l) => s + l.estimated_value, 0),
      avgScore: open.length ? Math.round(open.reduce((s, l) => s + l.score, 0) / open.length) : 0,
      hot: open.filter((l) => l.rating === "hot").length,
      rate: closed.length ? Math.round((converted.length / closed.length) * 1000) / 10 : 0,
    };
  }, [leads]);

  async function save(e: FormEvent) {
    e.preventDefault(); toast.error("");
    try {
      const lead = await api.post<Lead>("/api/crm/leads", {
        ...form, estimated_value: Number(form.estimated_value) || 0,
      });
      toast.ok(`Lead captured — scored ${lead.score}/100 (${lead.rating})${lead.owner ? `, routed to ${lead.owner.full_name}` : ""}.`);
      setShowForm(false); setForm({ ...EMPTY }); setDupes([]);
      load();
    } catch (err: any) { toast.error(err.message); }
  }

  async function setStatusOf(lead: Lead, next: string) {
    let reason = "";
    if (next === "disqualified") reason = window.prompt("Why is this lead disqualified?") ?? "";
    try {
      await api.post(`/api/crm/leads/${lead.id}/status`, { status: next, disqualified_reason: reason });
      load();
    } catch (e: any) { toast.error(e.message); }
  }

  async function bulkAssign(ownerId: number) {
    if (!checked.length) return;
    try {
      await api.post("/api/crm/leads/bulk/assign", { lead_ids: checked, owner_id: ownerId });
      toast.ok(`${checked.length} lead(s) reassigned.`);
      setChecked([]);
      load();
    } catch (e: any) { toast.error(e.message); }
  }

  function openConvert(lead: Lead) {
    setConverting(lead);
    setConvertForm({
      create_company: Boolean(lead.company_name), create_deal: true,
      deal_title: `${lead.company_name || lead.last_name} — new opportunity`,
      deal_value: lead.estimated_value, account_type: "business",
    });
  }

  async function doConvert(e: FormEvent) {
    e.preventDefault();
    if (!converting) return;
    try {
      const res = await api.post<{ deal_id: number | null }>(`/api/crm/leads/${converting.id}/convert`, {
        ...convertForm, deal_value: Number(convertForm.deal_value) || 0,
      });
      setConverting(null);
      toast.ok("Lead converted into an account, a contact and an opportunity.");
      load();
      if (res.deal_id) navigate(`/deals/${res.deal_id}`);
    } catch (err: any) { toast.error(err.message); }
  }

  const set = (k: string) => (e: any) =>
    setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const toggleCheck = (id: number) =>
    setChecked((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Leads</h1>
          <div className="sub">Scored and routed on capture — qualify, then convert into an account, contact and opportunity</div>
        </div>
        <button onClick={() => setShowForm(true)}>+ New Lead</button>
      </div>

      <div className="grid cols-4">
        <div className="card stat hero">
          <div className="label">Open intake value</div>
          <div className="value">{money(stats.value)}</div>
          <div className="hint">{stats.open} open leads</div>
        </div>
        <div className="card stat">
          <div className="label">Hot leads</div>
          <div className="value">{stats.hot}</div>
          <div className="hint">scoring 60 and above</div>
        </div>
        <div className="card stat">
          <div className="label">Average score</div>
          <div className="value">{stats.avgScore}</div>
          <div className="hint">across open leads</div>
        </div>
        <div className="card stat">
          <div className="label">Conversion rate</div>
          <div className="value">{stats.rate}%</div>
          <div className="hint">of leads worked to a close</div>
        </div>
      </div>

      <div className="console">
        <aside className="console-rail">
          <div className="rail-title">List views</div>
          {VIEWS.map((v) => {
            const n = leads.filter(v.match).length;
            return (
              <button key={v.key} className={`rail-item${view === v.key ? " active" : ""}`}
                onClick={() => { setView(v.key); setChecked([]); }}>
                <span>{v.label}</span>
                <span className="rail-count">{n}</span>
              </button>
            );
          })}
        </aside>

        <section className="console-list">
          <div className="console-bar">
            <input type="search" placeholder="Search name, company, email…" value={q}
              onChange={(e) => setQ(e.target.value)} />
            <div className="seg">
              <button className={mode === "list" ? "on" : ""} onClick={() => setMode("list")}>List</button>
              <button className={mode === "board" ? "on" : ""} onClick={() => setMode("board")}>Board</button>
            </div>
            <span className="muted">{rows.length} record{rows.length === 1 ? "" : "s"}</span>
          </div>

          {checked.length > 0 && (
            <div className="bulk-bar">
              <b>{checked.length} selected</b>
              <select defaultValue="" onChange={(e) => { if (e.target.value) bulkAssign(Number(e.target.value)); }}>
                <option value="">Reassign to…</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </select>
              <button className="ghost small" onClick={() => setChecked([])}>Clear</button>
            </div>
          )}

          {mode === "list" ? (
            <div className="lead-rows">
              {rows.map((l) => (
                <div key={l.id}
                  className={`lead-row${selected?.id === l.id ? " active" : ""}`}
                  onClick={() => setSelectedId(l.id)}>
                  <input type="checkbox" checked={checked.includes(l.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggleCheck(l.id)} />
                  <Avatar first={l.first_name} last={l.last_name} />
                  <div className="lead-main">
                    <b>{l.first_name} {l.last_name}</b>
                    <div className="muted">{l.company_name || l.job_title || "—"}</div>
                  </div>
                  <div className="lead-meta">
                    <span className={`badge ${statusClass(l.status)}`}>{l.status}</span>
                    <span className="muted">{l.source.replace("_", " ")}</span>
                  </div>
                  <div className="lead-value">{l.estimated_value ? money(l.estimated_value) : <span className="muted">—</span>}</div>
                  <ScoreRing score={l.score} rating={l.rating} size={40} />
                </div>
              ))}
              {rows.length === 0 && <div className="empty">No leads in this view</div>}
            </div>
          ) : (
            <div className="lead-board">
              {PIPE_STAGES.map((st) => {
                const items = rows.filter((l) => l.status === st.key);
                return (
                  <div key={st.key} className="board-col">
                    <div className="board-head">
                      <span>{st.label}</span><span className="badge muted">{items.length}</span>
                    </div>
                    <div className="board-total">
                      {money(items.reduce((s, l) => s + l.estimated_value, 0))}
                    </div>
                    {items.map((l) => (
                      <div key={l.id} className={`board-card${selected?.id === l.id ? " active" : ""}`}
                        onClick={() => setSelectedId(l.id)}>
                        <div className="board-card-top">
                          <b>{l.first_name} {l.last_name}</b>
                          <ScoreRing score={l.score} rating={l.rating} size={34} />
                        </div>
                        <div className="muted">{l.company_name || "—"}</div>
                        <div className="board-card-foot">
                          <span>{money(l.estimated_value)}</span>
                          <span className="muted">{l.source.replace("_", " ")}</span>
                        </div>
                      </div>
                    ))}
                    {items.length === 0 && <div className="muted" style={{ fontSize: 12, padding: "8px 2px" }}>Empty</div>}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <aside className="console-detail">
          {!selected ? (
            <div className="empty">Select a lead to see the full record</div>
          ) : (
            <>
              <div className="detail-head">
                <Avatar first={selected.first_name} last={selected.last_name} size={46} />
                <div>
                  <h3>{selected.first_name} {selected.last_name}</h3>
                  <div className="muted">
                    {selected.job_title}{selected.job_title && selected.company_name ? " · " : ""}
                    {selected.company_name}
                  </div>
                </div>
              </div>

              <Path stages={PIPE_STAGES} current={selected.status} lostKey="disqualified" />

              <div className="detail-actions">
                {selected.status === "converted" ? (
                  selected.converted_deal_id ? (
                    <button className="small" onClick={() => navigate(`/deals/${selected.converted_deal_id}`)}>
                      Open opportunity
                    </button>
                  ) : <span className="muted">Converted {fmtDate(selected.converted_at)}</span>
                ) : selected.status === "disqualified" ? (
                  <button className="secondary small" onClick={() => setStatusOf(selected, "working")}>Requalify</button>
                ) : (
                  <>
                    <button className="small" onClick={() => openConvert(selected)}>Convert</button>
                    {selected.status === "new" &&
                      <button className="secondary small" onClick={() => setStatusOf(selected, "working")}>Start working</button>}
                    {selected.status !== "nurturing" &&
                      <button className="secondary small" onClick={() => setStatusOf(selected, "nurturing")}>Nurture</button>}
                    <button className="ghost small" onClick={() => setStatusOf(selected, "disqualified")}>Disqualify</button>
                  </>
                )}
              </div>

              <dl className="detail-fields">
                <div><dt>Email</dt><dd>{selected.email || "—"}</dd></div>
                <div><dt>Phone</dt><dd>{selected.phone || "—"}</dd></div>
                <div><dt>Source</dt><dd>{selected.source.replace("_", " ")}</dd></div>
                <div><dt>Owner</dt><dd>{selected.owner?.full_name ?? "Unassigned"}</dd></div>
                <div><dt>Estimated value</dt><dd>{money(selected.estimated_value)}</dd></div>
                <div><dt>Captured</dt><dd>{fmtDateTime(selected.created_at)}</dd></div>
                <div><dt>Marketing consent</dt>
                  <dd>{selected.marketing_opt_in
                    ? <span className="badge ok">granted</span>
                    : <span className="badge muted">not granted</span>}</dd></div>
              </dl>

              {selected.interest && (
                <div className="detail-block">
                  <h4>Enquiry</h4>
                  <p className="muted">{selected.interest}</p>
                </div>
              )}

              {selected.disqualified_reason && (
                <div className="detail-block">
                  <h4>Disqualified because</h4>
                  <p className="muted">{selected.disqualified_reason}</p>
                </div>
              )}

              <div className="detail-block">
                <h4>
                  Why this score
                  <ScoreRing score={selected.score} rating={selected.rating} size={44} />
                </h4>
                {!explain ? (
                  <p className="muted">Working it out…</p>
                ) : (
                  <>
                    {Array.from(new Set(explain.factors.map((f) => f.group))).map((group) => (
                      <div key={group}>
                        <div className="factor-group">{group}</div>
                        {explain.factors.filter((f) => f.group === group).map((f) => (
                          <div key={f.label} className="factor">
                            <div className="factor-top">
                              <span>{f.label}</span>
                              <b className={f.points > 0 ? "" : "muted"}>
                                {f.points > 0 ? `+${f.points}` : "0"}
                              </b>
                            </div>
                            <div className="factor-track">
                              <div className="factor-fill"
                                style={{ width: `${f.max ? (f.points / f.max) * 100 : 0}%` }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    ))}
                    {explain.capped && (
                      <p className="muted" style={{ fontSize: 12 }}>
                        Raw total {explain.raw_score} — capped at 100.
                      </p>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </aside>
      </div>

      {showForm && (
        <div className="modal-backdrop" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>New lead</h2>
            <form onSubmit={save}>
              <div className="form-row">
                <div className="field"><label>First name</label><input required value={form.first_name} onChange={set("first_name")} /></div>
                <div className="field"><label>Last name</label><input required value={form.last_name} onChange={set("last_name")} /></div>
              </div>
              <div className="form-row">
                <div className="field"><label>Company</label><input value={form.company_name} onChange={set("company_name")} /></div>
                <div className="field"><label>Job title</label><input value={form.job_title} onChange={set("job_title")} /></div>
              </div>
              <div className="form-row">
                <div className="field"><label>Email</label><input type="email" value={form.email} onChange={set("email")} /></div>
                <div className="field"><label>Phone</label><input value={form.phone} onChange={set("phone")} /></div>
              </div>
              {dupes.length > 0 && (
                <div className="error-banner">
                  Possible duplicate:{" "}
                  {dupes.map((d) => `${d.existing_label} (existing ${d.existing_type}, same ${d.field})`).join("; ")}
                </div>
              )}
              <div className="form-row">
                <div className="field">
                  <label>Source</label>
                  <select value={form.source} onChange={set("source")}>
                    {SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="field"><label>Estimated value</label>
                  <input type="number" step="0.01" value={form.estimated_value} onChange={set("estimated_value")} /></div>
              </div>
              <div className="field"><label>What are they interested in?</label>
                <textarea rows={3} value={form.interest} onChange={set("interest")} /></div>
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input type="checkbox" checked={form.marketing_opt_in} onChange={set("marketing_opt_in")} />
                Consented to marketing communication (POPIA)
              </label>
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowForm(false)}>Cancel</button>
                <button type="submit">Capture lead</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {converting && (
        <div className="modal-backdrop" onClick={() => setConverting(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
            <h2>Convert {converting.first_name} {converting.last_name}</h2>
            <p className="muted">
              Score {converting.score}/100 ({converting.rating}). Converting creates a contact, and
              optionally an account and an opportunity — the lead becomes read-only.
            </p>
            <form onSubmit={doConvert}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <input type="checkbox" checked={convertForm.create_company}
                  onChange={(e) => setConvertForm({ ...convertForm, create_company: e.target.checked })} />
                Create / link account {converting.company_name && <b>&nbsp;{converting.company_name}</b>}
              </label>
              {convertForm.create_company && (
                <div className="field">
                  <label>Account type</label>
                  <select value={convertForm.account_type}
                    onChange={(e) => setConvertForm({ ...convertForm, account_type: e.target.value })}>
                    <option value="clinic">Clinic / practice</option>
                    <option value="old_age_home">Old-age home</option>
                    <option value="employer">Employer / occupational health</option>
                    <option value="wholesale">Wholesale buyer</option>
                    <option value="business">Other business</option>
                  </select>
                </div>
              )}
              <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <input type="checkbox" checked={convertForm.create_deal}
                  onChange={(e) => setConvertForm({ ...convertForm, create_deal: e.target.checked })} />
                Create an opportunity
              </label>
              {convertForm.create_deal && (
                <div className="form-row">
                  <div className="field"><label>Opportunity title</label>
                    <input value={convertForm.deal_title}
                      onChange={(e) => setConvertForm({ ...convertForm, deal_title: e.target.value })} /></div>
                  <div className="field" style={{ maxWidth: 160 }}><label>Value</label>
                    <input type="number" step="0.01" value={convertForm.deal_value}
                      onChange={(e) => setConvertForm({ ...convertForm, deal_value: Number(e.target.value) })} /></div>
                </div>
              )}
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setConverting(null)}>Cancel</button>
                <button type="submit">Convert lead</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
