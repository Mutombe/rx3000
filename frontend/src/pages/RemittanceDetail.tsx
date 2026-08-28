/** One payment from one funder, and what it did to the claims it names.
 *
 *  The listing could say CIMAS paid ninety-one dollars against a hundred and
 *  fourteen, that five lines came back short and two matched nothing — and gave
 *  no way to find out which. That is the whole job: a shortfall is not work
 *  until you can see whose claim it was and why, and decide whether the patient
 *  owes it or the pharmacy swallows it.
 *
 *  Both of those are real money leaving, so neither happens without a reason
 *  written down. "Reduced by the member's levy" is billed on; "not on the
 *  formulary" usually is not, and a pharmacy that writes off both without
 *  looking is one paying its patients' levies for them.
 */
import { useCallback, useEffect, useState } from "react";
import { Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useToast } from "../components/Toast";
import { useParams } from "react-router-dom";

interface Line {
  id: number; line_number: number; claim_reference: string;
  policy_number: string; member_name: string; service_date: string | null;
  amount_claimed: number; amount_allowed: number; amount_paid: number;
  variance: number; reason_code: string; reason: string; status: string;
  claim_id: number | null; gateway_transaction_id: string;
  written_off: boolean; patient_billed: boolean; resolution_note: string;
}
interface Reason { reason_code: string; reason: string; lines: number; amount: number }
interface Advice {
  id: number; remittance_number: string; funder_id: string;
  payment_date: string | null; payment_reference: string; currency_code: string;
  status: string; line_count: number;
  total_claimed: number; total_paid: number;
  shortfall: number; outstanding: number;
  counts: Record<string, number>; unmatched: number;
  by_reason: Reason[]; lines: Line[];
}

/** What each state means at a glance, in the reader's terms not the table's. */
const TONE: Record<string, string> = {
  matched: "ok", short_paid: "warn", rejected: "bad",
  unmatched: "bad", overpaid: "warn",
};
const STATE: Record<string, string> = {
  matched: "paid in full", short_paid: "short paid", rejected: "refused",
  unmatched: "no claim found", overpaid: "overpaid",
};

type Action = "bill_patient" | "write_off" | "reopen";

