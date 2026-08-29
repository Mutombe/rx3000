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
import { useStepUp, CANCELLED } from "../components/StepUp";
import IconButton from "../components/IconButton";
import BusyButton from "../components/BusyButton";
import { Refreshable, TableSkeleton } from "../components/Skeleton";

interface VatReturn {
  period_code: string; period_name: string; period_status: string;
  from: string; to: string; vat_rate: number;
  turnover_excluding_vat: number; output_tax: number; input_tax: number;
  payable: number; direction: string; warning: string;
}

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
  const [loading, setLoading] = useState(true);
  const [current, setCurrent] = useState<Period | null>(null);
  const toast = useToast();
  const [reopening, setReopening] = useState<Period | null>(null);
  const [reason, setReason] = useState("");
  const { guarded, prompt } = useStepUp();
  // The VAT return for one period. Reached from the period it belongs to rather
  // than from a screen of its own, because the figures are only trustworthy once
  // that period is closed — and the server says so on the return itself.
  const [vat, setVat] = useState<VatReturn | null>(null);
  const [vatBusy, setVatBusy] = useState("");

  function load() {
    api.get<Period[]>("/api/periods").then(setPeriods)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
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
      const res = await guarded(
        "period.reopen",
        (token) =>
          api.post(`/api/periods/${period.code}/reopen`, { reason }, token),
        period.code,
      );
      // Somebody backed out of the password prompt, so the period is still
      // closed. Saying it reopened would be a lie the next person acts on.
      if (res === CANCELLED) return;
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

      <div className="dt-scroll">
        <Refreshable
          loading={loading}
          hasData={periods.length > 0}
          skeleton={<TableSkeleton cols={6} rows={5} />}
        >
        <table className="dt">
          <thead>
            <tr>
              <th>Period</th>
              <th>Runs</th>
              <th>Status</th>
              <th className="num">Signed off at</th>
              <th className="num">Transactions</th>
              <th>Closed by</th>
              <th className="actions" />
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
                  <div className="muted small clip-2" title={STATUS_HINT[p.status]}>{STATUS_HINT[p.status]}</div>
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
                    <BusyButton className="btn sm" onClick={() => act(p, "close")}>
                      Close
                    </BusyButton>
                  )}
                  <button
                    className="btn ghost sm"
                    disabled={vatBusy === p.code}
                    onClick={async () => {
                      setVatBusy(p.code);
                      try {
                        setVat(await api.get<VatReturn>(`/api/ledger/vat-return/${p.code}`));
                      } catch (e) {
                        toast.error(errorText(e, "That VAT return could not be worked out."));
                      } finally {
                        setVatBusy("");
                      }
                    }}
                  >
                    {vatBusy === p.code ? "Working…" : "VAT return"}
                  </button>
                  {p.status === "closed" && (
                    <>
                      <button className="btn ghost sm" onClick={() => setReopening(p)}>
                        Reopen
                      </button>
                      <BusyButton className="btn sm" onClick={() => act(p, "lock")}>
                        Lock
                      </BusyButton>
                    </>
                  )}
                  {p.status === "locked" && <span className="muted small">Sealed</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </Refreshable>
      </div>

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

      {vat && (
        <div className="modal-backdrop" onClick={() => setVat(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>VAT return for {vat.period_name}</h2>
            <p className="muted">
              {fmtDate(vat.from)} to {fmtDate(vat.to)}, at {(vat.vat_rate * 100).toFixed(0)}%.
            </p>
            {/* Which basis, said plainly. This is worked out from the posted
                income accounts, and the VAT figure in Analytics is worked out
                from till sales — the two legitimately differ when something has
                been sold and not yet posted. This is the one that ties to the
                accounts a revenue authority will ask to see, so it is the one to
                file, and a screen that showed two VAT totals without saying which
                is which invites the wrong one to be filed. */}
            <p className="muted small">
              From the posted income accounts, so it ties to the ledger rather than
              to the till. The VAT figure under Analytics counts till sales instead
              and will differ while anything is unposted.
            </p>

            {/* The server's own warning, verbatim. A return filed from a period
                that can still receive postings will not match the accounts when
                somebody checks it, and that is worth more than a tidy screen. */}
            {vat.warning && <p className="alert warn">{vat.warning}</p>}

            <table>
              <tbody>
                <tr>
                  <td>Turnover excluding VAT</td>
                  <td className="num mono">{money(vat.turnover_excluding_vat)}</td>
                </tr>
                <tr>
                  <td>Output tax <span className="muted">— charged on sales</span></td>
                  <td className="num mono">{money(vat.output_tax)}</td>
                </tr>
                <tr>
                  <td>Input tax <span className="muted">— paid on purchases</span></td>
                  <td className="num mono">{money(vat.input_tax)}</td>
                </tr>
                <tr>
                  <td><b>{vat.direction}</b></td>
                  <td className="num mono"><b>{money(Math.abs(vat.payable))}</b></td>
                </tr>
              </tbody>
            </table>

            <div className="modal-actions">
              <IconButton action="print" onClick={() => window.print()} />
              <button className="btn primary" onClick={() => setVat(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
