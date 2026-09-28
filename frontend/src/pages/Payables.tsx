/** Supplier invoices: what was billed, what arrived, and what is still owed.
 *
 *  The ledger raised a creditor when goods were received, using the costs off
 *  the purchase order. That is an estimate, not a bill. Nothing here had ever
 *  read the invoice the wholesaler actually sent, so a price rise between
 *  ordering and delivery disappeared, being billed for more than arrived was
 *  invisible, and — because nothing anywhere debited trade creditors — the
 *  account only ever grew.
 *
 *  The screen leads with what is owed and what is late, because that is the
 *  question an owner opens it to answer. The match sits behind an invoice,
 *  where it is read at the moment somebody is deciding whether to pay.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Select from "../components/Select";
import { ArrowClockwise, CheckCircle, Printer, Question, Receipt, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money, prefetchRoute } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import BusyButton from "../components/BusyButton";
import RowLink, { RowActions } from "../components/RowLink";
import { useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";
import { EntityLink, TableSearch, useSearch } from "../components/Filters";
import PaySupplier from "../components/PaySupplier";
import Remittance, { RemittanceData } from "../components/Remittance";
import { Block, Figure, GhostRows } from "../components/Skeleton";
import PageHead from "../components/PageHead";
import ExportButton from "../components/ExportButton";
import RecordTheBill, { AwaitingBill } from "../components/RecordTheBill";
import Th from "../components/Th";

interface AgeInvoice {
  invoice_id: number; invoice_number: string; invoice_date: string;
  due_date: string; total: number; outstanding: number;
  days_overdue: number; status: string; band: string;
}
interface AgeSupplier {
  supplier_id: number; supplier: string; bands: Record<string, number>;
  total: number; oldest_days: number; queried: number; invoices: AgeInvoice[];
}
interface Ageing {
  as_at: string; bands: string[]; totals: Record<string, number>;
  total: number; queried: number; suppliers: AgeSupplier[];
  control_balance: number; difference: number; awaiting_approval: number;
}
interface MatchLine {
  description: string; billed_quantity: number; received_quantity: number;
  billed_unit_cost: number; ordered_unit_cost: number; line_total: number;
  issues: string[];
}
interface MatchResult {
  depth: "lines" | "totals" | "none"; matched: boolean; order_number?: string;
  ordered: number; received: number; billed: number; variance: number;
  lines: MatchLine[]; problems: string[];
}
interface Invoice {
  id: number; invoice_number: string; supplier: string; supplier_id: number;
  order_number: string; invoice_date: string; due_date: string | null;
  total: number; status: string; query_note: string; posted_reference: string;
  paid: number; outstanding: number; match?: MatchResult;
}
interface Uninvoiced {
  order_id: number; order_number: string; supplier: string; supplier_id: number;
  received_at: string | null; value: number; days: number | null;
}

/** How many ageing columns to hold open while their names are on their way.
 *  The bands are the server's (`AGE_BANDS` in payables.py) and there are five
 *  of them; only the count is needed here, and only so the table does not
 *  widen under the reader when they land. */
const BAND_SLOTS = [0, 1, 2, 3, 4];

const DEPTH_SAYS: Record<string, string> = {
  lines: "Matched line by line against what was received.",
  totals: "Only the total was keyed, so this compares totals. A short delivery and an overcharge of the same size would cancel out and pass.",
  none: "No order is linked, so there is nothing to check this against.",
};