export default function RemittanceDetail() {
  const { id } = useParams();
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [error, setError] = useState("");
  // Asking for the reason in the row itself was the first attempt and it broke
  // the row. The action column is sized by counting the buttons it holds and
  // clips whatever exceeds that, so an input beside two buttons pushed both
  // past the clip and they stopped being clickable at all — caught by trying to
  // click one, not by looking at it. A modal also suits the question better:
  // "why is the pharmacy absorbing this" deserves more than a box three
  // characters wide.
  const [asking, setAsking] = useState<{ line: Line; action: Action } | null>(null);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const toast = useToast();

  const load = useCallback(() => {
    api.get<Advice>(`/api/remittances/${id}`)
      .then(setAdvice)
      .catch((e) => setError(errorText(e, "That advice could not be opened.")));
  }, [id]);
  useEffect(() => { setAdvice(null); load(); }, [load]);

  async function resolve(line: Line, action: Action, note = "") {
    setBusy(line.id);
    try {
      await api.post(
        `/api/remittances/lines/${line.id}/resolve?action=${action}`
        + `&note=${encodeURIComponent(note)}`, {});
      toast.ok(action === "bill_patient" ? "Billed to the patient."
             : action === "write_off" ? "Written off."
             : "Reopened.");
      setAsking(null);
      setWhy("");
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded."));
    } finally {
      setBusy(null);
    }
  }

  const open = advice?.lines.filter(
    (l) => (l.status === "short_paid" || l.status === "rejected")
           && !l.written_off && !l.patient_billed) ?? [];

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Remittances", to: "/remittances" },
              { label: advice?.remittance_number ?? "This advice" }]}
      eyebrow="Remittance advice"
      title={advice?.remittance_number ?? ""}
      subtitle={advice?.funder_id}
      loading={!advice && !error}
      error={error}
      facts={advice ? [
        { label: "Claimed", value: money(advice.total_claimed) },
        { label: "Paid", value: money(advice.total_paid),
          hint: advice.payment_date ? `on ${fmtDate(advice.payment_date)}` : undefined },
        { label: "Short", value: advice.shortfall > 0.005 ? money(advice.shortfall) : "nothing" },
        { label: "Still to settle", value: advice.outstanding > 0.005
            ? money(advice.outstanding) : "nothing",
          hint: open.length ? `${open.length} lines` : undefined },
      ] : undefined}
    >
      {advice && (
        <>
          {advice.unmatched > 0 && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />
              <span>
                <b>{advice.unmatched} line{advice.unmatched === 1 ? "" : "s"} match no
                claim of ours.</b> Either they have paid for something this
                pharmacy never sent, or the reference we submitted was wrong.
                Both are worth a telephone call before the money is banked
                against the wrong thing.
              </span>
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="The payment">
              <dl className="kv">
                <dt>Funder</dt><dd>{advice.funder_id}</dd>
                <dt>Paid on</dt>
                <dd>{advice.payment_date ? fmtDate(advice.payment_date) : "—"}</dd>
                <dt>Their reference</dt>
                <dd className="mono">{advice.payment_reference || "—"}</dd>
                <dt>Currency</dt><dd>{advice.currency_code}</dd>
                <dt>Lines</dt><dd>{advice.line_count}</dd>
                <dt>State</dt><dd>{advice.status}</dd>
              </dl>
            </Panel>

            <Panel title="Why they held money back" count={advice.by_reason.length}
                   empty="Every line paid in full.">
              {/* Ranked, because the top one or two reasons are usually the
                  whole story and are what goes back to the funder. */}
              <table className="dt">
                <thead>
                  <tr><th>Reason</th><th className="num">Lines</th><th className="num">Amount</th></tr>
                </thead>
                <tbody>
                  {advice.by_reason.map((r) => (
                    <tr key={r.reason_code}>
                      <td>
                        <span className="mono small">{r.reason_code}</span>
                        <div className="muted small">{r.reason}</div>
                      </td>
                      <td className="num">{r.lines}</td>
                      <td className="num">{money(r.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>

          <Panel title="Every line on the advice" count={advice.lines.length}>
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>#</th><th>Claim</th><th>Member</th>
                    <th className="num">Claimed</th><th className="num">Paid</th>
                    <th className="num">Short</th><th>What happened</th>
                    <th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {advice.lines.map((l) => {
                    const settled = l.written_off || l.patient_billed;
                    const owed = (l.status === "short_paid" || l.status === "rejected")
                                 && !settled;
                    return (
                      <tr key={l.id} className={owed ? "row-flag" : ""}>
                        <td className="muted">{l.line_number}</td>
                        <td className="mono">
                          {l.claim_id
                            ? <EntityLink kind="claim" id={l.claim_id}>{l.claim_reference}</EntityLink>
                            : (l.claim_reference || "—")}
                        </td>
                        <td>
                          {l.member_name || <span className="muted">—</span>}
                          {l.policy_number && (
                            <div className="muted small mono">{l.policy_number}</div>
                          )}
                        </td>
                        <td className="num">{money(l.amount_claimed)}</td>
                        <td className="num">{money(l.amount_paid)}</td>
                        <td className={`num${l.variance > 0.005 ? " cu-diff" : ""}`}>
                          {l.variance > 0.005 ? money(l.variance) : "—"}
                        </td>
                        <td>
                          <span className={`badge ${TONE[l.status] ?? ""}`}>
                            {STATE[l.status] ?? l.status}
                          </span>
                          {l.reason && <div className="muted small">{l.reason}</div>}
                          {/* Kept apart from the funder's own words, so a line
                              resolved twice does not rewrite what they said. */}
                          {l.resolution_note && (
                            <div className="muted small">{l.resolution_note}</div>
                          )}
                          {l.patient_billed && <span className="badge">billed on</span>}
                          {l.written_off && <span className="badge">written off</span>}
                        </td>
                        <td className="actions">
                          {owed ? (
                            <>
                              <button className="btn small"
                                      onClick={() => { setWhy(""); setAsking({ line: l, action: "bill_patient" }); }}>
                                Bill patient
                              </button>
                              <button className="btn small ghost"
                                      onClick={() => { setWhy(""); setAsking({ line: l, action: "write_off" }); }}>
                                Write off
                              </button>
                            </>
                          ) : settled ? (
                            <BusyButton className="btn small ghost"
                                        disabled={busy === l.id}
                                        onClick={() => resolve(l, "reopen")}>
                              Reopen
                            </BusyButton>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>

          {asking && (
            <div className="modal-backdrop" onClick={() => setAsking(null)}>
              <div className="modal" onClick={(e) => e.stopPropagation()}>
                <h2>
                  {asking.action === "bill_patient" ? "Bill this to the patient"
                                                    : "Write this off"}
                </h2>
                <p className="muted">
                  {asking.action === "bill_patient" ? (
                    <>
                      {money(asking.line.variance)} the funder did not pay goes
                      onto <b>{asking.line.member_name || "the patient"}</b>&rsquo;s
                      account. Right when it is their levy or co-payment — they
                      always owed it.
                    </>
                  ) : (
                    <>
                      The pharmacy absorbs {money(asking.line.variance)}. Right
                      when the money was never claimable, and wrong when it was
                      the patient&rsquo;s levy — writing those off is how a
                      pharmacy ends up paying its patients&rsquo; co-payments
                      for them.
                    </>
                  )}
                </p>
                <p className="muted small">
                  {asking.line.claim_reference}
                  {asking.line.reason ? ` — ${asking.line.reason}` : ""}
                </p>
                <label className="field">
                  Why
                  <input value={why} onChange={(e) => setWhy(e.target.value)}
                         placeholder="so the next person reading this knows"
                         autoFocus />
                </label>
                <div className="modal-actions">
                  <button className="btn ghost" onClick={() => setAsking(null)}>
                    Cancel
                  </button>
                  <BusyButton
                    disabled={busy === asking.line.id}
                    onClick={() => resolve(asking.line, asking.action, why.trim())}
                  >
                    {asking.action === "bill_patient" ? "Bill it on" : "Write it off"}
                  </BusyButton>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </RecordPage>
  );
}
