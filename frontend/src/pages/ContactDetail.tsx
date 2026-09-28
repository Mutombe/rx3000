import { useEffect, useState } from "react";
import { Figure } from "../components/Skeleton";
import RecordPage from "../components/RecordPage";
import { Link, useParams } from "react-router-dom";
import { api, errorText, fmtDate, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import { Highlights } from "../components/record";
import { Contact, Deal } from "../types";
import { ArrowLeft } from "@phosphor-icons/react";

export default function ContactDetail() {
  const { id } = useParams();
  const [contact, setContact] = useState<Contact | null>(null);
  /* Nothing rather than an empty list to start with, so the table below can
     tell "we have not been told" apart from "there are none". */
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [dealsUnknown, setDealsUnknown] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Contact>(`/api/crm/contacts/${id}`).then(setContact)
      .catch((e) => setError(errorText(e, "This contact could not be read.")));
    api.get<Deal[]>("/api/crm/deals")
      .then((all) => { setDeals(all.filter((d) => d.contact_id === Number(id))); setDealsUnknown(false); })
      // Unhandled before this, so an empty opportunities table read as "we have
      // never quoted them" on the record of somebody being chased for business.
      .catch(() => { setDeals([]); setDealsUnknown(true); });
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
  /* A `DetailSkeleton` used to hold this page back entirely: the trail, the
   * word Contact, the Job title and Account labels, the four figure labels,
   * the Phone, Email and Account terms and the five column heads of the
   * opportunities table. All of it is written below and none of it comes from
   * the server, so the frame is drawn at once and only the values wait. */

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

  const open = (deals ?? []).filter((d) => !["won", "lost"].includes(d.stage));

  return (
    <RecordPage
      loading={!contact}
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Accounts", to: "/accounts" },
              { label: contact
                  ? `${contact.first_name} ${contact.last_name}`
                  : "Opening the record" }]}
      eyebrow="Contact"
      title={contact ? `${contact.first_name} ${contact.last_name}` : null}
      meta={[
        { label: "Job title",
          value: !contact ? ""
            : contact.job_title || <span className="muted">Not recorded</span> },
        { label: "Account",
          value: !contact ? ""
            : contact.company
            ? <EntityLink to={`/accounts/${contact.company.id}`}>
                {contact.company.name}
              </EntityLink>
            : <span className="muted">None</span> },
      ]}
    >

      <div className="card record-hero">
        {/* The pipeline figure comes from a second request and the rest from
            the contact, so each tile waits on its own answer rather than all
            four waiting on the slower of the two. */}
        <Highlights items={[
          { label: "Lifecycle stage",
            value: <Figure ready={!!contact} w="12ch">{contact?.lifecycle_stage}</Figure>,
            hint: contact ? contact.source || "No source recorded" : undefined },
          { label: "Open pipeline",
            value: <Figure ready={!!deals} w="9ch">
              {deals && money(open.reduce((s, d) => s + d.value, 0))}</Figure>,
            hint: deals ? `${open.length} open opportunit(ies)` : undefined },
          { label: "Marketing consent",
            value: <Figure ready={!!contact} w="11ch">
              {contact && (contact.marketing_opt_in ? "Granted" : "Not granted")}</Figure>,
            hint: "POPIA" },
          { label: "Added",
            value: <Figure ready={!!contact} w="11ch">
              {contact && fmtDate(contact.created_at)}</Figure>,
            hint: "on record since" },
        ]} />
        <dl className="detail-fields" style={{ marginTop: 14 }}>
          <div><dt>Phone</dt><dd><Figure ready={!!contact} w="14ch">
            {contact && (contact.phone || "none")}</Figure></dd></div>
          <div><dt>Email</dt><dd><Figure ready={!!contact} w="20ch">
            {contact && (contact.email || "none")}</Figure></dd></div>
          <div><dt>Account</dt>
            <dd><Figure ready={!!contact} w="18ch">{contact && (contact.company
              ? <EntityLink to={`/accounts/${contact.company.id}`}>{contact.company.name}</EntityLink>
              : "none")}</Figure></dd></div>
        </dl>
        {contact?.notes && <p className="muted" style={{ marginTop: 12, fontSize: 12.5 }}>{contact.notes}</p>}
      </div>

      <DataTable
        columns={cols}
        loading={!deals}
        rows={deals ?? []}
        rowKey={(d) => d.id}
        rowHref={(d) => `/deals/${d.id}`}
        totals
        initialSort={{ key: "value", dir: "desc" }}
        empty={dealsUnknown
          ? "The opportunities could not be read. This is not a statement "
            + "that none are linked to this contact."
          : "No opportunities linked to this contact"}
      />
    </RecordPage>
  );
}
