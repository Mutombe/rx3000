/** One lead: who it is, where it came from, and what happened to it.
 *
 *  Leads appeared in three reports and none of them opened. A lead that has
 *  been converted is the interesting case — the report shows a name and a
 *  status, and the company, contact and deal it turned into were unreachable
 *  from it.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { Figure } from "../components/Skeleton";
import BusyButton from "../components/BusyButton";
import { useAsk, useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";
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

  const load = useCallback(() => {
    api.get<Data>(`/api/crm/leads/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That lead could not be opened.")));
  }, [id]);
  useEffect(load, [load]);

  const name = d ? `${d.first_name} ${d.last_name}`.trim() : "";
  const owner = d?.owner?.full_name || d?.owner?.name || "";

  const toast = useToast();
  const ask = useAsk();
  const confirm = useConfirm();
  /** The two things anybody does to a lead, from the page that describes it.
   *
   *  Both endpoints existed and only the list reached them, so reading a lead
   *  and acting on it were two screens.
   */
  async function setStatus(next: string) {
    if (!d) return;
    let reason = "";
    if (next === "disqualified") {
      const answer = await ask({
        title: "Why is this lead disqualified?",
        body: "The reason is what makes the loss worth anything later.",
        field: "Reason",
        placeholder: "No budget, went elsewhere, not a pharmacy",
        required: true,
        confirmLabel: "Disqualify",
        destructive: true,
      });
      if (!answer.ok) return;
      reason = answer.value;
    }
    try {
      await api.post(`/api/leads/${d.id}/status`, { status: next, reason });
      toast.ok(`Marked ${next}.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  async function convert() {
    if (!d) return;
    const ok = await confirm({
      title: `Convert ${d.first_name} ${d.last_name}?`,
      body: (
        <>
          They become an account and a contact, and the lead is closed as won.
          {d.estimated_value > 0 && (
            <> An opportunity worth <b>{money(d.estimated_value)}</b> is opened
              alongside them.</>
          )}
        </>
      ),
      confirmLabel: "Convert",
    });
    if (!ok) return;
    try {
      await api.post(`/api/leads/${d.id}/convert`, {});
      toast.ok("Converted.");
      load();
    } catch (e) {
      toast.error(errorText(e, "That lead could not be converted."));
    }
  }
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
      actions={d && (
        <div className="page-actions">
          {d.status !== "converted" && d.status !== "disqualified" && (
            <>
              <BusyButton className="btn primary" onClick={convert}
                          busyLabel="Converting…">
                Convert
              </BusyButton>
              <BusyButton className="btn" busyLabel="Saving…"
                          onClick={() => setStatus("contacted")}>
                Mark contacted
              </BusyButton>
              <BusyButton className="btn ghost" busyLabel="Saving…"
                          onClick={() => setStatus("disqualified")}>
                Disqualify
              </BusyButton>
            </>
          )}
        </div>
      )}
      facts={[
        /* The four words above the strip are the same for every lead, so they
           are drawn at once and only the answers wait. */
        { label: "Status",
          value: <Figure ready={!!d} w="12ch">{d?.status}</Figure>,
          hint: d?.converted_at ? "converted" : undefined },
        { label: "Rating",
          value: <Figure ready={!!d} w="8ch">{d && (d.rating || "none")}</Figure>,
          hint: <>score <Figure ready={!!d} w="3ch">{d?.score}</Figure></> },
        { label: "Worth",
          value: <Figure ready={!!d} w="9ch">{d && money(d.estimated_value)}</Figure> },
        { label: "Source",
          value: <Figure ready={!!d} w="14ch">{d && (d.source || "none")}</Figure> },
      ]}
    >
      {/* The gate that stood here withheld both card headings and the eleven
          labels under them until the lead came back. Every lead is asked the
          same eleven questions, and those words are written here rather than
          fetched. Only the answers beside them pulse. */}
      {d && d.status === "disqualified" && d.disqualified_reason && (
        <div className="alert warn">
          <b>Disqualified</b>: {d.disqualified_reason}
        </div>
      )}

      {/* The whole point of keeping a converted lead: what it became. */}
      {d?.converted_at && (
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
            <dt>Name</dt>
            <dd><Figure ready={!!d} w="18ch">{d && (name || "none")}</Figure></dd>
            <dt>Company</dt>
            <dd><Figure ready={!!d} w="20ch">{d && (d.company_name || "none")}</Figure></dd>
            <dt>Role</dt>
            <dd><Figure ready={!!d} w="16ch">{d && (d.job_title || "none")}</Figure></dd>
            <dt>Telephone</dt>
            <dd><Figure ready={!!d} w="14ch">{d && (d.phone || "none")}</Figure></dd>
            <dt>Email</dt>
            <dd><Figure ready={!!d} w="24ch">{d && (d.email || "none")}</Figure></dd>
            <dt>Marketing</dt>
            <dd>
              <Figure ready={!!d} w="12ch">
                {d && (d.marketing_opt_in ? "opted in" : "Not opted in")}
              </Figure>
            </dd>
          </dl>
        </Panel>

        <Panel title="Where it came from">
          <dl className="kv">
            <dt>Source</dt>
            <dd><Figure ready={!!d} w="14ch">{d && (d.source || "none")}</Figure></dd>
            <dt>Interest</dt>
            <dd><Figure ready={!!d} w="20ch">{d && (d.interest || "none")}</Figure></dd>
            <dt>Campaign</dt>
            <dd>
              <Figure ready={!!d} w="10ch">
                {d && (
                  <EntityLink kind="campaign" id={d.campaign_id}>
                    {d.campaign_id ? `#${d.campaign_id}` : "none"}
                  </EntityLink>
                )}
              </Figure>
            </dd>
            <dt>Owner</dt>
            <dd>
              <Figure ready={!!d} w="16ch">
                {d && (
                  <EntityLink kind="staff" id={d.owner_id}>{owner || "unassigned"}</EntityLink>
                )}
              </Figure>
            </dd>
            <dt>Created</dt>
            <dd><Figure ready={!!d} w="16ch">{d && fmtDateTime(d.created_at)}</Figure></dd>
          </dl>
        </Panel>
      </div>
    </RecordPage>
  );
}
