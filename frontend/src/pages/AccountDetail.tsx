import { useEffect, useState } from "react";
import { Figure } from "../components/Skeleton";
import RecordPage from "../components/RecordPage";
import { Link, useParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Highlights } from "../components/record";
import { CompanyOverview } from "../types";
import { ArrowLeft } from "@phosphor-icons/react";

type Tab = "contacts" | "deals" | "cases";
type Row<K extends keyof CompanyOverview> = CompanyOverview[K] extends (infer R)[] ? R : never;

export default function AccountDetail() {
  const { id } = useParams();
  const [data, setData] = useState<CompanyOverview | null>(null);
  const [error, setError] = useState("");

  const TABS: TabDef<Tab>[] = [
    { key: "contacts", label: "Contacts", count: data?.contacts.length ?? null },
    { key: "deals", label: "Opportunities", count: data?.deals.length ?? null },
    { key: "cases", label: "Cases", count: data?.tickets.length ?? null },
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
  /* A `DetailSkeleton` used to take the whole account away while its overview
   * loaded, including the three tab names, the Type and Owner labels, the five
   * figure labels, the Phone, Email and Address terms and the column heads of
   * all three tables. None of that is an answer about this account: it is the
   * shape every account page has. Drawn at once now, with the values alone
   * waiting. */
  const c = data?.company;

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
    <RecordPage
      loading={!data}
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Accounts", to: "/accounts" },
              { label: c ? c.name : "Opening the account" }]}
      eyebrow="Account"
      title={c ? c.name : null}
      meta={[
        { label: "Type", value: c ? c.account_type.replace(/_/g, " ") : "" },
        { label: "Owner",
          value: !c ? "" : c.owner ?? <span className="muted">Unassigned</span> },
      ]}
    >

      <div className="card record-hero">
        {/* Five labels written here in the source, so they are on the screen
            before the request is answered and only the money waits. */}
        <Highlights items={!data || !c ? [
          { label: "Open pipeline", value: <Figure ready={false} w="9ch">{null}</Figure> },
          { label: "Won revenue", value: <Figure ready={false} w="9ch">{null}</Figure> },
          { label: "Open cases", value: <Figure ready={false} w="3ch">{null}</Figure> },
          { label: "Contacts", value: <Figure ready={false} w="3ch">{null}</Figure> },
          { label: "Credit terms", value: <Figure ready={false} w="7ch">{null}</Figure> },
        ] : [
          { label: "Open pipeline", value: money(data.totals.open_pipeline), hint: `${data.deals.length} opportunit(ies)` },
          { label: "Won revenue", value: money(data.totals.won_value), hint: "closed won to date" },
          { label: "Open cases", value: String(data.totals.open_tickets), hint: `${data.tickets.length} raised in total` },
          { label: "Contacts", value: String(data.totals.contacts), hint: "people on this account" },
          { label: "Credit terms", value: `${c.credit_terms_days} days`,
            hint: <span className={`badge ${c.status === "active" ? "ok" : "muted"}`}>{c.status}</span> },
        ]} />
        <dl className="detail-fields" style={{ marginTop: 14 }}>
          <div><dt>Phone</dt><dd><Figure ready={!!c} w="14ch">{c && (c.phone || "none")}</Figure></dd></div>
          <div><dt>Email</dt><dd><Figure ready={!!c} w="20ch">{c && (c.email || "none")}</Figure></dd></div>
          <div><dt>Address</dt><dd><Figure ready={!!c} w="28ch">{c && (c.address || "none")}</Figure></dd></div>
        </dl>
        {c?.notes && <p className="muted" style={{ marginTop: 12, fontSize: 12.5 }}>{c.notes}</p>}
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {/* `loading` holds each empty state back until the overview has actually
          come in. Telling a salesperson their biggest account has no
          opportunities on it, because a request is still in flight, is the one
          sentence this screen must never say by accident. */}
      {tab === "contacts" && (
        <DataTable columns={contactCols} loading={!data} rows={data?.contacts ?? []} rowKey={(r) => r.id}
          rowHref={(r) => `/contacts/${r.id}`} empty="No contacts on this account yet" />
      )}
      {tab === "deals" && (
        <DataTable columns={dealCols} loading={!data} rows={data?.deals ?? []} rowKey={(d) => d.id} totals
          rowHref={(d) => `/deals/${d.id}`} initialSort={{ key: "value", dir: "desc" }}
          empty="No opportunities raised against this account" />
      )}
      {tab === "cases" && (
        <DataTable columns={caseCols} loading={!data} rows={data?.tickets ?? []} rowKey={(t) => t.id}
          rowHref={(t) => `/cases/${t.id}`} initialSort={{ key: "created_at", dir: "desc" }}
          empty="No cases logged for this account" />
      )}
    </RecordPage>
  );
}
