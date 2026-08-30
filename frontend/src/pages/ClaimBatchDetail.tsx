/** One claim batch, and every claim inside it.
 *
 *  The claiming screen shows a batch that came back four hundred dollars short
 *  and stops there. That figure is not actionable — the question is always
 *  *which* claims were cut, by how much, and for whom, and answering it meant
 *  opening claims one at a time from another screen and adding up by hand.
 *
 *  The endpoint had been returning the whole batch since claiming was written.
 *  Nothing called it.
 *
 *  Two things this insists on:
 *
 *  **Short is only short once the batch is settled.** A claim that has not been
 *  paid yet is outstanding, not short, and painting it red teaches staff that
 *  red means nothing.
 *
 *  **What the named lines do not account for is shown, not absorbed.** When a
 *  scheme deducts something that belongs to no single claim — a levy
 *  adjustment, an old recovery — that is the most important number on the page,
 *  and rounding it into the total is how it stays undiscovered for a year.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, errorText, fmtDate, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";

interface Line {
  id: number; claim_number: string; status: string;
  patient: string; patient_id: number | null;
  sale_id: number | null; sale_number: string;
  gross: number; levy: number; amount_claimed: number;
  amount_approved: number; settled_amount: number; shortfall: number;
  patient_liable: number; response_message: string; created_at: string;
}
interface Batch {
  id: number; batch_number: string; status: string;
  claim_count: number; total_gross: number; total_discount: number;
  total_levy: number; total_claimed: number; total_settled: number;
  period_from: string | null; period_to: string | null;
  submitted_at: string | null; settled_at: string | null;
  reference: string; notes: string; created_at: string;
  pay_office?: { id: number; name: string } | null;
}
interface Data {
  batch: Batch; settled: boolean; shortfall: number;
  unattributed: number; short_count: number; rejected: number;
  counted_on_batch: number; found: number;
  claims: Line[];
}

/** The badge a claim's state deserves. Red is reserved for a refusal — the one
 *  state where somebody has to do something today. */
function tone(status: string) {
  if (status === "rejected") return "bad";
  if (status === "partial" || status === "deferred") return "warn";
  if (status === "approved") return "ok";
  return "muted";
}

