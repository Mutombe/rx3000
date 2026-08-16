import { ChangeEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import CurrencyRates from "../components/CurrencyRates";
import { Link, useSearchParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, getToken, money, errorText  } from "../api";
import { AuditEntry, AutomationRule, Backup, EmailTemplate, PriceImportResult, User } from "../types";
import Pagination, { Paged } from "../components/Pagination";

const RULE_TYPES = [
  ["lead_assignment", "Lead assignment"],
  ["lead_scoring", "Lead scoring"],
  ["ticket_assignment", "Ticket assignment"],
  ["ticket_escalation", "Ticket escalation"],
  ["deal_task", "Deal task creation"],
];

type Tab = "prices" | "currency" | "scripts" | "audit" | "switch" | "notices" | "backups" | "automation" | "templates";

const TABS: [Tab, string][] = [
  ["prices", "Price file import"], ["currency", "Currency & rates"],
  ["scripts", "Prescriber scripts"],
  ["audit", "Audit log"],
  ["switch", "Switch log"], ["notices", "Counter notices"],
  ["backups", "Backups"], ["automation", "CRM automation"],
  ["templates", "Templates"],
];

interface Submitted {
  id: number; rx_number: string; date: string; doctor: string;
  practice_number: string; patient: string; patient_id: number;
  items: { product: string; instructions: string; quantity: number }[];
}

interface Txn {
  transaction_id: string; kind: string; funder_id: number | null;
  switch_id: string | null; status: string; error_code: string | null;
  http_status: number | null; amount_claimed: number | null;
  amount_approved: number | null; switch_reference: string | null;
  duration_ms: number | null; created_at: string;
}
interface Notice {
  id: number; scope: string; target_id: number | null; severity: string;
  category: string | null; body: string; active: boolean;
  expires_on: string | null; created_at: string; created_by: string;
}

/** A switch result is either fine, refused, or broken, and the three want
 *  different reactions. Anything the switch *declined* is amber rather than red:
 *  a rejected claim is a normal outcome that needs a person, not a fault. Red is
 *  reserved for the switch failing to answer, which is the pharmacy's problem
 *  rather than the patient's.
 *
 *  Keyed on the lower-cased status because the switch sends them upper-case
 *  (APPROVED, REJECTED) — matching on the raw value dropped every badge to grey. */
const TXN_TONE: Record<string, string> = {
  approved: "ok", success: "ok", accepted: "ok", eligible: "ok",
  partial: "warn", rejected: "warn", declined: "warn", refused: "warn",
  reversed: "muted",
  error: "danger", failed: "danger", timeout: "danger",
};

export default function Admin() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find(([t]) => t === params.get("tab"))?.[0] ?? "prices") as Tab;
  const setTab = (t: Tab) => setParams(t === "prices" ? {} : { tab: t }, { replace: true });
  const [csv, setCsv] = useState("");
  const [result, setResult] = useState<PriceImportResult | null>(null);
  const [updateCost, setUpdateCost] = useState(true);
  const [updateSelling, setUpdateSelling] = useState(true);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditMeta, setAuditMeta] = useState<Paged<AuditEntry> | null>(null);
  const [auditPage, setAuditPage] = useState(1);
  const [auditSize, setAuditSize] = useState(50);
  const [txns, setTxns] = useState<Txn[]>([]);
  const [txnMeta, setTxnMeta] = useState<Paged<Txn> | null>(null);
  const [txnPage, setTxnPage] = useState(1);
  const [txnKind, setTxnKind] = useState("");
  const [notices, setNotices] = useState<Notice[]>([]);
  const [noticeMeta, setNoticeMeta] = useState<Paged<Notice> | null>(null);
  const [noticePage, setNoticePage] = useState(1);
  const [noticeActive, setNoticeActive] = useState(true);
  const [submitted, setSubmitted] = useState<Submitted[]>([]);
  const [auditUser, setAuditUser] = useState("");
  const [backups, setBackups] = useState<Backup[]>([]);
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [newRule, setNewRule] = useState<any>({
    name: "", rule_type: "lead_assignment", trigger_field: "source",
    trigger_value: "", action: "assign", action_value: "", active: true, sort_order: 100,
  });
  const [newTemplate, setNewTemplate] = useState<any>({
    name: "", category: "campaign", channel: "sms", subject: "", body: "",
  });
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (tab === "audit") loadAudit();
    if (tab === "scripts")
      api.get<Submitted[]>("/api/portal-admin/submitted")
        .then(setSubmitted).catch((e) => toast.error(errorText(e)));
    if (tab === "switch")
      api
        .get<Paged<Txn>>(
          `/api/gateway/transactions/paged?kind=${encodeURIComponent(txnKind)}&page=${txnPage}&per_page=50`,
        )
        .then((r) => { setTxns(r.items); setTxnMeta(r); if (r.page !== txnPage) setTxnPage(r.page); })
        .catch((e) => toast.error(errorText(e)));
    if (tab === "notices")
      api
        .get<Paged<Notice>>(
          `/api/counter-messages/paged?active_only=${noticeActive}&page=${noticePage}&per_page=50`,
        )
        .then((r) => { setNotices(r.items); setNoticeMeta(r); if (r.page !== noticePage) setNoticePage(r.page); })
        .catch((e) => toast.error(errorText(e)));
    if (tab === "backups") loadBackups();
    if (tab === "automation") { loadRules(); api.get<User[]>("/api/auth/users").then(setUsers).catch(() => {}); }
    if (tab === "templates") loadTemplates();
  }, [tab, auditUser, auditPage, auditSize, txnPage, txnKind, noticePage, noticeActive]);
  async function acceptScript(id: number) {
    try {
      const r = await api.post<{ rx_number: string; message: string }>(
        `/api/portal-admin/submitted/${id}/accept`);
      toast.ok(`${r.rx_number} — ${r.message}`);
      // Drop it from the queue immediately; the server has already moved it on.
      setSubmitted((all) => all.filter((s) => s.id !== id));
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  useEffect(() => setTxnPage(1), [txnKind]);
  useEffect(() => setNoticePage(1), [noticeActive]);
  // A narrowed username filter can leave you past the end of a smaller set.
  useEffect(() => setAuditPage(1), [auditUser]);

  function loadRules() {
    api.get<AutomationRule[]>("/api/crm/automation").then(setRules).catch((e) => toast.error(errorText(e)));
  }
  function loadTemplates() {
    api.get<EmailTemplate[]>("/api/crm/templates").then(setTemplates).catch((e) => toast.error(errorText(e)));
  }

  async function saveRule() {
    try {
      await api.post("/api/crm/automation", { ...newRule, sort_order: Number(newRule.sort_order) || 100 });
      setNewRule({ ...newRule, name: "", trigger_value: "", action_value: "" });
      loadRules();
    } catch (e: any) { toast.error(errorText(e)); }
  }
  async function toggleRule(rule: AutomationRule) {
    await api.put(`/api/crm/automation/${rule.id}`, { ...rule, active: !rule.active });
    loadRules();
  }
  async function deleteRule(rule: AutomationRule) {
    await api.delete(`/api/crm/automation/${rule.id}`);
    loadRules();
  }
  async function saveTemplate() {
    try {
      await api.post("/api/crm/templates", newTemplate);
      setNewTemplate({ ...newTemplate, name: "", subject: "", body: "" });
      loadTemplates();
    } catch (e: any) { toast.error(errorText(e)); }
  }
  async function runEscalations() {
    const res = await api.post<{ escalated: number }>("/api/crm/automation/run-escalations");
    toast.ok(`Escalation pass complete — ${res.escalated} ticket(s) escalated.`);
  }

  function loadAudit() {
    api
      .get<Paged<AuditEntry>>(
        `/api/admin/audit/paged?username=${encodeURIComponent(auditUser)}` +
        `&page=${auditPage}&per_page=${auditSize}`,
      )
      .then((r) => {
        setAudit(r.items);
        setAuditMeta(r);
        if (r.page !== auditPage) setAuditPage(r.page);
      })
      .catch((e) => toast.error(errorText(e)));
  }
  function loadBackups() {
    api.get<Backup[]>("/api/admin/backups").then(setBackups).catch((e) => toast.error(errorText(e)));
  }

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    file.text().then((t) => { setCsv(t); setResult(null); });
  }

  async function runImport(apply: boolean) {
    setBusy(true);
    try {
      const res = await api.post<PriceImportResult>("/api/admin/price-import", {
        csv_text: csv, apply, update_cost: updateCost, update_selling: updateSelling,
      });
      setResult(res);
      if (apply) toast.ok(`Applied ${res.updated} price change(s) across ${res.matched} matched product(s).`);
    } catch (e: any) { toast.error(errorText(e)); } finally { setBusy(false); }
  }

  /** Re-open a backup and see whether it still reads.
   *
   *  A file that verified when it was written can still rot on a failing disk,
   *  and the point of asking is to find that out before the restore rather than
   *  during it.
   */
  async function recheck(filename: string) {
    try {
      const b = await api.post<Backup>(`/api/admin/backups/${filename}/verify`);
      setBackups((rows) => rows.map((r) => (r.filename === filename ? b : r)));
      if (b.verified) toast.ok(`${filename} opened cleanly and can be restored.`);
      else toast.error(b.problem || `${filename} could not be verified.`);
    } catch (e: any) {
      toast.error(errorText(e, "That backup could not be checked."));
    }
  }

  async function makeBackup() {
    setBusy(true);
    try {
      const b = await api.post<Backup>("/api/admin/backup");
      toast.ok(`Backup created: ${b.filename}`);
      loadBackups();
    } catch (e: any) { toast.error(errorText(e)); } finally { setBusy(false); }
  }

  async function download(filename: string) {
    const res = await fetch(`/api/admin/backups/${filename}/download`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) { toast.error("Download failed"); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Control Panel</h1>
          <div className="sub">
            Supplier price files, user activity audit, database backups, CRM automation rules and message templates
          </div>
        </div>
      </div>

      <div className="pill-tabs">
        {TABS.map(([t, label]) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{label}</button>
        ))}
      </div>

      {tab === "automation" && (
        <>
          <div className="card">
            <h3>Automation rules</h3>
            <p className="muted">
              Rules run automatically when a lead or ticket is created, or when a deal changes stage.
              They are evaluated in order — the first match wins for assignment; scoring rules all apply.
            </p>
            <div className="toolbar" style={{ marginTop: 12 }}>
              <button className="secondary" onClick={runEscalations}>Run SLA escalation pass now</button>
              <span className="muted">Also runs automatically with the reminder jobs</span>
            </div>
            <table>
              <thead><tr><th>Rule</th><th>Type</th><th>When</th><th>Then</th><th className="num">Fired</th><th>Active</th><th></th></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td><b>{r.name}</b><div className="muted">order {r.sort_order}</div></td>
                    <td><span className="badge muted">{r.rule_type.replace(/_/g, " ")}</span></td>
                    <td className="muted">
                      {r.trigger_field ? `${r.trigger_field} = ${r.trigger_value || "any"}` : "any record"}
                    </td>
                    <td className="muted">
                      {r.action} → {users.find((u) => String(u.id) === r.action_value)?.full_name ?? r.action_value}
                    </td>
                    <td className="num">{r.times_fired}</td>
                    <td>
                      <button className={`small ${r.active ? "" : "secondary"}`} onClick={() => toggleRule(r)}>
                        {r.active ? "on" : "off"}
                      </button>
                    </td>
                    <td className="right"><button className="ghost small" onClick={() => deleteRule(r)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rules.length === 0 && <div className="empty">No automation rules yet</div>}
          </div>

          <div className="card">
            <h3>New rule</h3>
            <div className="form-row">
              <div className="field"><label>Name</label>
                <input value={newRule.name} onChange={(e) => setNewRule({ ...newRule, name: e.target.value })} /></div>
              <div className="field">
                <label>Type</label>
                <select value={newRule.rule_type} onChange={(e) => setNewRule({ ...newRule, rule_type: e.target.value })}>
                  {RULE_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
            </div>
            <div className="form-row">
              <div className="field"><label>When field</label>
                <input value={newRule.trigger_field} placeholder="source, category, priority, stage"
                  onChange={(e) => setNewRule({ ...newRule, trigger_field: e.target.value })} /></div>
              <div className="field"><label>Equals (blank = any)</label>
                <input value={newRule.trigger_value}
                  onChange={(e) => setNewRule({ ...newRule, trigger_value: e.target.value })} /></div>
              <div className="field"><label>Then value</label>
                {newRule.rule_type.includes("assignment") ? (
                  <select value={newRule.action_value} onChange={(e) => setNewRule({ ...newRule, action_value: e.target.value })}>
                    <option value="">Choose user…</option>
                    {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
                  </select>
                ) : (
                  <input value={newRule.action_value} placeholder="score delta / priority / task subject"
                    onChange={(e) => setNewRule({ ...newRule, action_value: e.target.value })} />
                )}
              </div>
              <div className="field" style={{ maxWidth: 110 }}><label>Order</label>
                <input type="number" value={newRule.sort_order}
                  onChange={(e) => setNewRule({ ...newRule, sort_order: e.target.value })} /></div>
            </div>
            <button onClick={saveRule} disabled={!newRule.name || !newRule.action_value}>Create rule</button>
          </div>
        </>
      )}

      {tab === "templates" && (
        <>
          <div className="card">
            <h3>Message templates</h3>
            <table>
              <thead><tr><th>Name</th><th>Category</th><th>Channel</th><th>Content</th></tr></thead>
              <tbody>
                {templates.map((t) => (
                  <tr key={t.id}>
                    <td><b>{t.name}</b></td>
                    <td><span className="badge muted">{t.category}</span></td>
                    <td>{t.channel.toUpperCase()}</td>
                    <td style={{ maxWidth: 480 }}>
                      {t.subject && <b>{t.subject}<br /></b>}
                      <span className="muted">{t.body}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {templates.length === 0 && <div className="empty">No templates yet</div>}
          </div>

          <div className="card">
            <h3>New template</h3>
            <div className="form-row">
              <div className="field"><label>Name</label>
                <input value={newTemplate.name} onChange={(e) => setNewTemplate({ ...newTemplate, name: e.target.value })} /></div>
              <div className="field">
                <label>Category</label>
                <select value={newTemplate.category} onChange={(e) => setNewTemplate({ ...newTemplate, category: e.target.value })}>
                  <option value="campaign">Campaign</option><option value="ticket">Ticket reply</option>
                  <option value="deal">Deal / proposal</option><option value="general">General</option>
                </select>
              </div>
              <div className="field">
                <label>Channel</label>
                <select value={newTemplate.channel} onChange={(e) => setNewTemplate({ ...newTemplate, channel: e.target.value })}>
                  <option value="sms">SMS</option><option value="email">Email</option>
                </select>
              </div>
            </div>
            {newTemplate.channel === "email" && (
              <div className="field"><label>Subject</label>
                <input value={newTemplate.subject} onChange={(e) => setNewTemplate({ ...newTemplate, subject: e.target.value })} /></div>
            )}
            <div className="field">
              <label>Body — merge fields <span className="mono">{"{first_name} {points} {pharmacy}"}</span></label>
              <textarea rows={4} value={newTemplate.body}
                onChange={(e) => setNewTemplate({ ...newTemplate, body: e.target.value })} />
            </div>
            <button onClick={saveTemplate} disabled={!newTemplate.name || !newTemplate.body}>Save template</button>
          </div>
        </>
      )}

      {tab === "currency" && <CurrencyRates />}

      {tab === "prices" && (
        <>
          <div className="card">
            <h3>Import supplier price file</h3>
            <p className="muted">
              Upload or paste a CSV. Products are matched on NAPPI code, then barcode, then name.
              Recognised columns: <span className="mono">nappi</span>, <span className="mono">barcode</span>,{" "}
              <span className="mono">name/description</span>, <span className="mono">cost/trade_price</span>,{" "}
              <span className="mono">price/selling_price/sep</span>.
            </p>
            <div className="toolbar" style={{ marginTop: 14 }}>
              <input type="file" accept=".csv,text/csv" onChange={onFile} style={{ maxWidth: 300 }} />
              <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
                <input type="checkbox" checked={updateCost} onChange={(e) => setUpdateCost(e.target.checked)} />
                Update cost prices
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
                <input type="checkbox" checked={updateSelling} onChange={(e) => setUpdateSelling(e.target.checked)} />
                Update selling prices
              </label>
            </div>
            <div className="field">
              <label>CSV content</label>
              <textarea rows={6} value={csv} onChange={(e) => { setCsv(e.target.value); setResult(null); }}
                placeholder="nappi,description,cost,selling_price&#10;701985,Paracetamol 500mg,15.20,26.95" />
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <button className="secondary" onClick={() => runImport(false)} disabled={busy || !csv.trim()}>
                {busy ? "Working…" : "Preview changes"}
              </button>
              <button onClick={() => runImport(true)} disabled={busy || !csv.trim() || !result}>
                Apply {result ? `${result.updated} change(s)` : ""}
              </button>
            </div>
          </div>

          {result && (
            <div className="card">
              <h3>{result.applied ? "Applied" : "Preview"} — {result.matched} matched, {result.unmatched} unmatched</h3>
              <table>
                <thead>
                  <tr><th>Row</th><th>Key</th><th>Product</th><th className="num">Cost</th><th className="num">Selling</th><th>Result</th></tr>
                </thead>
                <tbody>
                  {result.lines.map((l) => (
                    <tr key={l.row}>
                      <td>{l.row}</td>
                      <td className="mono">{l.key}</td>
                      <td>{l.product_name || <span className="muted">—</span>}</td>
                      <td className="num">
                        {l.new_cost !== null
                          ? <><span className="muted">{money(l.old_cost)}</span> → <b>{money(l.new_cost)}</b></>
                          : <span className="muted">{l.old_cost !== null ? money(l.old_cost) : "—"}</span>}
                      </td>
                      <td className="num">
                        {l.new_price !== null
                          ? <><span className="muted">{money(l.old_price)}</span> → <b>{money(l.new_price)}</b></>
                          : <span className="muted">{l.old_price !== null ? money(l.old_price) : "—"}</span>}
                      </td>
                      <td>
                        <span className={`badge ${l.message === "Updated" ? "ok" : l.matched ? "muted" : "danger"}`}>
                          {l.message}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "scripts" && (
        <div className="card">
          <p className="muted small">
            Prescriptions sent in by doctors through the prescriber portal. Nothing
            here can be dispensed until a pharmacist accepts it — the prescriber
            cannot see your stock, the funder rules, or the patient at the counter.
          </p>
          <table>
            <thead>
              <tr>
                <th>Sent</th><th>Prescriber</th><th>Patient</th>
                <th>Medicines</th><th />
              </tr>
            </thead>
            <tbody>
              {submitted.map((r) => (
                <tr key={r.id}>
                  <td>
                    {fmtDate(r.date)}
                    <div className="muted small mono">{r.rx_number}</div>
                  </td>
                  <td>
                    {r.doctor}
                    <div className="muted small">{r.practice_number}</div>
                  </td>
                  <td>
                    <Link to={`/patients/${r.patient_id}`}>{r.patient}</Link>
                  </td>
                  <td>
                    {r.items.map((i, n) => (
                      <div key={n}>
                        <b>{i.product}</b> — {i.instructions}{" "}
                        <span className="muted">×{i.quantity}</span>
                      </div>
                    ))}
                  </td>
                  <td className="right">
                    <button className="btn primary small" onClick={() => acceptScript(r.id)}>
                      Accept
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {submitted.length === 0 && (
            <div className="empty">No prescriber has sent a script in</div>
          )}
        </div>
      )}

      {tab === "switch" && (
        <div className="card">
          <div className="toolbar">
            <select value={txnKind} onChange={(e) => setTxnKind(e.target.value)}>
              <option value="">All kinds</option>
              <option value="claim">Claim</option>
              <option value="eligibility">Eligibility</option>
              <option value="authorisation">Authorisation</option>
              <option value="reversal">Reversal</option>
            </select>
          </div>
          <p className="muted small">
            Every request this pharmacy sent to a switch, and what came back. When a
            claim is queried weeks later this is the evidence that settled it.
          </p>
          <table>
            <thead>
              <tr>
                <th>When</th><th>Transaction</th><th>Kind</th><th>Status</th>
                <th className="num">Claimed</th><th className="num">Approved</th>
                <th className="num">Took</th>
              </tr>
            </thead>
            <tbody>
              {txns.map((t) => (
                <tr key={t.transaction_id}>
                  <td>{fmtDateTime(t.created_at)}</td>
                  <td className="mono">
                    {t.transaction_id}
                    {t.switch_reference && (
                      <div className="muted small">ref {t.switch_reference}</div>
                    )}
                  </td>
                  <td>{t.kind}</td>
                  <td>
                    <span className={`badge ${TXN_TONE[t.status?.toLowerCase()] ?? "muted"}`}>
                      {t.status}
                    </span>
                    {t.error_code && <div className="muted small">{t.error_code}</div>}
                  </td>
                  <td className="num">{t.amount_claimed != null ? money(t.amount_claimed) : "—"}</td>
                  <td className="num">{t.amount_approved != null ? money(t.amount_approved) : "—"}</td>
                  <td className="num">{t.duration_ms != null ? `${t.duration_ms} ms` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {txns.length === 0 && <div className="empty">Nothing has been sent to a switch yet</div>}
          {txnMeta && (
            <Pagination meta={txnMeta} noun="transactions" onPage={setTxnPage} />
          )}
        </div>
      )}

      {tab === "notices" && (
        <div className="card">
          <div className="toolbar">
            <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
              <input type="checkbox" style={{ width: "auto" }} checked={noticeActive}
                onChange={(e) => setNoticeActive(e.target.checked)} />
              Active only
            </label>
          </div>
          <p className="muted small">
            Notices raised at the counter — the warnings a dispenser sees against a
            patient, a product or a funder. Expired ones are kept, because why a
            warning was shown last month is a question that gets asked.
          </p>
          <table>
            <thead>
              <tr>
                <th>Raised</th><th>Scope</th><th>Severity</th>
                <th>Message</th><th>Expires</th><th>By</th>
              </tr>
            </thead>
            <tbody>
              {notices.map((n) => (
                <tr key={n.id}>
                  <td>{fmtDateTime(n.created_at)}</td>
                  <td>
                    {n.scope}
                    {n.target_id ? <div className="muted small">#{n.target_id}</div> : null}
                  </td>
                  <td>
                    <span className={`badge ${n.severity === "block" ? "danger"
                      : n.severity === "warn" ? "warn" : "muted"}`}>
                      {n.severity}
                    </span>
                  </td>
                  <td>{n.body}</td>
                  <td>{n.expires_on ? fmtDate(n.expires_on) : "—"}</td>
                  <td>{n.created_by || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {notices.length === 0 && <div className="empty">No counter notices</div>}
          {noticeMeta && (
            <Pagination meta={noticeMeta} noun="notices" onPage={setNoticePage} />
          )}
        </div>
      )}

      {tab === "audit" && (
        <div className="card">
          <div className="toolbar">
            <input type="search" placeholder="Filter by username…" value={auditUser}
              onChange={(e) => setAuditUser(e.target.value)} />
          </div>
          <table>
            <thead><tr><th>When</th><th>User</th><th>Action</th><th>Endpoint</th><th>Status</th><th>IP</th></tr></thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id}>
                  <td>{fmtDateTime(a.created_at)}</td>
                  <td><b>{a.username || "—"}</b></td>
                  <td>{a.summary}</td>
                  <td className="mono muted">{a.action} {a.path}</td>
                  <td>
                    <span className={`badge ${a.status_code < 300 ? "ok" : a.status_code < 500 ? "warn" : "danger"}`}>
                      {a.status_code}
                    </span>
                  </td>
                  <td className="mono muted">{a.ip_address}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {audit.length === 0 && <div className="empty">No activity recorded</div>}
          {auditMeta && (
            <Pagination
              meta={auditMeta}
              noun="audit entries"
              onPage={setAuditPage}
              onPerPage={(n) => { setAuditSize(n); setAuditPage(1); }}
            />
          )}
        </div>
      )}

      {tab === "backups" && (
        <div className="card">
          {/* The only question anyone actually has about backups is not "is it
              configured" but "when did one last actually work". A list of files
              cannot answer that, which is precisely why the system we are
              replacing shows a failed 0.00 MByte archive indistinguishable from
              its good ones. So the answer is stated first, in a sentence. */}
          {(() => {
            const good = backups.find((b) => b.verified);
            const failing = backups.filter((b) => !b.verified).length;
            if (!backups.length) return null;
            return (
              <p className={`st-note ${good ? "is-ok" : "is-bad"}`}>
                {good
                  ? `Last backup proven restorable: ${fmtDateTime(good.created_at)}.`
                  : "No backup here has been proven restorable. Take one now and check the result."}
                {failing > 0 && ` ${failing} of ${backups.length} could not be verified.`}
              </p>
            );
          })()}

          <div className="toolbar">
            <button onClick={makeBackup} disabled={busy}>{busy ? "Backing up…" : "Back up now"}</button>
            <span className="muted">
              Runs nightly at 23:30 · 20 kept, verified ones first
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <th>File</th><th>Created</th><th className="num">Size</th>
                <th>Restorable</th><th></th>
              </tr>
            </thead>
            <tbody>
              {backups.map((b) => (
                <tr key={b.filename}>
                  <td className="mono">{b.filename}</td>
                  <td>{fmtDateTime(b.created_at)}</td>
                  <td className="num">{(b.size_bytes / 1024).toFixed(0)} KB</td>
                  <td>
                    {b.verified ? (
                      <span className="badge ok">verified</span>
                    ) : (
                      // The reason travels with the verdict. "Failed" on its own
                      // tells an owner they have a problem and nothing about
                      // which problem.
                      <span className="badge danger" title={b.problem}>
                        {b.problem ? b.problem.split(".")[0] : "not checked"}
                      </span>
                    )}
                  </td>
                  <td className="right">
                    <button className="small ghost" onClick={() => recheck(b.filename)}>
                      Check
                    </button>
                    <button className="small secondary" onClick={() => download(b.filename)}>
                      Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {backups.length === 0 && <div className="empty">No backups yet — create one now or wait for tonight's run.</div>}
        </div>
      )}
    </>
  );
}
