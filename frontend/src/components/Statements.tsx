/** The income statement and the balance sheet.
 *
 *  Two presentation rules, both taken from how accountants actually read these
 *  and both easy to get wrong:
 *
 *  **A section is shown even when it is empty.** A zero next to Stock write-offs
 *  says the pharmacy wrote nothing off, which is information. An absent line
 *  says nobody knows whether it is zero or forgotten. Zero rows can be hidden on
 *  request, never by default.
 *
 *  **Every total can be opened.** A figure a pharmacist cannot decompose is a
 *  figure they cannot check, and a statement that cannot be checked is not worth
 *  signing. Each section expands into the accounts behind it.
 *
 *  The balance sheet says plainly whether it balances. If it does not, the
 *  difference is printed rather than rounded away — being out by a cent means
 *  something is wrong, and hiding it destroys the only evidence.
 */
import { useEffect, useState } from "react";
import { Printer } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { TableSkeleton } from "./Skeleton";
import Checkbox from "./Checkbox";

interface Line {
  code: string; name: string; amount: number; subledger?: string; computed?: boolean;
}
interface Section {
  key: string; heading: string; total: number; accounts: Line[]; subtotal?: boolean;
}
interface Income {
  from: string; to: string; sections: Section[];
  revenue: number; cost_of_sales: number; gross_profit: number; gross_margin: number;
  operating_expenses: number; net_profit: number;
  /** Null for the group. See JournalEntry.branch_id. */
  branch_id: number | null;
}
interface Branch { id: number; name: string }
interface Balance {
  as_at: string; sections: Section[];
  total_assets: number; total_liabilities: number; total_equity: number;
  profit_for_period: number; balances: boolean; difference: number; note: string;
}

/** The first day of the month `n` months back, as an ISO date. */
function isoToday() {
  return new Date().toISOString().slice(0, 10);
}

