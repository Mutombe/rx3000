import { FormEvent, useEffect, useMemo, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDate, errorText  } from "../api";
import AiStreamBlock from "../components/AiStreamBlock";
import DataTable, { Column, Truncate } from "../components/DataTable";
import { applyFilters, emptyFilters, EntityLink, FilterBar, FilterState } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Company, Contact } from "../types";
import Checkbox from "../components/Checkbox";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import ClaudeIcon from "../components/ClaudeIcon";

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
  // Who in the pharmacy owns this relationship, and whether this person is also
  // somebody the dispensary knows. Both were on the endpoint from the start and
  // sent by nothing — so every contact was unowned, and the buyer at a corporate
  // account who collects her own script was two unconnected records.
  owner_id: "" as string | number,
  patient_id: null as number | null,
};

export default function Accounts() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [showCo, setShowCo] = useState(false);
  const [showCt, setShowCt] = useState(false);
  const [coForm, setCoForm] = useState<any>({ ...EMPTY_CO });
  const [staff, setStaff] = useState<any[]>([]);
  const [linkQ, setLinkQ] = useState("");
  const [linkHits, setLinkHits] = useState<any[]>([]);
  const [ctForm, setCtForm] = useState<any>({ ...EMPTY_CT });
  const [editingCo, setEditingCo] = useState<Company | null>(null);
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
        <span className="row-actions" onClick={(e) => e.stopPropagation()}>
          <IconButton action="edit" title={`Edit ${c.name}`} onClick={() => {
            setEditingCo(c); setCoForm({ ...c, company_id: undefined }); setShowCo(true);
          }} />
          <IconButton action="review" title={`AI review of ${c.name}`}
            onClick={() => aiSummary(c)} disabled={busy} />
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
    api.get<Company[]>(`/api/crm/companies?q=${encodeURIComponent(q)}`).then(setCompanies).catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
    api.get<Contact[]>(`/api/crm/contacts?q=${encodeURIComponent(q)}`).then(setContacts);
  }

  useEffect(load, [q]);
  useEffect(() => {
    api.get<any>("/api/auth/users").then((d) => setStaff(d.items ?? d ?? []))
      .catch(() => setStaff([]));
  }, []);
  useEffect(() => {
    if (linkQ.trim().length < 2) { setLinkHits([]); return; }
    api.get<any>(`/api/patients?q=${encodeURIComponent(linkQ)}&limit=6`)
      .then((d) => setLinkHits(d.items ?? d ?? [])).catch(() => setLinkHits([]));
  }, [linkQ]);

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
        ...ctForm,
        company_id: ctForm.company_id === "" ? null : Number(ctForm.company_id),
        owner_id: ctForm.owner_id === "" ? null : Number(ctForm.owner_id),
      });
      setShowCt(false); setCtForm({ ...EMPTY_CT });
      load();
    } catch (err: any) { toast.error(errorText(err)); }
  }

  /* Opens the card first and streams into it, rather than setting the text to
     the literal word "Thinking…" and replacing it twelve seconds later. That
     placeholder was indistinguishable from an answer until it changed, and on a
     slow line it sat there long enough to be read as one. */
  const [reviewing, setReviewing] = useState<Company | null>(null);
  function aiSummary(company: Company) {
    setReviewing(company);
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
          loading={loading}
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

      {reviewing && (
        <div className="card">
          <h3><ClaudeIcon size={16} /> AI account review, {reviewing.name}</h3>
          <AiStreamBlock
            key={reviewing.id}
            path={`/api/ai/account-summary/${reviewing.id}/stream`}
            label="Write the review"
            title="Account summary"
            context={reviewing.name}
            empty={`Where the relationship with ${reviewing.name} stands, the risks, and the next actions worth taking.`}
          />
          <div style={{ marginTop: 10 }}>
            <button className="secondary small" onClick={() => setReviewing(null)}>Dismiss</button>
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
                  <Select
                    value={String(coForm.account_type ?? "")}
                    onChange={(__value) => setCo("account_type")({ target: { value: __value } } as any)}
                    options={[...ACCOUNT_TYPES.map(([v, l]) => ({ value: String(v), label: l }))]}
                  />
                </div>
                <div className="field">
                  <label>Status</label>
                  <Select
                    value={String(coForm.status ?? "")}
                    onChange={(__value) => setCo("status")({ target: { value: __value } } as any)}
                    options={[{ value: "active", label: "Active" }, { value: "prospect", label: "Prospect" }, { value: "dormant", label: "Dormant" }]}
                  />
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
                  <Select
                    value={String(ctForm.company_id ?? "")}
                    onChange={(__value) => setCt("company_id")({ target: { value: __value } } as any)}
                    options={[{ value: "", label: "None" }, ...companies.map((c) => ({ value: String(c.id), label: c.name }))]}
                  />
                </div>
              </div>
              <div className="form-row">
                <div className="field"><label>Phone</label><input value={ctForm.phone} onChange={setCt("phone")} /></div>
                <div className="field"><label>Email</label><input type="email" value={ctForm.email} onChange={setCt("email")} /></div>
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Lifecycle stage</label>
                  <Select
                    value={String(ctForm.lifecycle_stage ?? "")}
                    onChange={(__value) => setCt("lifecycle_stage")({ target: { value: __value } } as any)}
                    options={[...STAGES.map(([v, l]) => ({ value: String(v), label: l }))]}
                  />
                </div>
                <div className="field"><label>Source</label>
                  <input value={ctForm.source} onChange={setCt("source")} placeholder="referral, website, event…" /></div>
              </div>
              <div className="field">
                <Checkbox
                  checked={ctForm.marketing_opt_in}
                  // The shared setter reads `e.target.type` to decide between
                  // `checked` and `value`; the synthetic event says which it is
                  // rather than relying on the fallback branch happening to be
                  // right for a boolean.
                  onChange={(v) =>
                    setCt("marketing_opt_in")({ target: { type: "checkbox", checked: v } } as any)}
                >
                  Consented to marketing communication (POPIA)
                </Checkbox>
              </div>
              {/* Who in the pharmacy owns this relationship. An unowned contact
                  is one nobody rings back. */}
              <div className="field">
                <label>Owned by</label>
                <Select
                  value={ctForm.owner_id === "" ? "" : String(ctForm.owner_id)}
                  onChange={(v) => setCtForm({ ...ctForm, owner_id: v })}
                  options={[{ value: "", label: "Nobody yet" },
                            ...staff.map((u: any) => ({
                              value: String(u.id),
                              label: u.full_name || u.username,
                              hint: u.role }))]}
                />
              </div>

              {/* The same person, on the other side of the counter. A buyer at
                  a corporate account who collects her own script was two
                  records that could not see each other. */}
              <div className="field">
                <label>Also a patient here?</label>
                {ctForm.patient_id ? (
                  <div className="product-pick">
                    <span>Linked to patient #{ctForm.patient_id}</span>
                    <button type="button" className="btn ghost small"
                            onClick={() => setCtForm({ ...ctForm, patient_id: null })}>
                      Unlink
                    </button>
                  </div>
                ) : (
                  <>
                    <input type="search" placeholder="Search the patient register…"
                           value={linkQ} onChange={(e) => setLinkQ(e.target.value)} />
                    {linkHits.map((pt: any) => (
                      <div key={pt.id} className="product-pick"
                           onClick={() => {
                             setCtForm({ ...ctForm, patient_id: pt.id });
                             setLinkQ("");
                           }}>
                        <span>{pt.last_name}, {pt.first_name}</span>
                        <span className="muted">{pt.phone}</span>
                      </div>
                    ))}
                  </>
                )}
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
