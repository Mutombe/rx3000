/** Trading periods — the accounting month everything is filed under.
 *
 *  The screen exists to make one rule visible: a closed period will not accept
 *  a posting. Everything else here is in service of that — the status, the
 *  frozen figures, and the drift warning that appears if what a period contains
 *  now disagrees with what was signed off.
 *
 *  Reopening asks for a password and a reason. It is deliberately possible: a
 *  pharmacy that genuinely finds a missing invoice will otherwise date it into
 *  the current month, and the accounts will be wrong in a way nobody can see.
 */
import { useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import { useStepUp } from "../components/StepUp";

interface Period {
  id: number;
  code: string;
  name: string;
  start_date: string;
  end_date: string;
  status: "open" | "closed" | "locked";
  opened_at: string | null;
  closed_at: string | null;
  opened_by: string;
  closed_by: string;
  notes: string;
  closing_sales: number;
  closing_vat: number;
  closing_transactions: number;
  postable: boolean;
  live?: { sales: number; vat: number; cost: number; transactions: number };
  drift?: number;
  drift_warning?: string;
}

const STATUS_HINT: Record<string, string> = {
  open: "Trading. Postings are accepted.",
  closed: "Signed off. Nothing new posts here unless it is reopened.",
  locked: "Sealed after a return or an audit. It cannot be reopened at all.",
};

export default function Periods() {
  const [periods, setPeriods] = useState<Period[]>([]);
  const [current, setCurrent] = useState<Period | null>(null);
  const toast = useToast();
  const [reopening, setReopening] = useState<Period | null>(null);
  const [reason, setReason] = useState("");
  const { guarded, prompt } = useStepUp();

  function load() {
    api.get<Period[]>("/api/periods").then(setPeriods).catch((e) => toast.error(errorText(e)));
    api.get<Period>("/api/periods/current").then(setCurrent).catch(() => undefined);
  }

  useEffect(load, []);

  async function act(period: Period, verb: "close" | "lock", body: unknown = {}) {
        try {
      await api.post(`/api/periods/${period.code}/${verb}`, body);
      toast.ok(`${period.name} ${verb === "close" ? "closed" : "locked"}.`);
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  async function reopen() {
    if (!reopening) return;
    const period = reopening;
        try {
      await guarded(
        "period.reopen",
        (token) =>
          api.post(`/api/periods/${period.code}/reopen`, { reason }, token),
        period.code,
      );
      toast.ok(`${period.name} reopened. The reason is on the period's record.`);
      setReopening(null);
      setReason("");
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Trading periods</h1>
          <p className="muted">
            {current
              ? `Currently trading in ${current.name}. ${current.live?.transactions ?? 0} transactions, ${money(current.live?.sales)}.`
              : ""}
          </p>
        </div>
      </header>

      <table className="dt">
        <thead>
          <tr>
            <th>Period</th>
            <th>Runs</th>
            <th>Status</th>
            <th className="num">Signed off at</th>
            <th className="num">Transactions</th>
            <th>Closed by</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {periods.map((p) => (
            <tr key={p.code} className={p.drift ? "row-flag" : undefined}>
              <td className="mono">
                {p.code}
                <div className="muted small">{p.name}</div>
              </td>
              <td>
                {fmtDate(p.start_date)} – {fmtDate(p.end_date)}
              </td>
              <td>
                <span className={`badge ${p.status === "open" ? "ok" : p.status === "locked" ? "warn" : ""}`}>
                  {p.status}
                </span>
                <div className="muted small">{STATUS_HINT[p.status]}</div>
                {p.drift_warning && (
                  <div className="alert error small">{p.drift_warning}</div>
                )}
              </td>
              <td className="num">
                {p.status === "open" ? (
                  <span className="muted">—</span>
                ) : (
                  money(p.closing_sales)
                )}
              </td>
              <td className="num">
                {p.status === "open" ? (
                  <span className="muted">—</span>
                ) : (
                  p.closing_transactions
                )}
              </td>
              <td>
                {p.closed_by || <span className="muted">—</span>}
                {p.closed_at && (
                  <div className="muted small">{fmtDateTime(p.closed_at)}</div>
                )}
              </td>
              <td className="actions">
                {p.status === "open" && (
                  <button className="btn sm" onClick={() => act(p, "close")}>
                    Close
                  </button>
                )}
                {p.status === "closed" && (
                  <>
                    <button className="btn ghost sm" onClick={() => setReopening(p)}>
                      Reopen
                    </button>
                    <button className="btn sm" onClick={() => act(p, "lock")}>
                      Lock
                    </button>
                  </>
                )}
                {p.status === "locked" && <span className="muted small">Sealed</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {reopening && (
        <div className="modal-backdrop" onClick={() => setReopening(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Reopen {reopening.name}</h2>
            <p className="muted">
              This month was signed off at {money(reopening.closing_sales)}. Reopening
              lets a figure somebody has already reported change underneath them, so
              the reason is kept on the period's own record and an administrator's
              password is required.
            </p>
            <label>
              Reason
              <input
                value={reason}
                autoFocus
                onChange={(e) => setReason(e.target.value)}
                placeholder="Supplier invoice arrived late"
              />
            </label>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setReopening(null)}>
                Leave it closed
              </button>
              <button
                className="btn danger"
                disabled={!reason.trim()}
                onClick={reopen}
              >
                Reopen
              </button>
            </div>
          </div>
        </div>
      )}

      {prompt}
    </div>
  );
}
