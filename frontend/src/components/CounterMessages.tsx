/** What the pharmacist must see before the medicine leaves the counter.
 *
 *  This panel exists because a warning shown *after* the hand-over is not a
 *  warning. It loads as soon as there is a patient and a basket, so it is on
 *  screen while the script is still being built rather than appearing at the
 *  moment somebody is trying to finish.
 *
 *  Blocking messages are not dismissible. Each has to be acknowledged by name,
 *  and the acknowledgement is kept — that is the whole difference between a
 *  banner and a control. A busy assistant scrolls past a banner.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

export interface CounterMessage {
  id: number | null;
  scope: string;
  severity: "info" | "warn" | "stop";
  category: string;
  body: string;
  source: string;
  blocking: boolean;
}

interface Payload {
  messages: CounterMessage[];
  count: number;
  blocking: CounterMessage[];
  must_acknowledge: number[];
  can_dispense: boolean;
  summary: string;
}

interface Props {
  patientId?: number | null;
  productIds: number[];
  medicalAidId?: number | null;
  /** The script these acknowledgements attach to, once one exists. */
  prescriptionId?: number | null;
  /** Told whether anything is still blocking, so the caller can gate its button. */
  onBlockingChange?: (blocking: boolean) => void;
}

const TONE: Record<string, string> = { stop: "error", warn: "warn", info: "" };

export default function CounterMessages({
  patientId,
  productIds,
  medicalAidId,
  prescriptionId,
  onBlockingChange,
}: Props) {
  const [data, setData] = useState<Payload | null>(null);
  const [acked, setAcked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");

  const key = `${patientId ?? ""}|${productIds.join(",")}|${medicalAidId ?? ""}`;

  const load = useCallback(() => {
    if (!patientId && !productIds.length) {
      setData(null);
      return;
    }
    const params = new URLSearchParams();
    if (patientId) params.set("patient_id", String(patientId));
    if (medicalAidId) params.set("medical_aid_id", String(medicalAidId));
    productIds.forEach((id) => params.append("product_ids", String(id)));
    api
      .get<Payload>(`/api/counter-messages/for-dispensing?${params}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [key]);

  useEffect(load, [key]);

  const outstanding = (data?.blocking ?? []).filter(
    (m) => m.id === null || !acked.has(m.id),
  );

  useEffect(() => {
    onBlockingChange?.(outstanding.length > 0);
  }, [outstanding.length]);

  async function acknowledge(message: CounterMessage) {
    if (message.id === null) return;
    if (!prescriptionId) {
      // Acknowledgement is recorded against a script. Before one exists there
      // is nothing to attach it to, and pretending otherwise would lose it.
      setError(
        "Capture the script first. An acknowledgement is recorded against it, " +
          "not against the screen.",
      );
      return;
    }
    setBusy(message.id);
    setError("");
    try {
      await api.post(`/api/counter-messages/${message.id}/acknowledge`, {
        prescription_id: prescriptionId,
      });
      setAcked(new Set([...acked, message.id]));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!data || !data.count) return null;

  return (
    <section className="panel counter-messages">
      <header className="panel-head">
        <h3>Before you dispense</h3>
        <span className="muted small">{data.summary}</span>
      </header>

      {error && <div className="alert error">{error}</div>}

      <ul className="msg-list">
        {data.messages.map((m, i) => {
          const done = m.id !== null && acked.has(m.id);
          return (
            <li key={m.id ?? `derived-${i}`} className={`msg ${TONE[m.severity]}`}>
              <div className="msg-body">
                <span className="badge">{m.source}</span>
                {m.category && <span className="badge">{m.category}</span>}
                <p>{m.body}</p>
              </div>
              {m.blocking && (
                <div className="msg-action">
                  {done ? (
                    <span className="badge ok">acknowledged</span>
                  ) : (
                    <button
                      className="btn danger sm"
                      disabled={busy === m.id}
                      onClick={() => acknowledge(m)}
                    >
                      {busy === m.id ? "Recording…" : "I have checked this"}
                    </button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {outstanding.length > 0 && (
        <p className="alert error">
          {outstanding.length} warning{outstanding.length > 1 ? "s" : ""} must be
          acknowledged before this script can be dispensed. Your name is recorded
          against each one.
        </p>
      )}
    </section>
  );
}
