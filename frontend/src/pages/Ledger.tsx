/** The general ledger — trial balance, journal, and subledger reconciliation.
 *
 *  Every figure here is a link to what produced it. A trial balance line that
 *  cannot be opened is exactly the point where "follow your data" breaks for
 *  the person who needs it most: an accountant looking at a number that seems
 *  wrong wants the entries behind it, not a filter they have to build by hand.
 */
import { useEffect, useState } from "react";
import { api, fmtDate, money, prefetchRoute, errorText  } from "../api";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import Statements from "../components/Statements";
import CashFlow from "../components/CashFlow";
import AgedAnalysis from "../components/AgedAnalysis";
import RowLink, { RowActions } from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import ExpiryProvision from "../components/ExpiryProvision";
import Pagination, { Paged } from "../components/Pagination";
import { useClientPage } from "../hooks/useClientPage";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";

interface TbLine {
  code: string; name: string; type: string; subledger: string;
  debit: number; credit: number; balance: number;
}
interface TrialBalance {
  lines: TbLine[]; total_debit: number; total_credit: number;
  difference: number; balanced: boolean; message: string;
}
interface Entry {
  id: number; reference: string; period_code: string; entry_date: string;
  description: string; source: string; source_id: number | null;
  status: string; total: number;
}
interface Recon {
  subledger: string; control_balance: number; subledger_total: number;
  difference: number; reconciled: boolean; unattributed_lines: number;
  message: string;
  parties: { party_type: string; party_id: number | null; balance: number }[];
}
interface Unposted {
  count: number; message: string;
  sales: { sale_id: number; sale_number: string; total: number }[];
}
interface UnpostedReceipts {
  count: number; message: string;
  orders: { order_id: number; order_number: string; supplier: string;
            value: number; received_at: string | null }[];
}
interface BankRecon {
  account_code: string; account_name: string; from: string; to: string;
  statement_lines: number; statement_total: number; matched_count: number;
  matched_total: number; ledger_balance: number;
  unreconciled_difference: number; reconciled: boolean; message: string;
  matched: { line_number: number; date: string; description: string;
             amount: number; matched_by: string; entry_id: number;
             entry_reference: string }[];
  on_statement_only: { line_number: number; date: string; description: string;
                       amount: number; reference: string; suggestion: string }[];
  in_ledger_only: { entry_id: number; entry_reference: string;
                    entry_date: string; description: string; amount: number }[];
}

type Tab = "trial" | "income" | "balance" | "cash" | "ageing" | "journal" | "recon" | "bank" | "unposted" | "provision";

