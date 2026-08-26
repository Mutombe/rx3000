import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, fmtDate, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import { Avatar, Highlights } from "../components/record";
import { Contact, Deal } from "../types";
import { ArrowLeft } from "@phosphor-icons/react";

export default function ContactDetail() {
  const { id } = useParams();
  const [contact, setContact] = useState<Contact | null>(null);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Contact>(`/api/crm/contacts/${id}`).then(setContact).catch((e) => setError(e.message));
    api.get<Deal[]>("/api/crm/deals").then((all) => setDeals(all.filter((d) => d.contact_id === Number(id))));
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
  if (!contact) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Accounts", to: "/accounts" }, { label: "This record" }]}
        eyebrow="Contact"
        cards={1}
        avatar
        table={5}
      />;

  const cols: Column<Deal>[] = [
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

  const open = deals.filter((d) => !["won", "lost"].includes(d.stage));

  return (
    <>
      <Breadcrumbs trail={[{ label: "Dashboard", to: "/" }, { label: "Accounts", to: "/accounts" }, { label: "This record" }]} />
      <div className="page-head">
        <div className="record-title">
          <Avatar first={contact.first_name} last={contact.last_name} size={44} />
          <div>
            <div className="eyebrow">Contact</div>
            <h1>{contact.first_name} {contact.last_name}</h1>
            <div className="sub">
              {contact.job_title || "—"}
              {contact.company && <> · <EntityLink to={`/accounts/${contact.company.id}`}>{contact.company.name}</EntityLink></>}
            </div>
          </div>
        </div>
        <Link to="/accounts?tab=contacts" className="btn secondary"><ArrowLeft size={13} weight="bold" /> Contacts</Link>
      </div>

      <div className="card record-hero">
        <Highlights items={[
          { label: "Lifecycle stage", value: contact.lifecycle_stage, hint: contact.source || "no source recorded" },
          { label: "Open pipeline", value: money(open.reduce((s, d) => s + d.value, 0)),
            hint: `${open.length} open opportunit(ies)` },
          { label: "Marketing consent",
            value: contact.marketing_opt_in ? "Granted" : "Not granted",
            hint: "POPIA" },
          { label: "Added", value: fmtDate(contact.created_at), hint: "on record since" },
        ]} />
        <dl className="detail-fields" style={{ marginTop: 14 }}>
          <div><dt>Phone</dt><dd>{contact.phone || "—"}</dd></div>
          <div><dt>Email</dt><dd>{contact.email || "—"}</dd></div>
          <div><dt>Account</dt>
            <dd>{contact.company
              ? <EntityLink to={`/accounts/${contact.company.id}`}>{contact.company.name}</EntityLink>
              : "—"}</dd></div>
        </dl>
        {contact.notes && <p className="muted" style={{ marginTop: 12, fontSize: 12.5 }}>{contact.notes}</p>}
      </div>

      <DataTable
        columns={cols}
        rows={deals}
        rowKey={(d) => d.id}
        rowHref={(d) => `/deals/${d.id}`}
        totals
        initialSort={{ key: "value", dir: "desc" }}
        empty="No opportunities linked to this contact"
      />
    </>
  );
}
