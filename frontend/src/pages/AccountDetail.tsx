import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Avatar, Highlights } from "../components/record";
import { CompanyOverview } from "../types";
import { ArrowLeft } from "@phosphor-icons/react";

type Tab = "contacts" | "deals" | "cases";
type Row<K extends keyof CompanyOverview> = CompanyOverview[K] extends (infer R)[] ? R : never;

export default function AccountDetail() {
  const { id } = useParams();
  const [data, setData] = useState<CompanyOverview | null>(null);
  const [error, setError] = useState("");

  const TABS: TabDef<Tab>[] = [
    { key: "contacts", label: "Contacts", count: data?.contacts.length },
    { key: "deals", label: "Opportunities", count: data?.deals.length },
    { key: "cases", label: "Cases", count: data?.tickets.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "contacts");

  useEffect(() => {
    api.get<CompanyOverview>(`/api/crm/companies/${id}/overview`).then(setData).catch((e) => setError(e.message));
  }, [id]);

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
  if (!data) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Accounts", to: "/accounts" }, { label: "This record" }]}
        eyebrow="Account"
        tabs={["Contacts", "Opportunities", "Cases"]}
        cards={1}
      />;
  const c = data.company;

  const contactCols: Column<Row<"contacts">>[] = [
    { key: "name", header: "Contact", sortable: true,
      render: (r) => <EntityLink to={`/contacts/${r.id}`}>{r.name}</EntityLink> },
    { key: "job_title", header: "Role", truncate: 30 },
    { key: "phone", header: "Phone" },
    { key: "email", header: "Email", truncate: 30 },
    { key: "lifecycle_stage", header: "Stage", sortable: true,
      render: (r) => <span className={`badge ${r.lifecycle_stage === "customer" ? "ok" : "muted"}`}>{r.lifecycle_stage}</span> },
  ];

  const dealCols: Column<Row<"deals">>[] = [
    { key: "title", header: "Opportunity", sortable: true, truncate: 46,
      render: (d) => <EntityLink to={`/deals/${d.id}`}>{d.title}</EntityLink> },
    { key: "stage", header: "Stage", sortable: true,
      render: (d) => <span className={`badge ${d.stage === "won" ? "ok" : d.stage === "lost" ? "danger" : "muted"}`}>{d.stage}</span> },
    { key: "probability", header: "Probability", align: "right", sortable: true, render: (d) => `${d.probability}%` },
    { key: "expected_close_date", header: "Expected close", sortable: true,
      render: (d) => <span className="muted">{fmtDate(d.expected_close_date)}</span> },
    { key: "value", header: "Value", align: "right", sortable: true,
      render: (d) => <b>{money(d.value)}</b>, total: (d) => d.value, totalRender: (n) => money(n) },
  ];

  const caseCols: Column<Row<"tickets">>[] = [
    { key: "ticket_number", header: "Case", sortable: true,
      render: (t) => <EntityLink to={`/cases/${t.id}`}><span className="mono">{t.ticket_number}</span></EntityLink> },
    { key: "subject", header: "Subject", truncate: 50 },
    { key: "priority", header: "Priority", sortable: true,
      render: (t) => <span className={`badge ${t.priority === "urgent" ? "danger" : t.priority === "high" ? "warn" : "muted"}`}>{t.priority}</span> },
    { key: "status", header: "Status", sortable: true,
      render: (t) => <span className={`badge ${t.status === "resolved" || t.status === "closed" ? "ok" : "warn"}`}>{t.status}</span> },
    { key: "created_at", header: "Raised", sortable: true, render: (t) => <span className="muted">{fmtDateTime(t.created_at)}</span> },
  ];

  return (
    <>
      <Breadcrumbs trail={[{ label: "Dashboard", to: "/" }, { label: "Accounts", to: "/accounts" }, { label: "This record" }]} />
      <div className="page-head">
        <div className="record-title">
          <Avatar first={c.name} last="" size={44} />
          <div>
            <div className="eyebrow">Account</div>
            <h1>{c.name}</h1>
            <div className="sub">
              {c.account_type.replace(/_/g, " ")} · owner {c.owner ?? "unassigned"}
            </div>
          </div>
        </div>
        <Link to="/accounts" className="btn secondary"><ArrowLeft size={13} weight="bold" /> Accounts</Link>
      </div>

      <div className="card record-hero">
        <Highlights items={[
          { label: "Open pipeline", value: money(data.totals.open_pipeline), hint: `${data.deals.length} opportunit(ies)` },
          { label: "Won revenue", value: money(data.totals.won_value), hint: "closed won to date" },
          { label: "Open cases", value: String(data.totals.open_tickets), hint: `${data.tickets.length} raised in total` },
          { label: "Contacts", value: String(data.totals.contacts), hint: "people on this account" },
          { label: "Credit terms", value: `${c.credit_terms_days} days`,
            hint: <span className={`badge ${c.status === "active" ? "ok" : "muted"}`}>{c.status}</span> },
        ]} />
        <dl className="detail-fields" style={{ marginTop: 14 }}>
          <div><dt>Phone</dt><dd>{c.phone || "—"}</dd></div>
          <div><dt>Email</dt><dd>{c.email || "—"}</dd></div>
          <div><dt>Address</dt><dd>{c.address || "—"}</dd></div>
        </dl>
        {c.notes && <p className="muted" style={{ marginTop: 12, fontSize: 12.5 }}>{c.notes}</p>}
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "contacts" && (
        <DataTable columns={contactCols} rows={data.contacts} rowKey={(r) => r.id}
          rowHref={(r) => `/contacts/${r.id}`} empty="No contacts on this account yet" />
      )}
      {tab === "deals" && (
        <DataTable columns={dealCols} rows={data.deals} rowKey={(d) => d.id} totals
          rowHref={(d) => `/deals/${d.id}`} initialSort={{ key: "value", dir: "desc" }}
          empty="No opportunities raised against this account" />
      )}
      {tab === "cases" && (
        <DataTable columns={caseCols} rows={data.tickets} rowKey={(t) => t.id}
          rowHref={(t) => `/cases/${t.id}`} initialSort={{ key: "created_at", dir: "desc" }}
          empty="No cases logged for this account" />
      )}
    </>
  );
}