export default function ClaimBatchDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/claiming/batches/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That batch could not be opened.")));
  }, [id]);

  const b = d?.batch;
  const period = b?.period_from
    ? `${fmtDate(b.period_from)}${b.period_to ? ` – ${fmtDate(b.period_to)}` : ""}`
    : "";

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Claiming", to: "/claiming" },
              { label: b?.batch_number ?? "This batch" }]}
      eyebrow="Claim batch"
      title={b?.batch_number ?? ""}
      subtitle={b && [b.pay_office?.name, period,
                      b.settled_at ? `settled ${fmtDate(b.settled_at)}`
                        : b.submitted_at ? `sent ${fmtDate(b.submitted_at)}`
                          : "not sent yet"].filter(Boolean).join(" · ")}
      loading={!d && !error}
      error={error}
      facts={d && b ? [
        { label: "Claimed", value: money(b.total_claimed),
          hint: `${b.claim_count} claim${b.claim_count === 1 ? "" : "s"}` },
        { label: "Settled", value: money(b.total_settled),
          hint: d.settled ? "paid by the scheme" : "not paid yet" },
        // Only meaningful once the money has come back. Before that it is the
        // whole batch, which is not a shortfall, it is a queue.
        { label: d.settled ? "Short" : "Outstanding",
          value: money(d.settled ? d.shortfall : b.total_claimed),
          hint: d.settled
            ? `${d.short_count} claim${d.short_count === 1 ? "" : "s"} cut`
            : "waiting on the scheme",
          tone: d.settled && d.shortfall > 0.005 ? "bad" : undefined },
        { label: "Levies", value: money(b.total_levy),
          hint: "paid by patients at the counter" },
      ] : undefined}
    >
      {d && b && (
        <>
          {d.settled && Math.abs(d.unattributed) > 0.005 && (
            // The number this page exists for. A deduction that belongs to no
            // claim is the one a pharmacy never finds, because every screen
            // that could show it rounds it into a total.
            <div className="alert warn">
              <b>{money(Math.abs(d.unattributed))} of this batch is not
              accounted for by any single claim.</b>{" "}
              The lines below come to {money(d.shortfall - d.unattributed)} short
              between them, but the scheme paid {money(d.shortfall)} less than was
              asked for. The difference is a deduction against the batch as a
              whole — a levy adjustment, or a recovery from an earlier period.
              It is worth asking the pay office what it was for.
            </div>
          )}

          {d.counted_on_batch !== d.found && (
            // Two numbers that disagree, said out loud. The batch records that
            // it holds five claims; five claims cannot be found attached to it.
            // The totals above therefore describe claims this page cannot show,
            // and a reader has to know that before trusting them.
            <div className="alert error">
              <b>This batch says it holds {d.counted_on_batch} claim
              {d.counted_on_batch === 1 ? "" : "s"}, and {d.found === 0
                ? "none can be found attached to it"
                : `only ${d.found} can be found attached to it`}.</b>{" "}
              The totals above come from the batch's own record, so they describe
              claims that are not listed below. Something detached them — a
              reversal, or a migration from another system. The figures the
              scheme was sent are still the batch's, but nothing here can show
              you what they were made of.
            </div>
          )}

          {d.rejected > 0 && (
            <div className="alert error">
              {d.rejected} claim{d.rejected === 1 ? " was" : "s were"} refused
              outright. A refusal is not a shortfall — the money will not arrive
              later, and the amount falls to the patient or to the pharmacy.
            </div>
          )}

          <Panel title="Claims in this batch" count={d.claims.length}
                 empty={d.counted_on_batch > 0
                   ? "The claims this batch was built from are no longer attached to it."
                   : "Nothing has been added to this batch yet."}
                 aside={b.reference
                   ? <span className="muted small">Scheme reference {b.reference}</span>
                   : undefined}>
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Claim</th>
                    <th>Patient</th>
                    <th>Sale</th>
                    <th>Status</th>
                    <th className="num">Claimed</th>
                    <th className="num">Approved</th>
                    <th className="num">Settled</th>
                    <th className="num">Short</th>
                  </tr>
                </thead>
                <tbody>
                  {d.claims.map((c) => (
                    <tr key={c.id}
                        className={c.status === "rejected" ? "row-danger"
                          : c.shortfall > 0.005 ? "row-warn" : undefined}>
                      <td className="mono">
                        <EntityLink kind="claim" id={c.id}>{c.claim_number}</EntityLink>
                      </td>
                      <td>
                        <EntityLink kind="patient" id={c.patient_id}>
                          {c.patient || "—"}
                        </EntityLink>
                      </td>
                      <td className="mono">
                        <EntityLink kind="sale" id={c.sale_id}>
                          {c.sale_number || "—"}
                        </EntityLink>
                      </td>
                      <td>
                        <span className={`badge ${tone(c.status)}`}>{c.status}</span>
                        {c.response_message && (
                          <div className="muted small wrap">{c.response_message}</div>
                        )}
                      </td>
                      <td className="num">{money(c.amount_claimed)}</td>
                      <td className="num">
                        {c.amount_approved > 0.005
                          ? money(c.amount_approved)
                          : <span className="muted">—</span>}
                      </td>
                      <td className="num">
                        {d.settled ? money(c.settled_amount)
                          : <span className="muted">not yet</span>}
                      </td>
                      <td className="num">
                        {c.shortfall > 0.005
                          ? <b className="neg">{money(c.shortfall)}</b>
                          : <span className="muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={4}><b>Total</b></td>
                    <td className="num"><b>{money(b.total_claimed)}</b></td>
                    <td className="num" />
                    <td className="num">
                      <b>{d.settled ? money(b.total_settled) : "—"}</b>
                    </td>
                    <td className="num">
                      <b className={d.settled && d.shortfall > 0.005 ? "neg" : undefined}>
                        {d.settled ? money(d.shortfall) : "—"}
                      </b>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </Panel>

          <Panel title="How the batch was priced"
                 aside={<span className="muted small">
                   What was asked for, and why it is not the shelf price
                 </span>}>
            <table className="dt">
              <tbody>
                <tr>
                  <td>Gross</td>
                  <td className="muted wrap">Before the scheme's discount</td>
                  <td className="num">{money(b.total_gross)}</td>
                </tr>
                <tr>
                  <td>Scheme discount</td>
                  <td className="muted wrap">Agreed with the pay office</td>
                  <td className="num">−{money(b.total_discount)}</td>
                </tr>
                <tr>
                  <td>Levies</td>
                  <td className="muted wrap">
                    Collected from patients at the counter, so never claimed
                  </td>
                  <td className="num">−{money(b.total_levy)}</td>
                </tr>
                <tr>
                  <td><b>Claimed from the scheme</b></td>
                  <td />
                  <td className="num"><b>{money(b.total_claimed)}</b></td>
                </tr>
              </tbody>
            </table>
          </Panel>

          {b.notes && (
            <Panel title="Notes">
              <p className="wrap">{b.notes}</p>
            </Panel>
          )}
        </>
      )}
    </RecordPage>
  );
}
