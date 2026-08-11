/** Claims held at the counter and not yet sent.
 *
 *  Every row here is money the pharmacy has already dispensed against and not
 *  yet asked anybody for. That is the whole reason the screen exists: a claim
 *  held because the switch was down is invisible until somebody looks, and what
 *  is invisible does not get sent.
 *
 *  "Send everything held" is the action a pharmacy runs when the switch comes
 *  back. One failure does not abort the run — a claim that cannot be sent stays
 *  held and is reported by name, because a batch that stops halfway leaves the
 *  queue in a state nobody can reason about.
 */
import { useEffect, useMemo, useState } from "react";
import { api, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import { useToast } from "../components/Toast";

interface Deferred {
  id: number;
  claim_number: string;
  sale_id: number;
  sale_number: string;
  patient_id: number | null;
  patient_name: string;
  medical_aid: string;
  amount_claimed: number;
  patient_liable: number;
  status: string;
  deferred_reason: string;
  deferred_at: string | null;
  created_at: string;
}

interface Summary {
  held: number;
  value_held: number;
  oldest_held_at: string | null;
  message: string;
}

interface BatchResult {
  attempted: number;
  submitted: number;
  still_held: number;
  failed: { claim_number: string; reason: string }[];
}

export default function DeferredClaims() {
  const [rows, setRows] = useState<Deferred[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const toast = useToast();
  const [busy, setBusy] = useState<number | "all" | null>(null);
  const [failures, setFailures] = useState<BatchResult["failed"]>([]);

  function load() {
    api.get<Deferred[]>("/api/claims/deferred").then(setRows).catch((e) => toast.error(e.message));
    api.get<Summary>("/api/claims/deferred/summary").then(setSummary).catch(() => undefined);
  }

  useEffect(load, []);

  async function submit(claim: Deferred) {
    setBusy(claim.id);
        try {
      const sent = await api.post<Deferred>(`/api/claims/${claim.id}/submit`);
      toast.ok(
        `${claim.claim_number} sent — ${sent.status}, ${money(sent.amount_claimed)} claimed.`,
      );
      load();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function submitAll() {
    setBusy("all");
        setFailures([]);
    try {
      const res = await api.post<BatchResult>("/api/claims/deferred/submit-all", {
        limit: 200,
      });
      toast.ok(
        `${res.submitted} of ${res.attempted} sent.` +
          (res.still_held ? ` ${res.still_held} could not be sent and stay held.` : ""),
      );
      setFailures(res.failed);
      load();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setBusy(null);
    }
  }

  const headline = useMemo(() => {
    if (!summary) return "";
    if (!summary.held) return "Nothing is held. Every claim has been sent.";
    return summary.message;
  }, [summary]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Claims held</h1>
          <p className="muted">{headline}</p>
        </div>
        {!!rows.length && (
          <button className="btn primary" disabled={busy !== null} onClick={submitAll}>
            {busy === "all" ? "Sending…" : `Send everything held (${rows.length})`}
          </button>
        )}
      </header>

      {failures.length > 0 && (
        <div className="alert warn">
          <strong>Still held:</strong>
          <ul>
            {failures.map((f) => (
              <li key={f.claim_number}>
                {f.claim_number} — {f.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!rows.length ? (
        <p className="muted pad">
          Nothing held. Claims land here when the switch is unreachable or a member's
          card is not present — the medicine goes out, and the claim waits.
        </p>
      ) : (
        <table className="dt">
          <thead>
            <tr>
              <th>Claim</th>
              <th>Sale</th>
              <th>Patient</th>
              <th>Scheme</th>
              <th className="num">Value</th>
              <th>Why it is held</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td className="mono">{c.claim_number}</td>
                <td>
                  <EntityLink to={`/sales/${c.sale_id}`}>{c.sale_number}</EntityLink>
                </td>
                <td>
                  {c.patient_id ? (
                    <EntityLink to={`/patients/${c.patient_id}`}>
                      {c.patient_name}
                    </EntityLink>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>{c.medical_aid || <span className="muted">—</span>}</td>
                <td className="num">{money(c.amount_claimed)}</td>
                <td>
                  {c.deferred_reason}
                  {c.deferred_at && (
                    <div className="muted small">held {fmtDateTime(c.deferred_at)}</div>
                  )}
                </td>
                <td className="actions">
                  <button
                    className="btn sm"
                    disabled={busy !== null}
                    onClick={() => submit(c)}
                  >
                    {busy === c.id ? "Sending…" : "Send now"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
