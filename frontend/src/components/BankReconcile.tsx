/** The bank statement against the ledger.
 *
 *  This was a tab inside the ledger page, which is where an accountant looks
 *  for it and nowhere near where anybody else does. It is one of five things a
 *  pharmacy reconciles, and the other four were in four other places. Same
 *  screen, lifted out, so it can appear under Reconciliation as well as where
 *  it has always been.
 *
 *  Nothing here posts anything. A bank charge the ledger has never seen is a
 *  real transaction, and inventing a journal entry for it without somebody
 *  looking is how a ledger acquires figures nobody can explain. The output is
 *  a list of things to chase.
 */
import { useState } from "react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

/** What comes back from `/api/ledger/bank-reconciliation`.
 *
 *  Declared beside the screen that renders it rather than in the shared types
 *  file, because it is the only consumer and one more entry in a 900-line
 *  barrel is a worse place to find it.
 */
export interface BankRecon {
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


export default function BankReconcile() {
  const [statement, setStatement] = useState("");
  const [bank, setBank] = useState<BankRecon | null>(null);
  const toast = useToast();

  async function reconcileBank() {
    try {
      setBank(await api.post<BankRecon>("/api/ledger/bank-reconciliation", {
        account_code: "1010", content: statement,
      }));
    } catch (e) {
      toast.error(errorText(e, "That statement could not be read."));
    }
  }

  return (
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
  );
}