export default function Statements({ kind }: { kind: "income" | "balance" }) {
  const [upto, setUpto] = useState(isoToday);
  const [hideZero, setHideZero] = useState(false);
  /* Which shop, or the group. Only the income statement offers this: a branch
     has no bank account and no share capital, so a balance sheet for one is a
     document that cannot balance. */
  const [branch, setBranch] = useState("");
  const [branches, setBranches] = useState<Branch[]>([]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [income, setIncome] = useState<Income | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);

  /* A statement that failed to load is not a statement of zero. Swallowed,
     the skeleton stayed up for ever and the reader waited on a figure that
     was never coming. */
  const [problem, setProblem] = useState("");

  /* The shops to choose between. A single-shop pharmacy never sees the
     control at all, because "which branch" is not a question they have. */
  useEffect(() => {
    if (kind !== "income") return;
    api.get<Branch[]>("/api/branches")
      .then(setBranches)
      // Silent: without the list there is no picker, and no picker means the
      // group statement, which is what this screen has always shown.
      .catch(() => setBranches([]));
  }, [kind]);

  useEffect(() => {
    const q = `upto=${upto}&hide_zero=${hideZero}`
      + (kind === "income" && branch ? `&branch_id=${branch}` : "");
    const failed = (e: unknown) =>
      setProblem(errorText(e, "That statement could not be read."));
    setProblem("");
    if (kind === "income") {
      setIncome(null);
      api.get<Income>(`/api/ledger/income-statement?${q}`).then(setIncome).catch(failed);
    } else {
      setBalance(null);
      api.get<Balance>(`/api/ledger/balance-sheet?${q}`).then(setBalance).catch(failed);
    }
  }, [kind, upto, hideZero, branch]);

  const branchName = branches.find((b) => String(b.id) === branch)?.name ?? "";

  const data = kind === "income" ? income : balance;

  function SectionRows({ sections }: { sections: Section[] }) {
    return (
      <>
        {sections.map((s) => {
          const expanded = open[s.key];
          return (
            <tbody key={s.key} className={s.subtotal ? "st-subtotal" : undefined}>
              <tr
                className={`st-section${s.accounts.length ? " is-openable" : ""}`}
                onClick={() => s.accounts.length && setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))}
              >
                <td>
                  {s.accounts.length > 0 && (
                    <span className={`st-caret${expanded ? " is-open" : ""}`} aria-hidden="true">›</span>
                  )}
                  {s.heading}
                  {s.accounts.length > 0 && (
                    <span className="muted st-count"> {s.accounts.length}</span>
                  )}
                </td>
                <td className="mono st-amount">{money(s.total)}</td>
              </tr>
              {expanded && s.accounts.map((a) => (
                <tr key={s.key + a.code} className="st-line">
                  <td>
                    <span className="mono muted">{a.code}</span> {a.name}
                    {a.computed && <span className="badge muted st-badge">Calculated</span>}
                    {a.subledger && <span className="badge st-badge">{a.subledger}</span>}
                  </td>
                  <td className="mono st-amount">{money(a.amount)}</td>
                </tr>
              ))}
            </tbody>
          );
        })}
      </>
    );
  }

  /** The statement as a document.
   *
   *  These two are the pages a pharmacy hands to a bank, a landlord or a
   *  prospective buyer, and until now the only way to get one on paper was to
   *  print the screen — browser header, navigation and all. An accountant
   *  receiving that reads it as a business with no accounting system.
   *
   *  The section headings survive as rows of their own, and every account under
   *  them prints whether or not it was expanded on screen: a statement a reader
   *  cannot decompose is one they cannot check.
   */
  async function print() {
    if (!data) return;
    const head = await letterhead();
    const rows: Record<string, unknown>[] = [];
    data.sections.forEach((section) => {
      rows.push({ name: section.heading.toUpperCase(), amount: "" });
      section.accounts.forEach((line) => rows.push({
        code: line.code, name: line.name, amount: money(line.amount),
      }));
      rows.push({ name: `Total ${section.heading.toLowerCase()}`,
                  amount: money(section.total) });
    });

    printDocument(head, {
      kind: kind === "income" ? "Income statement" : "Balance sheet",
      meta: kind === "income" && income
        ? [// Which shop, on the paper itself. A branch statement and the
           // group's look identical once printed, and the one that gets taken
           // to a bank is whichever was on the desk.
           ...(branchName ? [{ label: "Shop", value: branchName }] : []),
           { label: "From", value: fmtDate(income.from) },
           { label: "To", value: fmtDate(income.to) },
           { label: "Gross margin", value: `${income.gross_margin}%` },
           { label: income.net_profit >= 0 ? "Net profit" : "Net loss",
             value: money(income.net_profit), strong: true }]
        : balance
          ? [{ label: "As at", value: fmtDate(balance.as_at) },
             { label: "Total assets", value: money(balance.total_assets) },
             { label: "Liabilities and equity",
               value: money(balance.total_liabilities + balance.total_equity),
               strong: true }]
          : [],
      columns: [
        { key: "code", label: "Code", width: "20mm" },
        { key: "name", label: "" },
        { key: "amount", label: "Amount", numeric: true, width: "34mm" },
      ],
      rows,
      totals: kind === "income" && income
        ? { name: income.net_profit >= 0 ? "Net profit" : "Net loss",
            amount: money(income.net_profit) }
        : balance
          ? { name: "Liabilities and equity",
              amount: money(balance.total_liabilities + balance.total_equity) }
          : undefined,
      // The balance sheet says either way whether it balances. A statement
      // that only speaks up when it is wrong leaves a reader unable to tell
      // "checked and fine" from "never checked".
      note: kind === "balance" && balance ? balance.note : undefined,
    });
  }

  return (
    <div className="card">
      <div className="st-controls">
        <label className="st-control">
          <span>{kind === "income" ? "Up to" : "As at"}</span>
          <input type="date" value={upto} onChange={(e) => setUpto(e.target.value)} />
        </label>
        {kind === "income" && branches.length > 1 && (
          <label className="st-control">
            <span>Shop</span>
            <select value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">The whole pharmacy</option>
              {branches.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </label>
        )}
        <div className="st-control st-check">
          <Checkbox checked={hideZero} onChange={setHideZero}>
            Hide empty sections
          </Checkbox>
        </div>
        {kind === "income" && income && (
          <span className="muted">
            {income.from} to {income.to}
          </span>
        )}
        <button className="btn secondary small" onClick={print} disabled={!data}
                style={{ marginLeft: "auto" }}>
          <Printer size={15} /> Print
        </button>
      </div>

      {problem && <div className="alert error">{problem}</div>}

      {/* Said once, plainly, because the figure below is not what a reader
          assumes it is. A branch statement carries that shop's trading and
          none of the costs carried above it, so the four shops add up to the
          group's gross profit and not to its net. Leaving that unsaid is how
          somebody reads a branch as unprofitable when what it is missing is
          rent nobody charged it. */}
      {kind === "income" && branchName && (
        <p className="muted small">
          {branchName} only. Group costs such as bank charges and head office
          are not charged to a shop, so this is what {branchName} contributes
          before them.
        </p>
      )}

      {problem ? null : !data ? (
        <TableSkeleton cols={2} rows={7} />
      ) : (
        <>
          <table className="st-table">
            <SectionRows sections={data.sections} />
            <tfoot>
              {kind === "income" && income && (
                <>
                  <tr>
                    <td>Gross margin</td>
                    <td className="mono st-amount">{income.gross_margin}%</td>
                  </tr>
                  <tr className="st-total">
                    <td>{income.net_profit >= 0 ? "Net profit" : "Net loss"}</td>
                    <td className="mono st-amount">{money(income.net_profit)}</td>
                  </tr>
                </>
              )}
              {kind === "balance" && balance && (
                <>
                  <tr>
                    <td>Total assets</td>
                    <td className="mono st-amount">{money(balance.total_assets)}</td>
                  </tr>
                  <tr className="st-total">
                    <td>Liabilities and equity</td>
                    <td className="mono st-amount">
                      {money(balance.total_liabilities + balance.total_equity)}
                    </td>
                  </tr>
                </>
              )}
            </tfoot>
          </table>

          {kind === "balance" && balance && (
            // Stated either way. A statement that only speaks up when it is
            // wrong leaves a reader unable to tell "checked and fine" from
            // "never checked".
            <p className={`st-note ${balance.balances ? "is-ok" : "is-bad"}`}>
              {balance.note}
            </p>
          )}
        </>
      )}
    </div>
  );
}
