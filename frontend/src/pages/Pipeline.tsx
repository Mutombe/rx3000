import { FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { useNavigate } from "react-router-dom";
import { api, fmtDate, money } from "../api";
import { Avatar } from "../components/record";
import { Company, Contact, CrmDashboard, Deal } from "../types";

/** Days since a date, used to flag deals going stale in a stage. */
function ageDays(iso: string) {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000));
}

const STAGES = [
  { key: "new", label: "New" },
  { key: "qualified", label: "Qualified" },
  { key: "proposal", label: "Proposal" },
  { key: "negotiation", label: "Negotiation" },
  { key: "won", label: "Won" },
  { key: "lost", label: "Lost" },
];

const EMPTY = {
  title: "", company_id: "" as string | number, contact_id: "" as string | number,
  value: 0, stage: "new", expected_close_date: "", source: "", notes: "",
};

export default function Pipeline() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [stats, setStats] = useState<CrmDashboard | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<any>({ ...EMPTY });
  const toast = useToast();
  const navigate = useNavigate();

  function load() {
    api.get<Deal[]>("/api/crm/deals").then(setDeals).catch((e) => toast.error(e.message));
    api.get<CrmDashboard>("/api/crm/dashboard").then(setStats);
  }

  useEffect(() => {
    load();
    api.get<Company[]>("/api/crm/companies").then(setCompanies);
    api.get<Contact[]>("/api/crm/contacts").then(setContacts);
  }, []);

  async function moveDeal(dealId: number, stage: string) {
    const deal = deals.find((d) => d.id === dealId);
    if (!deal || deal.stage === stage) return;
    let lost_reason = "";
    if (stage === "lost") {
      lost_reason = window.prompt("Why was this deal lost?") ?? "";
    }
    // optimistic
    setDeals((ds) => ds.map((d) => (d.id === dealId ? { ...d, stage } : d)));
    try {
      await api.post(`/api/crm/deals/${dealId}/stage`, { stage, lost_reason });
      load();
    } catch (e: any) {
      toast.error(e.message);
      load();
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/crm/deals", {
        ...form,
        value: Number(form.value) || 0,
        company_id: form.company_id === "" ? null : Number(form.company_id),
        contact_id: form.contact_id === "" ? null : Number(form.contact_id),
        expected_close_date: form.expected_close_date || null,
      });
      setShowForm(false);
      setForm({ ...EMPTY });
      load();
    } catch (err: any) { toast.error(err.message); }
  }

  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.value });
  const byStage = (s: string) => deals.filter((d) => d.stage === s);
  const grandTotal = deals.reduce((s, d) => s + d.value, 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Opportunities</h1>
          <div className="sub">Supply contracts, wellness programmes and corporate opportunities — drag cards to move a deal</div>
        </div>
        <button onClick={() => setShowForm(true)}>+ New Deal</button>
      </div>

      {stats && (
        <div className="grid cols-4">
          <div className="card stat hero">
            <div className="label">Open pipeline</div>
            <div className="value">{money(stats.pipeline_value)}</div>
            <div className="hint">{stats.open_deals} open deals</div>
          </div>
          <div className="card stat">
            <div className="label">Weighted forecast</div>
            <div className="value">{money(stats.weighted_value)}</div>
            <div className="hint">by stage probability</div>
          </div>
          <div className="card stat">
            <div className="label">Won</div>
            <div className="value">{money(stats.won_value)}</div>
            <div className="hint">{stats.won_count} deals</div>
          </div>
          <div className="card stat">
            <div className="label">Win rate</div>
            <div className="value">{stats.win_rate}%</div>
            <div className="hint">of closed deals</div>
          </div>
        </div>
      )}

      <div className="kanban">
        {STAGES.map((stage) => {
          const items = byStage(stage.key);
          const total = items.reduce((s, d) => s + d.value, 0);
          return (
            <div
              key={stage.key}
              className={`kanban-col${hover === stage.key ? " over" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setHover(stage.key); }}
              onDragLeave={() => setHover(null)}
              onDrop={(e) => {
                e.preventDefault();
                setHover(null);
                if (dragging !== null) moveDeal(dragging, stage.key);
                setDragging(null);
              }}
            >
              <div className="kanban-head">
                <span>{stage.label}</span>
                <span className="badge muted">{items.length}</span>
              </div>
              <div className="kanban-total">{money(total)}</div>
              <div className="kanban-share">
                <div style={{ width: `${grandTotal ? (total / grandTotal) * 100 : 0}%` }} />
              </div>
              {items.map((d) => {
                const age = ageDays(d.created_at);
                const stale = age > 30 && !["won", "lost"].includes(d.stage);
                return (
                  <div
                    key={d.id}
                    className={`deal-card${stale ? " stale" : ""}`}
                    draggable
                    onDragStart={() => setDragging(d.id)}
                    onDragEnd={() => { setDragging(null); setHover(null); }}
                    onDoubleClick={() => navigate(`/deals/${d.id}`)}
                    title="Double-click to open the opportunity"
                  >
                    <b>{d.title}</b>
                    <div className="deal-value">{money(d.value)}</div>
                    <div className="muted" style={{ fontSize: 11.5 }}>
                      {d.company?.name ?? (d.contact ? `${d.contact.first_name} ${d.contact.last_name}` : "—")}
                    </div>
                    <div className="deal-prob">
                      <div style={{ width: `${d.probability}%` }} />
                    </div>
                    <div className="deal-meta">
                      <span>{d.probability}% · {age}d old</span>
                      <span>{d.expected_close_date ? fmtDate(d.expected_close_date) : "no date"}</span>
                    </div>
                    <div className="deal-foot">
                      {d.owner
                        ? <Avatar first={d.owner.full_name.split(" ")[0]} last={d.owner.full_name.split(" ").slice(-1)[0]}
                            size={22} label={d.owner.full_name} />
                        : <span className="badge muted">unassigned</span>}
                      {stale && <span className="badge warn">stale</span>}
                    </div>
                    {d.lost_reason && <div className="muted" style={{ fontSize: 11 }}>✕ {d.lost_reason}</div>}
                  </div>
                );
              })}
              {items.length === 0 && <div className="muted" style={{ fontSize: 12, padding: "10px 2px" }}>Drop deals here</div>}
            </div>
          );
        })}
      </div>

      {showForm && (
        <div className="modal-backdrop" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>New Deal</h2>
            <form onSubmit={save}>
              <div className="field"><label>Title</label>
                <input required value={form.title} onChange={set("title")}
                  placeholder="e.g. Sunrise — monthly blister-pack supply" /></div>
              <div className="form-row">
                <div className="field">
                  <label>Company</label>
                  <select value={form.company_id} onChange={set("company_id")}>
                    <option value="">None</option>
                    {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Contact</label>
                  <select value={form.contact_id} onChange={set("contact_id")}>
                    <option value="">None</option>
                    {contacts.map((c) => <option key={c.id} value={c.id}>{c.first_name} {c.last_name}</option>)}
                  </select>
                </div>
              </div>
              <div className="form-row">
                <div className="field"><label>Value ({"R"})</label>
                  <input type="number" step="0.01" value={form.value} onChange={set("value")} /></div>
                <div className="field">
                  <label>Stage</label>
                  <select value={form.stage} onChange={set("stage")}>
                    {STAGES.filter((s) => s.key !== "won" && s.key !== "lost")
                      .map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                </div>
                <div className="field"><label>Expected close</label>
                  <input type="date" value={form.expected_close_date} onChange={set("expected_close_date")} /></div>
              </div>
              <div className="field"><label>Source</label>
                <input value={form.source} onChange={set("source")} placeholder="referral, tender, website…" /></div>
              <div className="field"><label>Notes</label>
                <textarea rows={3} value={form.notes} onChange={set("notes")} /></div>
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowForm(false)}>Cancel</button>
                <button type="submit">Create deal</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