export default function Ledger() {
  const [tb, setTb] = useState<TrialBalance | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [jMeta, setJMeta] = useState<Paged<Entry> | null>(null);
  const [jPage, setJPage] = useState(1);
  const [jSize, setJSize] = useState(50);
  const [recon, setRecon] = useState<Record<string, Recon>>({});
  const [unposted, setUnposted] = useState<Unposted | null>(null);
  /* The count and the total beside this table are computed over the whole set by
     the endpoint, never over the visible page. A footer that quietly totals one
     page is the most misleading thing a ledger screen can do. */
  const unpostedPage = useClientPage(unposted?.sales ?? [], 25);
  const [receipts, setReceipts] = useState<UnpostedReceipts | null>(null);
  const receiptPage = useClientPage(receipts?.orders ?? [], 25);
  const [statement, setStatement] = useState("");
  const [bank, setBank] = useState<BankRecon | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "trial", label: "Trial balance", count: tb?.lines.length },
    { key: "income", label: "Income statement",
      hint: "Revenue, cost of sales and profit for the financial year" },
    { key: "balance", label: "Balance sheet",
      hint: "What the pharmacy owns and owes at a date" },
    { key: "cash", label: "Cash flow",
      hint: "Why the bank balance moved, which profit alone never explains" },
    { key: "ageing", label: "Aged analysis",
      hint: "How old the money owed is, and who is sitting on it" },
    { key: "journal", label: "Journal", count: entries.length },
    { key: "recon", label: "Reconciliation" },
    // Beside the statements, because it is the entry that makes the balance
    // sheet honest rather than a stock report that happens to mention money.
    { key: "provision", label: "Expiry provision" },
    { key: "bank", label: "Bank statement",
      hint: "What the bank says against what the ledger says" },
    { key: "unposted", label: "Not posted",
      count: (unposted?.count ?? 0) + (receipts?.count ?? 0),
      hint: "Sales and deliveries the ledger has not caught up with" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "trial");

  function load() {
    setLoading(true);
    api.get<TrialBalance>("/api/ledger/trial-balance").then(setTb)
      .catch((e) => toast.error(errorText(e))).finally(() => setLoading(false));
    api
      .get<Paged<Entry>>(`/api/ledger/entries/paged?page=${jPage}&per_page=${jSize}`)
      .then((r) => {
        setEntries(r.items);
        setJMeta(r);
        if (r.page !== jPage) setJPage(r.page);
      })
      .catch((e) => toast.error(errorText(e)));
    api.get<Unposted>("/api/ledger/unposted").then(setUnposted).catch(() => undefined);
    // The purchase-side twin. Its own docstring says the two together answer
    // "is the ledger a complete picture of the business" — this screen was
    // asking only the sales half, so a manager reading "nothing outstanding"
    // was reading half a sentence.
    api.get<UnpostedReceipts>("/api/ledger/unposted-receipts")
      .then(setReceipts).catch(() => undefined);
    for (const name of ["debtors", "creditors", "stock", "vat"]) {
      api.get<Recon>(`/api/ledger/subledgers/${name}/reconcile`)
        .then((r) => setRecon((all) => ({ ...all, [name]: r })))
        .catch(() => undefined);
    }
  }
  useEffect(load, [jPage, jSize]);

  async function postReceipt(orderId: number) {
    const res = await api
      .post<{ posted: boolean; reason?: string; reference?: string }>(
        `/api/ledger/post-receipt/${orderId}`)
      .catch((e) => { toast.error(errorText(e)); return null; });
    if (!res) return;
    if (res.posted) toast.ok(`Posted as ${res.reference}.`);
    else toast.warn(res.reason || "Not posted.");
    load();
  }

  async function reconcileBank() {
    try {
      setBank(await api.post<BankRecon>("/api/ledger/bank-reconciliation", {
        account_code: "1010", content: statement,
      }));
    } catch (e) {
      toast.error(errorText(e, "That statement could not be read."));
    }
  }

  async function postSale(saleId: number) {
    const res = await api
      .post<{ posted: boolean; reason?: string; reference?: string }>(
        `/api/ledger/post-sale/${saleId}`)
      .catch((e) => { toast.error(errorText(e)); return null; });
    if (!res) return;
    if (res.posted) toast.ok(`Posted as ${res.reference}.`);
    else toast.warn(res.reason || "Not posted.");
    load();
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>General ledger</h1>
          <p className="muted">
            {tb
              ? tb.balanced
                ? `Balanced. ${money(tb.total_debit)} debits against ${money(tb.total_credit)} credits.`
                : tb.message
              : ""}
          </p>
        </div>
      </header>

      {tb && !tb.balanced && <div className="alert error">{tb.message}</div>}
      {unposted?.count ? <div className="alert warn">{unposted.message}</div> : null}

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "income" && <Statements kind="income" />}
      {tab === "balance" && <Statements kind="balance" />}
      {tab === "cash" && <CashFlow />}
      {tab === "ageing" && <AgedAnalysis />}

      {tab === "trial" && (
        <Refreshable
          loading={loading}
          hasData={!!tb?.lines.length}
          skeleton={<TableSkeleton cols={6} rows={8}
            widths={["6ch", "22ch", "10ch", "10ch", "10ch", "10ch"]} />}
        >
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th>Code</th><th>Account</th><th>Type</th>
                  <th className="num">Debit</th><th className="num">Credit</th>
                  <th className="num">Balance</th>
                </tr>
              </thead>
              <tbody>
                {tb?.lines.map((l) => (
                  <RowLink key={l.code} to={`/ledger/accounts/${l.code}`}>
                    <td className="mono">{l.code}</td>
                    <td>
                      {l.name}
                      {l.subledger && <span className="badge">{l.subledger}</span>}
                    </td>
                    <td className="muted">{l.type}</td>
                    <td className="num">{l.debit ? money(l.debit) : "—"}</td>
                    <td className="num">{l.credit ? money(l.credit) : "—"}</td>
                    <td className="num">{money(l.balance)}</td>
                  </RowLink>
                ))}
                {tb && (
                  <tr className="total-row">
                    <td colSpan={3}>Totals</td>
                    <td className="num">{money(tb.total_debit)}</td>
                    <td className="num">{money(tb.total_credit)}</td>
                    <td className="num">{tb.balanced ? "—" : money(tb.difference)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Refreshable>
      )}

      {tab === "journal" && (
        <Refreshable
          loading={loading}
          hasData={entries.length > 0}
          skeleton={<TableSkeleton cols={6} rows={8} />}
        >
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th>Reference</th><th>Date</th><th>Period</th>
                  <th>Description</th><th>Source</th><th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <RowLink key={e.id} to={`/ledger/entries/${e.id}`} prefetch={prefetchRoute}
                    className={e.status === "reversed" ? "row-flag" : ""}>
                    <td className="mono">{e.reference}</td>
                    <td>{fmtDate(e.entry_date)}</td>
                    <td className="mono">{e.period_code}</td>
                    <td>
                      {e.description}
                      {e.status === "reversed" && <span className="badge warn">reversed</span>}
                    </td>
                    <td className="muted">{e.source}</td>
                    <td className="num">{money(e.total)}</td>
                  </RowLink>
                ))}
              </tbody>
            </table>
          </div>
          {jMeta && (
            <Pagination
              meta={jMeta}
              noun="journal entries"
              onPage={setJPage}
              onPerPage={(n) => { setJSize(n); setJPage(1); }}
            />
          )}
        </Refreshable>
      )}

      {tab === "recon" && (
        <div className="recon-grid">
          {Object.entries(recon).map(([name, r]) => (
            <div key={name} className={`card ${r.reconciled ? "" : "card-flag"}`}>
              <h3>{name}</h3>
              <p className={r.reconciled ? "muted" : "alert error small"}>{r.message}</p>
              <dl className="kv">
                <dt>Control account</dt><dd className="num">{money(r.control_balance)}</dd>
                <dt>Subledger</dt><dd className="num">{money(r.subledger_total)}</dd>
                <dt>Difference</dt><dd className="num">{money(r.difference)}</dd>
                {!!r.unattributed_lines && (
                  <>
                    <dt>Unattributed</dt>
                    <dd className="num">{money(r.unattributed_lines)}</dd>
                  </>
                )}
              </dl>
            </div>
          ))}
        </div>
      )}

      {tab === "provision" && (
        <div className="card">
          <div className="card-head">
            <h3>Provision against short-dated stock</h3>
          </div>
          <ExpiryProvision />
        </div>
      )}

      {tab === "unposted" && (
        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr><th>Sale</th><th className="num">Total</th><th className="actions" /></tr>
            </thead>
            <tbody>
              {/* Paged in the browser, because the endpoint deliberately returns
                  the whole set: the figure beside this table is the total value
                  waiting to be posted, and that has to be summed over all of it.
                  What was wrong was rendering all of it — two hundred rows with
                  no way to move through them. */}
              {unpostedPage.items.map((s) => (
                <tr key={s.sale_id}>
                  <td className="mono"><EntityLink kind="sale" id={s.sale_id}>{s.sale_number}</EntityLink></td>
                  <td className="num">{money(s.total)}</td>
                  <RowActions>
                    <BusyButton className="btn sm" onClick={() => postSale(s.sale_id)}>
                      Post
                    </BusyButton>
                  </RowActions>
                </tr>
              ))}
              {!unposted?.count && (
                <tr><td colSpan={3} className="muted pad">
                  Every settled sale has reached the ledger.
                </td></tr>
              )}
            </tbody>
          </table>
          <Pagination meta={unpostedPage.meta} onPage={unpostedPage.setPage} />

          {/* The other half. A ledger missing its purchases overstates profit
              exactly as much as one missing its sales understates it, and this
              screen used to report only the second. */}
          <h3 style={{ marginTop: 22 }}>Deliveries not posted</h3>
          <table className="dt">
            <thead>
              <tr>
                <th>Order</th><th>Supplier</th><th>Received</th>
                <th className="num">Value</th><th className="actions" />
              </tr>
            </thead>
            <tbody>
              {receiptPage.items.map((o) => (
                <tr key={o.order_id}>
                  <td className="mono">
                    <EntityLink kind="order" id={o.order_id}>{o.order_number}</EntityLink>
                  </td>
                  <td>{o.supplier}</td>
                  <td>{o.received_at ? fmtDate(o.received_at) : "—"}</td>
                  <td className="num">{money(o.value)}</td>
                  <RowActions>
                    <BusyButton className="btn sm" onClick={() => postReceipt(o.order_id)}>
                      Post
                    </BusyButton>
                  </RowActions>
                </tr>
              ))}
              {!receipts?.count && (
                <tr><td colSpan={5} className="muted pad">
                  Every delivery has reached the ledger.
                </td></tr>
              )}
            </tbody>
          </table>
          <Pagination meta={receiptPage.meta} onPage={receiptPage.setPage} />
        </div>
      )}

      {tab === "bank" && (
        <>
          <div className="card">
            <div className="card-head">
              <h3>Reconcile the bank</h3>
              <span className="muted small">
                Nothing is posted. This produces a list of things to chase.
              </span>
            </div>
            <p className="muted">
              Paste the statement your bank exported, or open the file. Money in
              and out may be two columns or one signed one &mdash; both are read,
              because asking a pharmacy to reformat a file their own bank
              generated is not a reconciliation procedure.
            </p>
            <div className="field">
              <label>Statement file</label>
              <input type="file" accept=".csv,text/csv,text/plain"
                     onChange={(e) => {
                       const file = e.target.files?.[0];
                       if (!file) return;
                       file.text().then(setStatement);
                     }} />
            </div>
            <div className="field">
              <label>Or paste it</label>
              <textarea rows={6} className="mono" value={statement}
                        onChange={(e) => setStatement(e.target.value)}
                        placeholder="date,description,reference,amount" />
            </div>
            <div className="modal-actions">
              <BusyButton disabled={statement.trim().length < 10}
                          onClick={reconcileBank}>
                Reconcile it
              </BusyButton>
            </div>
          </div>

          {bank && (
            <>
              <div className={`alert ${bank.reconciled ? "ok" : "warn"}`}>
                {bank.message}
              </div>
              <div className="wc-bands">
                <div className="wl-stat">
                  <b>{money(bank.statement_total)}</b><span>on the statement</span>
                </div>
                <div className="wl-stat">
                  <b>{money(bank.ledger_balance)}</b><span>in the ledger</span>
                </div>
                <div className="wl-stat">
                  <b>{bank.matched_count}/{bank.statement_lines}</b><span>lines tied up</span>
                </div>
                <div className={`wl-stat${Math.abs(bank.unreconciled_difference) > 0.005 ? " wc-stale" : ""}`}>
                  <b>{money(bank.unreconciled_difference)}</b><span>unreconciled</span>
                </div>
              </div>

              {/* The two lists are the whole point. Anything the bank knows
                  about and the ledger does not is money that moved without
                  being recorded; anything the ledger knows and the bank does
                  not has not cleared, or never will. */}
              <div className="card">
                <div className="card-head">
                  <h3>On the statement, not in the ledger</h3>
                  <span className="muted small">
                    {bank.on_statement_only.length} to account for
                  </span>
                </div>
                {bank.on_statement_only.length === 0 ? (
                  <div className="empty">
                    Every line on the statement is accounted for.
                  </div>
                ) : (
                  <table className="dt">
                    <thead>
                      <tr>
                        <th>Date</th><th>What the bank calls it</th>
                        <th className="num">Amount</th><th>Likely</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bank.on_statement_only.map((l) => (
                        <tr key={l.line_number}>
                          <td>{l.date ? fmtDate(l.date) : "—"}</td>
                          <td>
                            {l.description}
                            {l.reference && (
                              <div className="muted small mono">{l.reference}</div>
                            )}
                          </td>
                          <td className="num">{money(l.amount)}</td>
                          <td className="muted small wrap">{l.suggestion}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div className="card">
                <div className="card-head">
                  <h3>In the ledger, not on the statement</h3>
                  <span className="muted small">
                    {bank.in_ledger_only.length} not cleared
                  </span>
                </div>
                {bank.in_ledger_only.length === 0 ? (
                  <div className="empty">Nothing is outstanding.</div>
                ) : (
                  <table className="dt">
                    <thead>
                      <tr>
                        <th>Entry</th><th>Dated</th><th>Description</th>
                        <th className="num">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bank.in_ledger_only.map((l) => (
                        <tr key={l.entry_id}>
                          <td className="mono">{l.entry_reference}</td>
                          <td>{fmtDate(l.entry_date)}</td>
                          <td>{l.description}</td>
                          <td className="num">{money(l.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {bank.matched_count > 0 && (
                <div className="card">
                  <h3>Tied up</h3>
                  <table className="dt">
                    <thead>
                      <tr>
                        <th>Date</th><th>Description</th><th className="num">Amount</th>
                        <th>Entry</th><th>Matched on</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bank.matched.map((m) => (
                        <tr key={m.line_number}>
                          <td>{m.date ? fmtDate(m.date) : "—"}</td>
                          <td>{m.description}</td>
                          <td className="num">{money(m.amount)}</td>
                          <td className="mono small">{m.entry_reference}</td>
                          <td>
                            {/* Which rule made the match. A reference is
                                evidence; an amount that happens to agree on a
                                nearby date is a guess, and the difference
                                matters to whoever is checking one. */}
                            <span className={`badge ${m.matched_by === "reference" ? "ok" : "warn"}`}>
                              {m.matched_by === "reference"
                                ? "reference" : "amount and date"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
