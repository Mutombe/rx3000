import { FormEvent, useEffect, useMemo, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDate, errorText  } from "../api";
import AiOutput from "../components/AiOutput";
import DataTable, { Column, Truncate } from "../components/DataTable";
import { applyFilters, emptyFilters, EntityLink, FilterBar, FilterState } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Company, Contact } from "../types";

type Tab = "companies" | "contacts";

const ACCOUNT_TYPES = [
  ["clinic", "Clinic / practice"],
  ["old_age_home", "Old-age home"],
  ["employer", "Employer / occupational health"],
  ["wholesale", "Wholesale buyer"],
  ["business", "Other business"],
];
const STAGES = [["lead", "Lead"], ["qualified", "Qualified"], ["customer", "Customer"], ["lost", "Lost"]];

const EMPTY_CO = {
  name: "", account_type: "business", phone: "", email: "", address: "",
  vat_number: "", credit_terms_days: 30, status: "active", notes: "",
};
const EMPTY_CT = {
  first_name: "", last_name: "", job_title: "", email: "", phone: "",
  company_id: "" as string | number, lifecycle_stage: "lead", source: "",
  marketing_opt_in: false, notes: "",
};

export default function Accounts() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [showCo, setShowCo] = useState(false);
  const [showCt, setShowCt] = useState(false);
  const [coForm, setCoForm] = useState<any>({ ...EMPTY_CO });
  const [ctForm, setCtForm] = useState<any>({ ...EMPTY_CT });
  const [editingCo, setEditingCo] = useState<Company | null>(null);
  const [summary, setSummary] = useState<{ name: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "companies", label: "Accounts", count: companies.length },
    { key: "contacts", label: "Contacts", count: contacts.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "companies");
  const [filters, setFilters] = useState<FilterState>(emptyFilters);
  const q = filters.q;

  const shownCompanies = useMemo(() => applyFilters(companies, { ...filters, q: "" }, {
    dims: { account_type: (c) => c.account_type, status: (c) => c.status },
  }), [companies, filters]);

  const shownContacts = useMemo(() => applyFilters(contacts, { ...filters, q: "" }, {
    dims: {
      lifecycle_stage: (c) => c.lifecycle_stage,
      marketing_opt_in: (c) => String(c.marketing_opt_in),
    },
  }), [contacts, filters]);

  const companyCols: Column<Company>[] = [
    { key: "name", header: "Account", sortable: true, value: (c) => c.name,
      render: (c) => (
        <>
          <EntityLink to={`/accounts/${c.id}`}>{c.name}</EntityLink>
          {c.notes && <div className="muted" style={{ fontSize: 11.5 }}><Truncate text={c.notes} at={60} /></div>}
        </>
      ) },
    { key: "account_type", header: "Type", sortable: true,
      render: (c) => <span className="badge muted">{c.account_type.replace(/_/g, " ")}</span> },
    { key: "phone", header: "Contact details",
      render: (c) => <>{c.phone}<div className="muted" style={{ fontSize: 11.5 }}>
        <Truncate text={c.email} at={28} /></div></> },
    { key: "credit_terms_days", header: "Terms", align: "right", sortable: true,
      render: (c) => `${c.credit_terms_days} days` },
    { key: "owner", header: "Owner", sortable: true, value: (c) => c.owner?.full_name ?? "",
      render: (c) => c.owner?.full_name ?? <span className="muted">—</span> },
    { key: "status", header: "Status", sortable: true,
      render: (c) => (
        <span className={`badge ${c.status === "active" ? "ok" : c.status === "prospect" ? "warn" : "muted"}`}>
          {c.status}
        </span>
      ) },
    { key: "actions", header: "", align: "right",
      render: (c) => (
        <span style={{ whiteSpace: "nowrap" }} onClick={(e) => e.stopPropagation()}>
          <button className="ghost small" onClick={() => {
            setEditingCo(c); setCoForm({ ...c, company_id: undefined }); setShowCo(true);
          }}>Edit</button>
          <button className="ghost small" onClick={() => aiSummary(c)} disabled={busy}>✦ Review</button>
        </span>
      ) },
  ];

  const contactCols: Column<Contact>[] = [
    { key: "name", header: "Contact", sortable: true, value: (c) => `${c.last_name} ${c.first_name}`,
      render: (c) => (
        <>
          <EntityLink to={`/contacts/${c.id}`}>{c.first_name} {c.last_name}</EntityLink>
          <div className="muted" style={{ fontSize: 11.5 }}><Truncate text={c.job_title} at={34} /></div>
        </>
      ) },
    { key: "company", header: "Account", sortable: true, value: (c) => c.company?.name ?? "",
      render: (c) => (c.company
        ? <EntityLink to={`/accounts/${c.company.id}`} muted>{c.company.name}</EntityLink>
        : <span className="muted">—</span>) },
    { key: "phone", header: "Details",
      render: (c) => <>{c.phone}<div className="muted" style={{ fontSize: 11.5 }}>
        <Truncate text={c.email} at={28} /></div></> },
    { key: "lifecycle_stage", header: "Stage", sortable: true,
      render: (c) => (
        <span className={`badge ${c.lifecycle_stage === "customer" ? "ok"
          : c.lifecycle_stage === "qualified" ? "warn"
          : c.lifecycle_stage === "lost" ? "danger" : "muted"}`}>{c.lifecycle_stage}</span>
      ) },
    { key: "source", header: "Source", sortable: true,
      render: (c) => <span className="muted">{c.source || "—"}</span> },
    { key: "marketing_opt_in", header: "Marketing",
      render: (c) => (c.marketing_opt_in
        ? <span className="badge ok">opted in</span>
        : <span className="badge muted">no consent</span>) },
    { key: "created_at", header: "Added", sortable: true,
      render: (c) => <span className="muted">{fmtDate(c.created_at)}</span> },
  ];

  function load() {
    api.get<Company[]>(`/api/crm/companies?q=${encodeURIComponent(q)}`).then(setCompanies).catch((e) => toast.error(errorText(e)));
    api.get<Contact[]>(`/api/crm/contacts?q=${encodeURIComponent(q)}`).then(setContacts);
  }

  useEffect(load, [q]);

  async function saveCompany(e: FormEvent) {
    e.preventDefault();
    try {
      const body = { ...coForm, credit_terms_days: Number(coForm.credit_terms_days) || 30 };
      if (editingCo) await api.put(`/api/crm/companies/${editingCo.id}`, body);
      else await api.post("/api/crm/companies", body);
      setShowCo(false); setEditingCo(null); setCoForm({ ...EMPTY_CO });
      load();
    } catch (err: any) { toast.error(errorText(err)); }
  }

  async function saveContact(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/crm/contacts", {
        ...ctForm, company_id: ctForm.company_id === "" ? null : Number(ctForm.company_id),
      });
      setShowCt(false); setCtForm({ ...EMPTY_CT });
      load();
    } catch (err: any) { toast.error(errorText(err)); }
  }

  async function aiSummary(company: Company) {
    setBusy(true); setSummary({ name: company.name, text: "Thinking…" });
    try {
      const res = await api.post<{ text: string }>(`/api/ai/account-summary/${company.id}`);
      setSummary({ name: company.name, text: res.text });
    } catch (e: any) {
      setSummary({ name: company.name, text: `Error: ${e.message}` });
    } finally { setBusy(false); }
  }

  const setCo = (k: string) => (e: any) => setCoForm({ ...coForm, [k]: e.target.value });
  const setCt = (k: string) => (e: any) =>
    setCtForm({ ...ctForm, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Accounts &amp; Contacts</h1>
          <div className="sub">Corporate customers, clinics and the people behind them</div>
        </div>
        {/* the primary action follows the visible tab, so there is only ever one */}
        {tab === "companies"
          ? <button onClick={() => { setEditingCo(null); setCoForm({ ...EMPTY_CO }); setShowCo(true); }}>+ New Account</button>
          : <button onClick={() => setShowCt(true)}>+ New Contact</button>}
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "companies" ? (
        <DataTable
          columns={companyCols}
          rows={shownCompanies}
          rowKey={(c) => c.id}
          rowHref={(c) => `/accounts/${c.id}`}
          empty="No accounts match these filters"
          toolbar={
            <FilterBar
              value={filters} onChange={setFilters} placeholder="Search accounts…"
              dimensions={[
                { key: "account_type", label: "Type", options: ACCOUNT_TYPES as [string, string][] },
                { key: "status", label: "Status",
                  options: [["active", "Active"], ["prospect", "Prospect"], ["inactive", "Inactive"]] },
              ]}
            />
          }
        />
      ) : (
        <DataTable
          columns={contactCols}
          rows={shownContacts}
          rowKey={(c) => c.id}
          rowHref={(c) => `/contacts/${c.id}`}
          empty="No contacts match these filters"
          toolbar={
            <FilterBar
              value={filters} onChange={setFilters} placeholder="Search contacts…"
              dimensions={[
                { key: "lifecycle_stage", label: "Stage", options: STAGES as [string, string][] },
                { key: "marketing_opt_in", label: "Consent",
                  options: [["true", "Opted in"], ["false", "No consent"]] },
              ]}
            />
          }
        />
      )}

      {summary && (
        <div className="card">
          <h3>✦ AI account review — {summary.name}</h3>
          <AiOutput text={summary.text} title="Account summary" context={summary.name} />
          <div style={{ marginTop: 10 }}>
            <button className="secondary small" onClick={() => setSummary(null)}>Dismiss</button>
          </div>
        </div>
      )}

      {showCo && (
        <div className="modal-backdrop" onClick={() => setShowCo(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editingCo ? "Edit account" : "New account"}</h2>
            <form onSubmit={saveCompany}>
              <div className="field"><label>Account name</label><input required value={coForm.name} onChange={setCo("name")} /></div>
              <div className="form-row">
                <div className="field">
                  <label>Type</label>
                  <select value={coForm.account_type} onChange={setCo("account_type")}>
                    {ACCOUNT_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Status</label>
                  <select value={coForm.status} onChange={setCo("status")}>
                    <option value="active">Active</option>
                    <option value="prospect">Prospect</option>
                    <option value="dormant">Dormant</option>
                  </select>
                </div>
                <div className="field"><label>Credit terms (days)</label>
                  <input type="number" value={coForm.credit_terms_days} onChange={setCo("credit_terms_days")} /></div>
              </div>
              <div className="form-row">
                <div className="field"><label>Phone</label><input value={coForm.phone} onChange={setCo("phone")} /></div>
                <div className="field"><label>Email</label><input type="email" value={coForm.email} onChange={setCo("email")} /></div>
                <div className="field"><label>VAT number</label><input value={coForm.vat_number} onChange={setCo("vat_number")} /></div>
              </div>
              <div className="field"><label>Address</label><input value={coForm.address} onChange={setCo("address")} /></div>
              <div className="field"><label>Notes</label><textarea rows={3} value={coForm.notes} onChange={setCo("notes")} /></div>
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowCo(false)}>Cancel</button>
                <button type="submit">Save account</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showCt && (
        <div className="modal-backdrop" onClick={() => setShowCt(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>New contact</h2>
            <form onSubmit={saveContact}>
              <div className="form-row">
                <div className="field"><label>First name</label><input required value={ctForm.first_name} onChange={setCt("first_name")} /></div>
                <div className="field"><label>Last name</label><input required value={ctForm.last_name} onChange={setCt("last_name")} /></div>
              </div>
              <div className="form-row">
                <div className="field"><label>Job title</label><input value={ctForm.job_title} onChange={setCt("job_title")} /></div>
                <div className="field">
                  <label>Account</label>
                  <select value={ctForm.company_id} onChange={setCt("company_id")}>
                    <option value="">None</option>
                    {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              </div>
              <div className="form-row">
                <div className="field"><label>Phone</label><input value={ctForm.phone} onChange={setCt("phone")} /></div>
                <div className="field"><label>Email</label><input type="email" value={ctForm.email} onChange={setCt("email")} /></div>
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Lifecycle stage</label>
                  <select value={ctForm.lifecycle_stage} onChange={setCt("lifecycle_stage")}>
                    {STAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="field"><label>Source</label>
                  <input value={ctForm.source} onChange={setCt("source")} placeholder="referral, website, event…" /></div>
              </div>
              <div className="field">
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="checkbox" checked={ctForm.marketing_opt_in} onChange={setCt("marketing_opt_in")} />
                  Consented to marketing communication (POPIA)
                </label>
              </div>
              <div className="field"><label>Notes</label><textarea rows={3} value={ctForm.notes} onChange={setCt("notes")} /></div>
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowCt(false)}>Cancel</button>
                <button type="submit">Save contact</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