export default function Payables() {
  const navigate = useNavigate();
  const [ageing, setAgeing] = useState<Ageing | null>(null);
  /* OPEN INVOICES, FLATTENED SO THE SEARCH CAN REACH THEM.
     The table is grouped by supplier, so an invoice number lives one level
     down and a plain filter on `suppliers` would have searched the group
     headings only. "Find an invoice" above this is a lookup that builds its
     own separate result list; this narrows the table a pharmacy actually
     pays from. */
  const openInvoices = useMemo(
    () => (ageing?.suppliers ?? []).flatMap((s) =>
      s.invoices.map((i) => ({ ...i, supplier: s.supplier,
                               supplier_id: s.supplier_id }))),
    [ageing]);
  const { q, setQ, shown } = useSearch(openInvoices, (i) =>
    [i.invoice_number, i.supplier]);
  /* Null until the ledger has answered. An empty list is "every delivery has
     been billed", which is a finding this screen states in so many words, and
     it may not state it before it has asked. */
  const [waiting, setWaiting] = useState<Uninvoiced[] | null>(null);
  const [open, setOpen] = useState<Invoice | null>(null);
  const [querying, setQuerying] = useState(false);
  const [find, setFind] = useState("");
  const [hits, setHits] = useState<Invoice[] | null>(null);
  const [queryNote, setQueryNote] = useState("");
  const [failed, setFailed] = useState("");
  const [paying, setPaying] = useState<AgeSupplier | null>(null);
  const [billing, setBilling] = useState<AwaitingBill | null>(null);
  /* Likewise: "no payment has been recorded" is one of the worst things this
     page can say about a pharmacy, and it is not something to say while the
     request is still out. */
  const [payments, setPayments] = useState<RemittanceData[] | null>(null);
  const [advice, setAdvice] = useState<RemittanceData | null>(null);
  const [spinning, setSpinning] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(async () => {
    setSpinning(true);
    try {
      const [aged, un, paid] = await Promise.all([
        api.get<Ageing>("/api/payables/ageing"),
        api.get<{ items: Uninvoiced[] }>("/api/payables/uninvoiced"),
        api.get<{ items: RemittanceData[] }>("/api/payables/payments?limit=25"),
      ]);
      setAgeing(aged);
      setWaiting(un.items);
      setPayments(paid.items ?? []);
      setFailed("");
    } catch (e) {
      setFailed(errorText(e, "What is owed could not be worked out."));
    } finally {
      // Held briefly so the turn is visible. A spinner that stops on the same
      // frame it started reads as a button that did nothing.
      window.setTimeout(() => setSpinning(false), 450);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function show(invoiceId: number) {
    try {
      setOpen(await api.get<Invoice>(`/api/payables/invoices/${invoiceId}`));
    } catch (e) {
      // `show()` is a read. Nothing was being saved, so saying nothing was
      // saved answers a question nobody asked.
      toast.error(errorText(e, "That invoice could not be opened."));
    }
  }

  async function approve() {
    if (!open) return;
    const m = open.match;
    const ok = await confirm({
      title: "Approve for payment?",
      body: (
        <>
          {m && !m.matched
            ? <>This invoice did not match cleanly. Approving it accepts
                the difference of <b>{money(m.variance)}</b> as correct.</>
            : <>This brings the creditor to what the supplier billed.</>}
          {" "}Only the difference against the goods receipt is posted, so
          approving twice does nothing.
        </>
      ),
      confirmLabel: "Approve it",
    });
    if (!ok) return;
    try {
      const r = await api.post<Invoice & { message: string }>(
        `/api/payables/invoices/${open.id}/approve`, {});
      toast.ok(r.message);
      await show(open.id);
      await load();
    } catch (e) {
      toast.error(errorText(e, "That could not be approved. Nothing was saved."));
    }
  }

  /** Find one invoice, across every supplier.
   *
   *  The ageing lists what is still owed and the supplier record lists that
   *  supplier's bills. Neither answers the question a wholesaler asks on the
   *  telephone, "what happened to 44001?", because a settled invoice is on
   *  neither. The endpoint has taken a search term since it was written and no
   *  screen sent one, so the answer was to guess which supplier it belonged to
   *  and read down their list.
   */
  useEffect(() => {
    const term = find.trim();
    if (term.length < 2) { setHits(null); return; }
    const t = window.setTimeout(() => {
      api.get<{ items: Invoice[] }>(
        `/api/payables/invoices?q=${encodeURIComponent(term)}&limit=25`)
        .then((r) => setHits(r.items))
        /* An empty result means "no invoice by that number", which on this
           box is a real and useful answer — and exactly the wrong one to give
           for a search that never ran. The supplier is usually on the
           telephone while somebody types here. */
        .catch((e) => {
          setHits([]);
          toast.error(errorText(e, "That search could not be run, so this is "
            + "not an answer about the invoice."));
        });
    }, 250);
    return () => window.clearTimeout(t);
  }, [find]);

  /** Dispute an invoice with the supplier.
   *
   *  The match exists to catch being billed for twelve when ten arrived, or at
   *  a price that rose after the order was placed. It caught those and then
   *  offered exactly one button: Approve. A pharmacist who found a discrepancy
   *  could accept it or leave the screen, which in practice means accepting it
   *  a week later, because the invoice has to be paid.
   *
   *  A queried invoice still ages and still counts as owed. This is not a way
   *  of hiding a bill; it is a note that somebody has telephoned, so the next
   *  person to look does not start the same conversation again.
   */
  async function raiseQuery() {
    if (!open || !queryNote.trim()) return;
    try {
      // Closed before the write, not after it. A record being created
      // or edited costs a click if it fails, and the list is what
      // confirms it either way.
      setQuerying(false);
      const r = await api.post<{ message: string }>(
        `/api/payables/invoices/${open.id}/query`, { note: queryNote.trim() });
      toast.ok(r.message);
      setQueryNote("");
      await show(open.id);
      await load();
    } catch (e) {
      // The server refuses to query an invoice already paid, and says so.
      toast.error(errorText(e, "That invoice could not be queried. Nothing was saved."));
    }
  }

  /** One creditor's statement, from the row that names them.
   *
   *  This is the month-end job: put ours beside theirs and find the invoice
   *  that never arrived or the payment that was never allocated. Reaching it
   *  from the ageing row is the point — the question "what is behind this two
   *  thousand dollars" is asked while looking at the two thousand dollars.
   */
  async function printStatement(supplierId: number) {
    try {
      const [head, doc] = await Promise.all([
        letterhead(),
        api.get<any>(`/api/payables/suppliers/${supplierId}/statement`),
      ]);
      printDocument(head, {
        kind: "Statement of account",
        to: [doc.supplier, doc.contact, doc.phone, doc.email].filter(Boolean),
        meta: [
          { label: "Account", value: doc.account_code },
          { label: "Date", value: fmtDate(doc.to) },
          { label: "Period from", value: fmtDate(doc.from) },
          { label: "Amount due", value: money(doc.amount_due), strong: true },
        ],
        columns: [
          { key: "date", label: "Date", width: "22mm" },
          { key: "reference", label: "Reference", width: "30mm" },
          { key: "description", label: "Description" },
          { key: "debit", label: "Debit", numeric: true, width: "24mm" },
          { key: "credit", label: "Credit", numeric: true, width: "24mm" },
          { key: "balance", label: "Balance", numeric: true, width: "26mm" },
        ],
        opening: { description: "Balance brought forward",
                   balance: money(doc.brought_forward) },
        rows: doc.lines.map((l: any) => ({
          date: fmtDate(l.date), reference: l.reference,
          description: l.description,
          debit: l.debit == null ? "" : money(l.debit),
          credit: l.credit == null ? "" : money(l.credit),
          balance: money(l.balance),
        })),
        totals: { description: "Closing balance", debit: money(doc.debits),
                  credit: money(doc.credits), balance: money(doc.closing) },
        ageing: [
          ...doc.ageing.map((a: any) => ({ label: a.label, value: money(a.value) })),
          { label: "Amount due", value: money(doc.amount_due), strong: true },
        ],
        note: head.terms
          || "Please quote the account number shown above on every remittance.",
      });
    } catch (e) {
      toast.error(errorText(e, "That statement could not be produced."));
    }
  }

  if (failed) return <div className="alert error">{failed}</div>;

  const late = ageing
    ? Object.entries(ageing.totals)
        .filter(([band]) => band !== "Not yet due")
        .reduce((sum, [, value]) => sum + value, 0)
    : 0;

  return (
    <>
      <PageHead
        title="Creditors"
        sub="What was billed, what arrived, and what is still owed"
        count={<><Figure ready={!!ageing} w="9ch">{ageing && money(ageing.total)}</Figure>{" "}owed</>}
        /* THE WORK THIS PAGE LEADS TO.
           The bar carried Refresh and nothing else, on the screen a pharmacy
           opens to decide who gets paid this week. Everything it could already
           do was buried a row at a time, or on a reports screen somebody had
           to know existed. */
        take={<ExportButton dataset="payables" />}
        also={
          <>
            <Select
              value=""
              placeholder="Reports…"
              onChange={(key) => { if (key) navigate(`/reports?report=${key}`); }}
              options={[
                // The aged analysis is this table as a document, and it is
                // where the spreadsheet comes from: a second export button
                // beside it would be a second set of figures to keep true.
                { value: "aged_analysis", label: "Aged analysis, and the spreadsheet" },
                { value: "creditor_statements", label: "Creditor statements" },
                { value: "purchases_by_supplier", label: "Purchases by supplier" },
                { value: "supplier_performance", label: "Supplier performance" },
                { value: "goods_received_not_invoiced", label: "Delivered and not billed" },
              ]}
            />
            <button className="btn secondary" onClick={load}>
              <ArrowClockwise size={15} className={spinning ? "spin" : ""} />
              Refresh
            </button>
          </>
        }
      />

      {/* SCOPED LOADING.
       *
       * One grey table used to stand for this entire page, so four tile
       * labels, five card headings, four explanatory sentences and every
       * static column head on the screen were withheld until the ageing came
       * back, and then arrived together about nine hundred pixels tall. None
       * of them is fetched.
       *
       * The frame is unconditional now and only the money pulses. The five
       * ageing columns are the exception: the server names them, which is why
       * they are read off `ageing.bands` rather than written here, so they
       * stay ghosted rather than being guessed at. */}
      <div className="wc-bands">
        <div className="wl-stat">
          <b><Figure ready={!!ageing} w="9ch">{ageing && money(ageing.total)}</Figure></b>
          <span>Owed to suppliers</span>
        </div>
        {/* The tone waits on the figure. A band cannot be marked overdue on
            the strength of a nought nobody has counted yet. */}
        <div className={`wl-stat${ageing && late > 0.005 ? " wc-stale" : ""}`}>
          <b><Figure ready={!!ageing} w="9ch">{ageing && money(late)}</Figure></b>
          <span>Past its due date</span>
        </div>
        <div className={`wl-stat${ageing && ageing.queried > 0.005 ? " wc-abandoned" : ""}`}>
          <b><Figure ready={!!ageing} w="9ch">{ageing && money(ageing.queried)}</Figure></b>
          <span>Queried with the supplier</span>
        </div>
        <div className="wl-stat">
          <b>
            <Figure ready={!!waiting} w="9ch">
              {waiting && money(waiting.reduce((s, w) => s + w.value, 0))}
            </Figure>
          </b>
          <span>Received, not yet invoiced</span>
        </div>
      </div>

      {/* The two are kept separately precisely so they can disagree, and
          this is the one check that finds what nothing else can. It names
          the innocent explanation first, because that is usually the true
          one: a delivery raised the creditor at the order's cost and its
          invoice has not been approved yet. Leading with an accusation
          sends somebody hunting a fraud that is really a queue. */}
      {ageing && Math.abs(ageing.difference) > 0.005 && (
        <div className="alert warn">
          <Warning size={16} weight="fill" />
          <span>
            The ledger says {money(ageing.control_balance)} is owed; these
            invoices come to {money(ageing.total)}, a difference of{" "}
            <b>{money(ageing.difference)}</b>.{" "}
            {ageing.awaiting_approval > 0.005
              ? <>{money(ageing.awaiting_approval)} of that is invoices
                  recorded but not yet approved, which accounts for most or all
                  of it. Approve them and the two should meet.</>
              : <>Nothing is waiting for approval, so this is stock received
                  and posted with no invoice recorded against it.</>}
          </span>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h3>What is owed, by age</h3>
          <span className="muted small">
            Aged on the due date, not the invoice date. Columns are days
          </span>
        </div>
        {ageing && ageing.suppliers.length === 0 ? (
          <div className="empty">
            <b>Nothing is owed to any supplier.</b>
            <p>
              Every invoice recorded has been paid and allocated. Goods
              received that no invoice has arrived for are listed below;
              those are a debt that has not been billed yet.
            </p>
          </div>
        ) : (
          /* A supplier name needs 294px and eight equal columns gave
             it 107, so whoever is owed the money was the one thing cut
             off. It scrolls in its card instead, with the floor
             declared rather than taken from whichever row sorts
             first. */
          <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr>
                <Th className="pay-supplier">Supplier</Th>
                {/* No Total column. It is the five bands added up, the
                    tile above already states the grand total, and it was
                    the column that pushed the Pay button off the right
                    edge: an arithmetic convenience was costing the control
                    somebody opens this page to press. The row's own total
                    rides with the supplier, where the eye already is. */}
                {/* "1 to 30 days" in a 90px column reads "1 TO 30 DA...".
                    The word "days" is on all five and is said once, in the
                    card's own subtitle, so the columns carry the numbers
                    that differ. */}
                {ageing
                  ? ageing.bands.map((b) => (
                    <th key={b} className="num" title={b}>
                      {b.replace(/ days$/, "").replace(/^Not yet due$/, "Not due")}
                    </th>
                  ))
                  /* Held open and unnamed. Where a band starts and stops is
                     the server's rule, not this file's, so writing "31 to 60"
                     here would be a second copy of it that can drift. */
                  : BAND_SLOTS.map((i) => (
                    <th key={i} className="num"><Block w="7ch" h={12} /></th>
                  ))}
                <th className="actions" />
              </tr>
            </thead>
            {!ageing ? (
              <GhostRows cols={7} rows={6} rowHeight={58} secondLine={[0]}
                         widths={["24ch", "8ch", "8ch", "8ch", "8ch", "8ch", "10ch"]} />
            ) : (
            <tbody>
              {ageing.suppliers.map((s) => (
                // The ageing row is about one supplier, so the row opens
                // that supplier. The name was already a link; the other five
                // columns were dead space in a table people read across.
                <RowLink key={s.supplier_id} to={`/suppliers/${s.supplier_id}`}
                         prefetch={prefetchRoute}>
                  <td className="pay-name" title={s.supplier}>
                    <EntityLink kind="supplier" id={s.supplier_id}>
                      <b>{s.supplier}</b>
                    </EntityLink>
                    <div className="muted small">
                      {money(s.total)} owed
                      {s.oldest_days > 0
                        && `, oldest ${s.oldest_days} day${s.oldest_days === 1 ? "" : "s"} past due`}
                    </div>
                  </td>
                  {ageing.bands.map((b) => (
                    <td key={b} className="num">
                      {s.bands[b] ? money(s.bands[b]) : <span className="muted">None</span>}
                    </td>
                  ))}
                  <td className="actions">
                    {/* Inside a RowLink, so the click has to be stopped or
                        paying a supplier navigates away from the form. */}
                    <button className="btn small ghost" title="Statement of account"
                            onClick={(e) => {
                              e.preventDefault(); e.stopPropagation();
                              printStatement(s.supplier_id);
                            }}>
                      <Printer size={14} />
                    </button>
                    <button className="btn small"
                            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setPaying(s); }}>
                      Pay
                    </button>
                  </td>
                </RowLink>
              ))}
            </tbody>
            )}
          </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Find an invoice</h3>
          <span className="muted small">
            By number or by note, across every supplier. Settled ones too
          </span>
        </div>
        <input
          className="page-search"
          value={find}
          onChange={(e) => setFind(e.target.value)}
          placeholder="Invoice number, or a word from its note"
        />
        {hits !== null && (
          hits.length === 0 ? (
            <div className="empty">
              <b>Nothing matches &ldquo;{find.trim()}&rdquo;</b>
              <p>
                An invoice that has never been recorded will not be here.
                Goods received with no bill against them are listed further
                down.
              </p>
            </div>
          ) : (
            <table className="dt">
              <thead>
                <tr>
                  <Th>Invoice</Th><Th className="pay-supplier">Supplier</Th><Th>Dated</Th>
                  <Th>Status</Th>
                  <Th className="num">Total</Th>
                  <Th className="num">Outstanding</Th>
                  <th className="actions" />
                </tr>
              </thead>
              <tbody>
                {hits.map((i) => (
                  <tr key={i.id}>
                    <td className="mono">
                      <EntityLink kind="invoice" id={i.id}>
                        {i.invoice_number}
                      </EntityLink>
                    </td>
                    <td>
                      <EntityLink kind="supplier" id={i.supplier_id}>
                        {i.supplier}
                      </EntityLink>
                    </td>
                    <td>{fmtDate(i.invoice_date)}</td>
                    <td>
                      <span className={`badge ${i.status === "queried" ? "warn"
                        : i.status === "paid" ? "ok" : "muted"}`}>
                        {i.status}
                      </span>
                    </td>
                    <td className="num">{money(i.total)}</td>
                    <td className="num">
                      {i.outstanding > 0.005
                        ? money(i.outstanding)
                        : <span className="muted">Settled</span>}
                    </td>
                    <td className="actions">
                      <button className="btn small" onClick={() => show(i.id)}>
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>

      <div className="card">
        <div className="card-head"><h3>Open invoices</h3></div>
        {/* The box and its placeholder are the same on every visit, so they
            are typeable before a row has landed; only the count beside them
            is fetched, and only it waits. */}
        <TableSearch value={q} onChange={setQ} ready={!!ageing}
                     placeholder="Find an invoice number or a supplier…"
                     shown={shown.length} total={openInvoices.length} />
        {ageing && openInvoices.length === 0 ? (
          <div className="empty">
            No invoice is open. Everything recorded has been paid and
            allocated.
          </div>
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <Th>Invoice</Th><Th className="pay-supplier">Supplier</Th><Th>Due</Th>
                <Th className="num">Outstanding</Th><th className="actions" />
              </tr>
            </thead>
            {!ageing ? (
              <GhostRows cols={5} rows={5} secondLine={[2]}
                         widths={["12ch", "24ch", "12ch", "10ch", "8ch"]} />
            ) : (
            <tbody>
              {shown.map((i) => (
                  <tr key={i.invoice_id}>
                    <td className="mono">
                      <EntityLink kind="invoice" id={i.invoice_id}>{i.invoice_number}</EntityLink>
                    </td>
                    <td>
                      <EntityLink kind="supplier" id={i.supplier_id}>{i.supplier}</EntityLink>
                    </td>
                    <td>
                      {fmtDate(i.due_date)}
                      {i.days_overdue > 0 && (
                        <div className="muted small">
                          {i.days_overdue} day{i.days_overdue === 1 ? "" : "s"} late
                        </div>
                      )}
                    </td>
                    <td className="num">{money(i.outstanding)}</td>
                    <td className="actions">
                      {i.status === "queried" && (
                        <span className="badge"><Question size={11} /> queried</span>
                      )}
                      <button className="btn small"
                              onClick={() => show(i.invoice_id)}>
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
            )}
          </table>
        )}
      </div>

      {/* What has actually left the account. Without this the screen could
          only ever show a growing debt, which is not what the business
          looks like. */}
      <div className="card">
        <div className="card-head">
          <h3>Paid recently</h3>
          <span className="muted small">
            Newest first. Open one to send the supplier its remittance.
          </span>
        </div>
        {payments && payments.length === 0 ? (
          <div className="empty">
            No payment has been recorded. Every invoice above will keep
            ageing until one is.
          </div>
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <Th className="pay-supplier">Supplier</Th><Th>Paid</Th><Th>Reference</Th>
                <Th className="num">Amount</Th><Th className="num">On account</Th>
                <th className="actions" />
              </tr>
            </thead>
            {!payments ? (
              <GhostRows cols={6} rows={4}
                         widths={["24ch", "12ch", "14ch", "10ch", "10ch", "10ch"]} />
            ) : (
            <tbody>
              {payments.map((r) => (
                <tr key={r.payment_id}>
                  <td><b>{r.supplier}</b></td>
                  <td>{fmtDate(r.paid_on)}</td>
                  <td className="mono small">{r.reference || <span className="muted">None</span>}</td>
                  <td className="num">{money(r.amount)}</td>
                  <td className="num">
                    {r.on_account > 0.005
                      ? <b>{money(r.on_account)}</b>
                      : <span className="muted">None</span>}
                  </td>
                  <td className="actions">
                    <button className="btn small secondary"
                            onClick={() => setAdvice(r)}>
                      Remittance
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            )}
          </table>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Received, but no invoice has arrived</h3>
        </div>
        {waiting && waiting.length === 0 ? (
          <div className="empty">
            <b>Every delivery has been billed.</b>
            <p>
              Stock on the shelf with no bill behind it is a debt that has
              not been recorded. Nothing is outstanding.
            </p>
          </div>
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <Th>Order</Th><Th className="pay-supplier">Supplier</Th><Th>Received</Th>
                <Th className="num">Value</Th><th className="actions" />
              </tr>
            </thead>
            {!waiting ? (
              <GhostRows cols={5} rows={3} secondLine={[2]}
                         widths={["12ch", "24ch", "12ch", "10ch", "12ch"]} />
            ) : (
            <tbody>
              {waiting.map((w) => (
                <tr key={w.order_id}>
                  <td className="mono">
                    <EntityLink kind="order" id={w.order_id}>{w.order_number}</EntityLink>
                  </td>
                  <td>
                    <EntityLink kind="supplier" id={w.supplier_id}>{w.supplier}</EntityLink>
                  </td>
                  <td>
                    {w.received_at ? fmtDate(w.received_at) : "No date"}
                    {w.days !== null && w.days > 45 && (
                      <div className="muted small">{w.days} days ago</div>
                    )}
                  </td>
                  <td className="num">{money(w.value)}</td>
                  {/* THE VERB THIS CARD HAS ALWAYS NEEDED.
                      It calls each of these "a debt that has not been
                      recorded" and could not record one: the endpoint had
                      no caller anywhere in the product. Opened from the
                      delivery rather than from a blank form, so the
                      supplier and the order cannot be got wrong and the
                      figure that was expected is beside the box where the
                      billed one is typed. */}
                  <RowActions>
                    <button className="btn sm" onClick={() => setBilling(w)}>
                      Record the bill
                    </button>
                  </RowActions>
                </tr>
              ))}
            </tbody>
            )}
          </table>
        )}
      </div>

      {billing && (
        <RecordTheBill
          against={billing}
          onClose={() => setBilling(null)}
          onRecorded={load}
        />
      )}

      {paying && (
        <PaySupplier
          supplierId={paying.supplier_id}
          supplier={paying.supplier}
          owed={paying.total}
          invoices={paying.invoices}
          onClose={() => setPaying(null)}
          onPaid={(remittance) => {
            setPaying(null);
            // Straight into the advice, because the next thing anybody does
            // after paying a wholesaler is tell them.
            if (remittance) setAdvice(remittance);
            load();
          }}
        />
      )}

      {advice && <Remittance data={advice} onClose={() => setAdvice(null)} />}

      {open && (
        <div className="card">
          <div className="card-head">
            <h3><Receipt size={16} /> Invoice {open.invoice_number}</h3>
            <button className="btn secondary small" onClick={() => setOpen(null)}>
              Close
            </button>
          </div>

          {open.match && (
            <>
              <p className={open.match.matched ? "muted" : ""}>
                {open.match.matched
                  ? <><CheckCircle size={14} weight="fill" /> It matches what was received.</>
                  : <b>This invoice does not match what was received.</b>}
                {" "}{DEPTH_SAYS[open.match.depth]}
              </p>

              {open.match.problems.length > 0 && (
                <div className="alert warn">
                  <Warning size={16} weight="fill" />
                  <ul>
                    {open.match.problems.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                </div>
              )}

              <dl className="kv">
                <dt>Ordered</dt><dd>{money(open.match.ordered)}</dd>
                <dt>Received</dt><dd>{money(open.match.received)}</dd>
                <dt>Billed</dt><dd>{money(open.match.billed)}</dd>
                <dt>Difference</dt>
                <dd>
                  {open.match.variance >= 0
                    ? money(open.match.variance)
                    : `(${money(Math.abs(open.match.variance))})`}
                  <div className="muted small">
                    Approving posts this difference alone. The goods receipt
                    already raised the rest.
                  </div>
                </dd>
                <dt>Outstanding</dt><dd>{money(open.outstanding)}</dd>
              </dl>

              {open.match.lines.length > 0 && (
                <table className="dt sub">
                  <thead>
                    <tr>
                      <Th>Line</Th><Th className="num">Billed</Th>
                      <Th className="num">Received</Th><Th className="num">At</Th>
                      <Th className="num">Ordered at</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {open.match.lines.map((l, i) => (
                      <tr key={i}>
                        <td>
                          {l.description}
                          {l.issues.length > 0 && (
                            <div className="muted small">{l.issues.join(", ")}</div>
                          )}
                        </td>
                        <td className="num">{l.billed_quantity}</td>
                        <td className="num">{l.received_quantity}</td>
                        <td className="num">{money(l.billed_unit_cost)}</td>
                        <td className="num">{money(l.ordered_unit_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}

          {open.status === "queried" && open.query_note && (
            <div className="alert warn">
              <Question size={16} weight="fill" />
              <span>
                <b>Queried with the supplier.</b> {open.query_note}
              </span>
            </div>
          )}

          {querying ? (
            <div className="stack" style={{ marginTop: 12 }}>
              <label className="field">
                What is wrong with it?
                <input
                  value={queryNote} autoFocus maxLength={200}
                  onChange={(e) => setQueryNote(e.target.value)}
                  placeholder="Billed for 12, only 10 arrived. Spoke to Tendai on the 14th"
                />
                <span className="hint">
                  Written down because the next person to open this invoice has
                  to know the call was already made, and by whom.
                </span>
              </label>
              <div className="row-actions">
                <button className="btn secondary"
                        onClick={() => { setQuerying(false); setQueryNote(""); }}>
                  Cancel
                </button>
                <BusyButton className="btn primary" onClick={raiseQuery}
                            disabled={queryNote.trim().length < 4}
                            busyLabel="Marking…">
                  Mark it queried
                </BusyButton>
              </div>
            </div>
          ) : open.posted_reference ? (
            <p className="muted">
              Posted as <span className="mono">{open.posted_reference}</span>.
            </p>
          ) : (
            <div className="row-actions" style={{ marginTop: 12 }}>
              <BusyButton onClick={approve}>Approve for payment</BusyButton>
              {open.status !== "paid" && (
                <button className="btn secondary" onClick={() => {
                  setQueryNote(open.query_note || "");
                  setQuerying(true);
                }}>
                  <Question size={15} /> Query it with the supplier
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}
