/** Trading periods: the accounting month everything is filed under.
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
import { api, fmtDate, fmtDateTime, money, errorText, sentence } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { useStepUp, CANCELLED } from "../components/StepUp";
import IconButton from "../components/IconButton";
import BusyButton from "../components/BusyButton";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import PageHead from "../components/PageHead";
import Th from "../components/Th";
import { EmptyRow } from "../components/Empty";

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
  const [opening, setOpening] = useState(false);
  const [month, setMonth] = useState("");
  const [reason, setReason] = useState("");
  const { guarded, prompt } = useStepUp();
  // The VAT return for one period. Reached from the period it belongs to rather
  // than from a screen of its own, because the figures are only trustworthy once
  // that period is closed, and the server says so on the return itself.
  const [vat, setVat] = useState<VatReturn | null>(null);
  const [vatBusy, setVatBusy] = useState("");

  function load() {
    api.get<Period[]>("/api/periods").then(setPeriods)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
    api.get<Period>("/api/periods/current").then(setCurrent).catch(() => undefined);
  }

  useEffect(load, []);

  /** Open a month, so figures that predate this system have somewhere to live.
   *
   *  THE EMPTY STATE SAID TO DO THIS AND NOTHING COULD.
   *
   *  "Until one is opened, nothing can be closed off" was the answer a new
   *  pharmacy got, on a screen with no way to open one. `POST /periods/{code}/
   *  open` has existed all along and no screen in the product called it, so a
   *  pharmacy switching systems in March could not make January exist and had
   *  nowhere to put January's figures.
   *
   *  Asked for as a month rather than a code. YYYYMM is what the server wants
   *  and 202601 is not what anybody calls January, so the month picker does
   *  the translation: a date input set to a month is a control every browser
   *  already draws.
   */
  async function openMonth() {
    const code = month.replace("-", "");
    if (code.length !== 6) {
      toast.warn("Choose the month to open.");
      return;
    }
    try {
      await api.post(`/api/periods/${code}/open`, {});
      toast.ok(`${month} is open. Anything dated in it can be posted now.`);
      setOpening(false);
      setMonth("");
      load();
    } catch (e) {
      toast.error(errorText(e, "That period could not be opened."));
    }
  }

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

  /** The VAT return, as a document a revenue officer would accept.
   *
   *  This one may be read by ZIMRA. A screen print of a modal — with the
   *  backdrop, the Close button and the browser's own header on it — is not a
   *  return; it is a photograph of a computer. The basis is stated on the face
   *  of it, because a pharmacy has two VAT figures (this one from the posted
   *  accounts, and Analytics' from till sales) and filing the wrong one is a
   *  correction letter.
   */
  async function printVat() {
    if (!vat) return;
    const head = await letterhead();
    printDocument(head, {
      kind: `VAT return: ${vat.period_name}`,
      meta: [
        { label: "From", value: fmtDate(vat.from) },
        { label: "To", value: fmtDate(vat.to) },
        { label: "Rate", value: `${(vat.vat_rate * 100).toFixed(0)}%` },
        { label: vat.direction, value: money(Math.abs(vat.payable)), strong: true },
      ],
      columns: [
        { key: "item", label: "" },
        { key: "amount", label: "Amount", numeric: true, width: "36mm" },
      ],
      rows: [
        { item: "Turnover excluding VAT", amount: money(vat.turnover_excluding_vat) },
        { item: "Output tax. Charged on sales", amount: money(vat.output_tax) },
        { item: "Input tax. Paid on purchases", amount: money(vat.input_tax) },
      ],
      totals: { item: vat.direction, amount: money(Math.abs(vat.payable)) },
      note: [
        "Prepared from the posted income accounts, so it ties to the ledger "
        + "rather than to the till.",
        vat.warning,
      ].filter(Boolean).join(" "),
    });
  }

  return (
    <div className="page">
      <PageHead
        primary={
          <button className="btn primary" onClick={() => setOpening(true)}>
            Open a month
          </button>
        }
        title="Trading periods" sub={current
              ? `Currently trading in ${current.name}. ${current.live?.transactions ?? 0} transactions, ${money(current.live?.sales)}.`
              : ""} />

      <div className="dt-scroll">
        <Refreshable
          loading={loading}
          hasData={periods.length > 0}
          skeleton={<TableSkeleton cols={7} rows={5}
            headers={["Period", "Runs", "Status", "Sales", "Transactions",
                      "Closed by", ""]} />}
        >
        {/* No forced width. `dt-wider` pinned this to 78rem, which is wider than
            the content area on a 1440 screen, so the table scrolled sideways and
            the actions were the part off the edge. It needed that width for a
            two line sentence under every status badge; without it the seven
            columns fit. */}
        <table className="dt">
          <thead>
            <tr>
              <Th className="pe-code">Period</Th>
              <Th className="col-range">Runs</Th>
              <Th>Status</Th>
              {/* This said "Signed off at" over a column of money. When the
                  timestamp moved under "Closed by" — where the person and the
                  moment belong together — its heading stayed behind and the
                  sales figure inherited it. A right-aligned column of dollars
                  under a heading about a date is the exact opposite of a
                  table you can read at a glance. */}
              <Th className="num">Sales</Th>
              <Th className="num">Transactions</Th>
              <Th>Closed by</Th>
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
                  {fmtDate(p.start_date)} to {fmtDate(p.end_date)}
                </td>
                <td>
                  {/* "closed" used to fall through to an empty tone and
                      render grey-on-grey, which on the row that says the books
                      are shut is the one status worth seeing. */}
                  {/* THE BADGE, AND THE SENTENCE ON THE HOVER.
                      Two lines of explanation under every badge made each row
                      twice as tall and took the width that the actions on the
                      right needed, so "Close the period" and "VAT return" were
                      pushed off the screen entirely: the table explained the
                      status and hid the controls for changing it. The sentence
                      is the same on every row of a given status, which is what
                      makes it a legend rather than data. */}
                  <span className={`badge ${p.status === "open" ? "ok"
                    : p.status === "locked" ? "warn" : "muted"}`}
                        title={STATUS_HINT[p.status]}>
                    {sentence(p.status)}
                  </span>
                  {p.drift_warning && (
                    <div className="alert error small">{p.drift_warning}</div>
                  )}
                </td>
                <td className="num">
                  {p.status === "open" ? (
                    <span className="muted">None</span>
                  ) : (
                    money(p.closing_sales)
                  )}
                </td>
                <td className="num">
                  {p.status === "open" ? (
                    <span className="muted">None</span>
                  ) : (
                    p.closing_transactions
                  )}
                </td>
                <td>
                  {p.closed_by || <span className="muted">None</span>}
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
          
              {periods.length === 0 && (
                <EmptyRow cols={7} title="No trading period has been opened">
                  A period is the stretch of trading that gets signed off and locked. Until one is opened, nothing can be closed off.
                </EmptyRow>
              )}
            </tbody>
        </table>
        </Refreshable>
      </div>

      {opening && (
        <div className="modal-backdrop" onClick={() => setOpening(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Open a month</h2>
            <p className="muted">
              A pharmacy that moved to this system part way through a year
              needs its earlier months to exist, so the figures from before
              have somewhere to live. Opening one creates it if it has never
              existed and reopens it if it was closed.
            </p>
            <label className="field">
              Which month
              <input type="month" value={month}
                     onChange={(e) => setMonth(e.target.value)} />
              <span className="field-hint">
                The month itself, not a date in it. Trading is signed off a
                month at a time.
              </span>
            </label>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setOpening(false)}>
                Not now
              </button>
              <BusyButton className="btn primary" onClick={openMonth}
                          disabled={!month} busyLabel="Opening it…">
                Open it
              </BusyButton>
            </div>
          </div>
        </div>
      )}

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
                from till sales. The two legitimately differ when something has
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
                  <td>Output tax <span className="muted">Charged on sales</span></td>
                  <td className="num mono">{money(vat.output_tax)}</td>
                </tr>
                <tr>
                  <td>Input tax <span className="muted">Paid on purchases</span></td>
                  <td className="num mono">{money(vat.input_tax)}</td>
                </tr>
                <tr>
                  <td><b>{vat.direction}</b></td>
                  <td className="num mono"><b>{money(Math.abs(vat.payable))}</b></td>
                </tr>
              </tbody>
            </table>

            <div className="modal-actions">
              <IconButton action="print" onClick={printVat} />
              <button className="btn primary" onClick={() => setVat(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
