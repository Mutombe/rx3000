/** One claim: what was billed to the scheme, what came back, and what is left.
 *
 *  The claiming screens listed hundreds of claims and none of them opened. The
 *  question a clerk asks about a short payment — what did we ask for, what did
 *  they allow, and who owes the difference — had to be reassembled from three
 *  columns and a memory of the scheme's rules.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useParams } from "react-router-dom";

interface Line {
  product_id: number | null; product: string; quantity: number; line_total: number;
}
interface Data {
  id: number; claim_number: string; status: string;
  patient: { id: number | null; name: string; phone: string };
  scheme: { id: number | null; name: string };
  sale_id: number | null; sale_number: string;
  gross: number; discount: number; levy: number; dispensing_fee: number;
  amount_claimed: number; amount_approved: number; settled_amount: number;
  patient_liable: number; shortfall: number;
  icd10_code: string; authorisation: string;
  response_message: string; deferred_reason: string;
  submitted_at: string | null; settled_at: string | null;
  submit_attempts: number; created_at: string;
  lines: Line[];
}

const TONE: Record<string, string> = {
  approved: "ok", partial: "warn", rejected: "bad",
  deferred: "warn", submitted: "muted",
};

export default function ClaimDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/claims/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That claim could not be opened.")));
  }, [id]);

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Claiming", to: "/claiming" },
              { label: d?.claim_number ?? "This claim" }]}
      eyebrow="Claim"
      title={d?.claim_number ?? ""}
      subtitle={d && <>{d.scheme.name} · <EntityLink kind="patient" id={d.patient.id}>
        {d.patient.name}</EntityLink></>}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Claimed", value: money(d.amount_claimed) },
        { label: "Allowed", value: money(d.amount_approved),
          hint: d.shortfall > 0.005 ? `${money(d.shortfall)} short` : undefined },
        { label: "Settled", value: money(d.settled_amount),
          hint: d.settled_at ? fmtDateTime(d.settled_at) : "not yet paid" },
        { label: "Patient owes", value: money(d.patient_liable),
          hint: "levy and any shortfall" },
      ] : undefined}
    >
      {d && (
        <>
          {/* The scheme's own words, first. A clerk chasing a rejection needs
              the reason before any of the arithmetic. */}
          {(d.response_message || d.deferred_reason) && (
            <div className={`alert ${d.status === "rejected" ? "error" : "warn"}`}>
              <b>{d.status === "deferred" ? "Held" : d.status}</b>
              {" — "}{d.deferred_reason || d.response_message}
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="How it was priced">
              <dl className="kv">
                <dt>Gross</dt><dd className="num">{money(d.gross)}</dd>
                <dt>Scheme discount</dt><dd className="num">{money(d.discount)}</dd>
                <dt>Levy</dt><dd className="num">{money(d.levy)}</dd>
                <dt>Dispensing fee</dt><dd className="num">{money(d.dispensing_fee)}</dd>
                <dt>Claimed</dt><dd className="num"><b>{money(d.amount_claimed)}</b></dd>
                <dt>Allowed</dt><dd className="num">{money(d.amount_approved)}</dd>
                <dt>Shortfall</dt>
                <dd className="num">
                  {d.shortfall > 0.005 ? money(d.shortfall) : <span className="muted">none</span>}
                </dd>
              </dl>
            </Panel>

            <Panel title="The claim">
              <dl className="kv">
                <dt>Status</dt>
                <dd><span className={`badge ${TONE[d.status] ?? ""}`}>{d.status}</span></dd>
                <dt>Patient</dt>
                <dd>
                  <EntityLink kind="patient" id={d.patient.id}>{d.patient.name}</EntityLink>
                  {d.patient.phone && <div className="muted small">{d.patient.phone}</div>}
                </dd>
                <dt>Scheme</dt><dd>{d.scheme.name}</dd>
                <dt>Sale</dt>
                <dd className="mono">
                  <EntityLink kind="sale" id={d.sale_id}>{d.sale_number || "—"}</EntityLink>
                </dd>
                <dt>Diagnosis</dt><dd className="mono">{d.icd10_code || "—"}</dd>
                <dt>Authorisation</dt><dd className="mono">{d.authorisation || "—"}</dd>
                <dt>Submitted</dt>
                <dd>
                  {d.submitted_at ? fmtDateTime(d.submitted_at)
                    : <span className="muted">not sent</span>}
                  {d.submit_attempts > 1 && (
                    <div className="muted small">{d.submit_attempts} attempts</div>
                  )}
                </dd>
              </dl>
            </Panel>
          </div>

          <Panel title="What was dispensed" count={d.lines.length}
                 empty="No sale lines are attached to this claim.">
            <table className="dt">
              <thead>
                <tr><th>Medicine</th><th className="num">Qty</th><th className="num">Value</th></tr>
              </thead>
              <tbody>
                {d.lines.map((l, i) => (
                  <tr key={i}>
                    <td>
                      <EntityLink kind="product" id={l.product_id}>
                        {l.product || "—"}
                      </EntityLink>
                    </td>
                    <td className="num">{l.quantity}</td>
                    <td className="num">{money(l.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
