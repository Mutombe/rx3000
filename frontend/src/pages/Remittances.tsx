/** Remittance advices: what a scheme actually paid, and what it did not.
 *
 *  Eight endpoints and no screen, including both importers — so the 132 advices
 *  in the database are there because they were seeded, not because anybody could
 *  load one.
 *
 *  The screen is built around the shortfall rather than the payment, because the
 *  payment needs no attention. A scheme paying a claim in full is the end of the
 *  matter; a scheme paying $1,008 against $1,400 leaves $392 that belongs to
 *  somebody, and until it is billed to the patient or written off it is money
 *  sitting in the air. That list is the first thing on the page and it carries a
 *  running total.
 *
 *  Writing off is deliberately as easy to reach as billing the patient, and
 *  neither is the default. A pharmacy that bills every shortfall to patients
 *  loses them; one that writes every shortfall off funds the scheme's shortfall
 *  out of its own margin. It is a judgement each time, and the reason the scheme
 *  gave is shown next to the buttons so it can be made.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, errorText, fmtDate, money } from "../api";
import { useConfirm } from "../components/Confirm";
import { TableSkeleton } from "../components/Skeleton";
import Pagination, { Paged } from "../components/Pagination";
import { useDebounced } from "../hooks/useDebounced";
import { useToast } from "../components/Toast";

type Tab = "outstanding" | "advices" | "import";

interface Line {
  id: number; remittance_id: number; remittance_number: string; funder_id: string;
  claim_reference: string; member_name: string; service_date: string | null;
  amount_claimed: number; amount_paid: number; variance: number;
  reason_code: string; reason: string; status: string;
  written_off: boolean; patient_billed: boolean; resolution_note: string;
}
interface Outstanding { count: number; total: number; showing: number; lines: Line[] }
interface Advice {
  id: number; remittance_number: string; funder_id: string;
  payment_date: string | null; payment_reference: string; currency_code: string;
  status: string; line_count: number; total_claimed: number; total_paid: number;
  shortfall: number; outstanding: number; unmatched: number;
  counts: Record<string, number>;
}
interface Reason { reason_code: string; meaning: string }

export default function Remittances() {
  const toast = useToast();
  const confirm = useConfirm();
  const [params, setParams] = useSearchParams();
  const tab = ((["outstanding", "advices", "import"] as Tab[])
    .find((t) => t === params.get("tab")) ?? "outstanding") as Tab;
  const setTab = (t: Tab) =>
    setParams(t === "outstanding" ? {} : { tab: t }, { replace: true });

  const [open, setOpen] = useState<Outstanding | null>(null);
  const [advices, setAdvices] = useState<Advice[]>([]);
  const [adviceMeta, setAdviceMeta] = useState<Paged<Advice> | null>(null);
  const [advicePage, setAdvicePage] = useState(1);
  const [adviceSearch, setAdviceSearch] = useState("");
  const settledSearch = useDebounced(adviceSearch);
  const [reasons, setReasons] = useState<Reason[]>([]);
  const [busy, setBusy] = useState("");

  // import
  const [funder, setFunder] = useState("");
  const [number, setNumber] = useState("");
  const [payRef, setPayRef] = useState("");
  const [payDate, setPayDate] = useState("");
  const [content, setContent] = useState("");

  const load = useCallback(() => {
    api.get<Outstanding>("/api/remittances/outstanding?limit=200")
      .then(setOpen)
      .catch((e) => toast.error(errorText(e, "The outstanding shortfalls could not be listed.")));
    api.get<Paged<Advice>>(
      `/api/remittances/paged?page=${advicePage}&per_page=25`
      + `&q=${encodeURIComponent(settledSearch)}`)
      .then((res) => {
        setAdvices(res.items);
        setAdviceMeta(res);
        if (res.page !== advicePage) setAdvicePage(res.page);
      })
      .catch(() => undefined);
    api.get<Reason[]>("/api/remittances/reasons/vocabulary").then(setReasons).catch(() => undefined);
  }, [toast, advicePage, settledSearch]);

  useEffect(load, [load]);

  // Narrowing the set sends you back to the first page of it.
  const firstSearch = useRef(true);
  useEffect(() => {
    if (firstSearch.current) { firstSearch.current = false; return; }
    setAdvicePage(1);
  }, [settledSearch]);

  async function resolve(line: Line, action: "bill_patient" | "write_off") {
    const billing = action === "bill_patient";
    const ok = await confirm({
      title: billing
        ? `Bill ${money(line.variance)} to the patient?`
        : `Write off ${money(line.variance)}?`,
      body: billing
        ? `${line.member_name || "The patient"} becomes liable for the shortfall on `
          + `claim ${line.claim_reference}. The scheme's reason was: ${line.reason}`
        : `The pharmacy absorbs the shortfall on claim ${line.claim_reference}. `
          + `It goes to the write-off account and shows in the margin, not in debtors.`,
      confirmLabel: billing ? "Bill the patient" : "Write it off",
      destructive: !billing,
    });
    if (!ok) return;
    setBusy(`line-${line.id}`);
    try {
      // A short note, so that six months later the decision has a reason
      // attached. It goes in its own field — appending it to the scheme's stated
      // reason is how that column ended up saying "uneconomic" eight times.
      const note = billing ? "billed to patient" : "uneconomic to pursue";
      await api.post(
        `/api/remittances/lines/${line.id}/resolve?action=${action}`
        + `&note=${encodeURIComponent(note)}`, {});
      toast.ok(billing
        ? `${money(line.variance)} billed to the patient.`
        : `${money(line.variance)} written off.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function importCsv(e: React.FormEvent) {
    e.preventDefault();
    setBusy("import");
    try {
      const res = await api.post<{ remittance_number?: string; line_count?: number }>(
        "/api/remittances/import-csv", {
          funder_id: funder.trim().toUpperCase(),
          remittance_number: number.trim(),
          payment_reference: payRef.trim(),
          payment_date: payDate || null,
          content,
        });
      toast.ok(`${res.remittance_number ?? number} imported with `
        + `${res.line_count ?? 0} line(s).`);
      setContent(""); setNumber(""); setPayRef("");
      setTab("advices");
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Remittances</h1>
          <div className="sub">
            What each scheme actually paid, and where the difference went
          </div>
        </div>
      </div>

      <div className="pill-tabs">
        <button className={tab === "outstanding" ? "active" : ""}
          onClick={() => setTab("outstanding")}>
          Money in the air{open ? ` (${open.count})` : ""}
        </button>
        <button className={tab === "advices" ? "active" : ""} onClick={() => setTab("advices")}>
          Advices
        </button>
        <button className={tab === "import" ? "active" : ""} onClick={() => setTab("import")}>
          Import
        </button>
      </div>

      {tab === "outstanding" && (
        <div className="card">
          <h3>Shortfalls not yet settled</h3>
          {!open ? <TableSkeleton cols={5} rows={5} /> : open.count === 0 ? (
            <p className="st-note is-ok">
              Every shortfall has been billed or written off. Nothing is in the air.
            </p>
          ) : (
            <>
              <p className="muted">
                {open.count} line(s), {money(open.total)} between what was claimed
                and what was paid. Each one is owed by the patient, or by nobody.
                {/* The count and the money are over everything open; the table
                    below is the worst of them. Reporting the cap as the total is
                    how this endpoint said $70,000 when $98,096 was outstanding. */}
                {open.showing < open.count && (
                  <> Showing the {open.showing} largest.</>
                )}
              </p>
              <div className="cu-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Claim</th><th>Member</th><th>Service</th>
                      <th className="num">Claimed</th><th className="num">Paid</th>
                      <th className="num">Short</th><th>Scheme's reason</th><th />
                    </tr>
                  </thead>
                  <tbody>
                    {open.lines.map((l) => (
                      <tr key={l.id}>
                        <td className="mono">{l.claim_reference}</td>
                        <td><span className="clip" title={l.member_name}>{l.member_name || <span className="muted">—</span>}</span></td>
                        <td>{l.service_date ? fmtDate(l.service_date) : "—"}</td>
                        <td className="num">{money(l.amount_claimed)}</td>
                        <td className="num">{money(l.amount_paid)}</td>
                        <td className="num cu-diff">{money(l.variance)}</td>
                        <td>
                          <span className="clip clip-2" title={l.reason}>
                            {l.reason || <span className="muted">not given</span>}
                          </span>
                          {l.reason_code && (
                            <div className="muted mono small">{l.reason_code}</div>
                          )}
                        </td>
                        <td className="num lb-actions">
                          <button className="small" disabled={busy === `line-${l.id}`}
                            onClick={() => resolve(l, "bill_patient")}>
                            Bill patient
                          </button>
                          <button className="small ghost" disabled={busy === `line-${l.id}`}
                            onClick={() => resolve(l, "write_off")}>
                            Write off
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {tab === "advices" && (
        <div className="card">
          <h3>Advices received</h3>
          <input
            className="page-search"
            value={adviceSearch}
            onChange={(e) => setAdviceSearch(e.target.value)}
            placeholder="Search advice number or payment reference"
          />
          {advices.length === 0 ? (
            <div className="empty">No remittance advices yet.</div>
          ) : (
            <div className="cu-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Advice</th><th>Funder</th><th>Paid on</th><th>Reference</th>
                    <th className="num">Lines</th><th className="num">Claimed</th>
                    <th className="num">Paid</th><th className="num">Short</th>
                    <th>Unmatched</th>
                  </tr>
                </thead>
                <tbody>
                  {advices.map((a) => (
                    <tr key={a.id}>
                      <td className="mono">{a.remittance_number}</td>
                      <td>{a.funder_id}</td>
                      <td>{a.payment_date ? fmtDate(a.payment_date) : "—"}</td>
                      <td className="mono muted">{a.payment_reference || "—"}</td>
                      <td className="num">{a.line_count}</td>
                      <td className="num">{money(a.total_claimed)}</td>
                      <td className="num">{money(a.total_paid)}</td>
                      <td className={`num${a.shortfall > 0.005 ? " cu-diff" : ""}`}>
                        {a.shortfall > 0.005 ? money(a.shortfall) : "—"}
                      </td>
                      <td>
                        {/* A line the advice mentions that we cannot tie to a
                            claim is the one worth chasing: either they paid for
                            something we did not send, or our reference is wrong. */}
                        {a.unmatched > 0
                          ? <span className="badge danger">{a.unmatched}</span>
                          : <span className="muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {adviceMeta && (
            <Pagination meta={adviceMeta} onPage={setAdvicePage} noun="advices" />
          )}
        </div>
      )}

      {tab === "import" && (
        <>
          <div className="card">
            <h3>Import an advice</h3>
            <p className="muted">
              Paste the spreadsheet the scheme sent. The columns it needs are the
              claim reference, what was claimed and what was paid; a reason code
              where the scheme gives one.
            </p>
            <form onSubmit={importCsv}>
              <div className="form-row">
                <div className="field">
                  <label>Funder</label>
                  <input value={funder} onChange={(e) => setFunder(e.target.value)}
                    placeholder="e.g. PSMAS_ZW" required />
                </div>
                <div className="field">
                  <label>Advice number</label>
                  <input value={number} onChange={(e) => setNumber(e.target.value)}
                    placeholder="As printed on the advice" required />
                </div>
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Payment reference</label>
                  <input value={payRef} onChange={(e) => setPayRef(e.target.value)}
                    placeholder="The EFT reference on the bank statement" />
                </div>
                <div className="field">
                  <label>Paid on</label>
                  <input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} />
                </div>
              </div>
              <div className="field">
                <label>The advice itself</label>
                <textarea rows={8} value={content} onChange={(e) => setContent(e.target.value)}
                  placeholder={"claim_reference,amount_claimed,amount_paid,reason_code\n"
                    + "SIM-0048143,1400.00,1008.00,LEVY"} required />
              </div>
              <div className="cu-actions">
                <button className="btn primary" type="submit"
                  disabled={busy === "import" || !content.trim()}>
                  {busy === "import" ? "Importing…" : "Import the advice"}
                </button>
              </div>
            </form>
          </div>

          <div className="card">
            <h3>Reason codes</h3>
            <p className="muted">
              What each code means once it has been normalised. Schemes word the
              same refusal differently; these are what they are recorded as.
            </p>
            <table>
              <tbody>
                {reasons.map((r) => (
                  <tr key={r.reason_code}>
                    <td className="mono">{r.reason_code}</td>
                    <td>{r.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
