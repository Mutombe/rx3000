/** One lead: who it is, where it came from, and what happened to it.
 *
 *  Leads appeared in three reports and none of them opened. A lead that has
 *  been converted is the interesting case — the report shows a name and a
 *  status, and the company, contact and deal it turned into were unreachable
 *  from it.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useParams } from "react-router-dom";

interface Data {
  id: number; first_name: string; last_name: string;
  company_name: string; job_title: string;
  email: string; phone: string;
  source: string; status: string; interest: string;
  rating: string; score: number; estimated_value: number;
  marketing_opt_in: boolean;
  disqualified_reason: string;
  campaign_id: number | null;
  owner_id: number | null;
  owner?: { id: number; full_name?: string; name?: string } | null;
  created_at: string;
  converted_at: string | null;
  converted_company_id: number | null;
  converted_contact_id: number | null;
  converted_deal_id: number | null;
}

export default function LeadDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/crm/leads/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That lead could not be opened.")));
  }, [id]);

  const name = d ? `${d.first_name} ${d.last_name}`.trim() : "";
  const owner = d?.owner?.full_name || d?.owner?.name || "";

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Leads", to: "/leads" },
              { label: name || "This lead" }]}
      eyebrow="Lead"
      title={name || d?.company_name || ""}
      subtitle={d && [d.job_title, d.company_name].filter(Boolean).join(" · ")}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Status", value: d.status,
          hint: d.converted_at ? "converted" : undefined },
        { label: "Rating", value: d.rating || "—", hint: `score ${d.score}` },
        { label: "Worth", value: money(d.estimated_value) },
        { label: "Source", value: d.source || "—" },
      ] : undefined}
    >
      {d && (
        <>
          {d.status === "disqualified" && d.disqualified_reason && (
            <div className="alert warn">
              <b>Disqualified</b> — {d.disqualified_reason}
            </div>
          )}

          {/* The whole point of keeping a converted lead: what it became. */}
          {d.converted_at && (
            <div className="alert ok">
              Converted on {fmtDateTime(d.converted_at)} into{" "}
              <EntityLink kind="account" id={d.converted_company_id}>the account</EntityLink>,{" "}
              <EntityLink kind="contact" id={d.converted_contact_id}>the contact</EntityLink>
              {d.converted_deal_id && <> and{" "}
                <EntityLink kind="deal" id={d.converted_deal_id}>the opportunity</EntityLink></>}.
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="Who they are">
              <dl className="kv">
                <dt>Name</dt><dd>{name || "—"}</dd>
                <dt>Company</dt><dd>{d.company_name || "—"}</dd>
                <dt>Role</dt><dd>{d.job_title || "—"}</dd>
                <dt>Telephone</dt><dd>{d.phone || "—"}</dd>
                <dt>Email</dt><dd>{d.email || "—"}</dd>
                <dt>Marketing</dt>
                <dd>{d.marketing_opt_in ? "opted in" : "not opted in"}</dd>
              </dl>
            </Panel>

            <Panel title="Where it came from">
              <dl className="kv">
                <dt>Source</dt><dd>{d.source || "—"}</dd>
                <dt>Interest</dt><dd>{d.interest || "—"}</dd>
                <dt>Campaign</dt>
                <dd>
                  <EntityLink kind="campaign" id={d.campaign_id}>
                    {d.campaign_id ? `#${d.campaign_id}` : "—"}
                  </EntityLink>
                </dd>
                <dt>Owner</dt>
                <dd>
                  <EntityLink kind="staff" id={d.owner_id}>{owner || "unassigned"}</EntityLink>
                </dd>
                <dt>Created</dt><dd>{fmtDateTime(d.created_at)}</dd>
              </dl>
            </Panel>
          </div>
        </>
      )}
    </RecordPage>
  );
}
