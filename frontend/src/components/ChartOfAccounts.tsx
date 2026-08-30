/** The chart of accounts — the shape of the business before any figures.
 *
 *  A trial balance says whether the books balance. This says where things go,
 *  which is the question actually asked, and asked far more often: by the
 *  bookkeeper with an electricity bill in hand, by the owner wondering what the
 *  shop is worth, by the accountant at year end.
 *
 *  Grouped by section rather than by type, deliberately. Stock and a delivery
 *  van are both assets; putting them in one heap is how a pharmacy comes to
 *  believe it has forty thousand dollars of working capital when half of that
 *  is a vehicle it cannot pay a supplier with. The sections are the headings a
 *  balance sheet uses, so what is read here is what will be read there.
 *
 *  Adding an account is the point of the screen. A chart you cannot extend is a
 *  chart that gets worked around — every unclassifiable cost posted to "sundry"
 *  until sundry is the largest expense in the business and means nothing.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowClockwise, PencilSimple, Plus, Printer } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import BusyButton from "./BusyButton";
import Checkbox from "./Checkbox";
import { EntityLink } from "./Filters";
import Select from "./Select";
import { Refreshable, TableSkeleton } from "./Skeleton";
import { useToast } from "./Toast";

interface Row {
  code: string; name: string; type: string; section: string;
  subledger: string; parent_code: string; is_cash: boolean; active: boolean;
  notes: string; balance: number; protected: boolean; posted_to: boolean;
}
interface Group {
  section: string; label: string; type: string; accounts: Row[]; total: number;
}
interface Chart {
  groups: Group[]; count: number;
  totals: {
    assets: number; current_assets: number; non_current_assets: number;
    liabilities: number; current_liabilities: number;
    non_current_liabilities: number; equity: number; revenue: number;
    expenses: number; profit: number; working_capital: number;
  };
  difference: number;
  sections: { key: string; label: string; type: string }[];
}

const TYPES = [
  { value: "asset", label: "Asset", hint: "Something the pharmacy owns or is owed" },
  { value: "liability", label: "Liability", hint: "Something the pharmacy owes" },
  { value: "equity", label: "Equity", hint: "What the owners have put in, and kept in" },
  { value: "income", label: "Income", hint: "Money earned" },
  { value: "expense", label: "Expense", hint: "Money spent to earn it" },
];

/** Money, with the sign said in words rather than left to a minus.
 *
 *  A liability of 4,000 is not "minus four thousand", and showing it that way
 *  is how somebody reads a healthy creditor balance as a hole in the bank.
 */
function Balance({ value }: { value: number }) {
  if (Math.abs(value) < 0.005) return <span className="muted">—</span>;
  return (
    <span className={value < 0 ? "neg" : undefined}>
      {money(Math.abs(value))}{value < 0 ? " cr" : ""}
    </span>
  );
}

export default function ChartOfAccounts() {
  const [chart, setChart] = useState<Chart | null>(null);
  const [inactive, setInactive] = useState(false);
  const [spinning, setSpinning] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Row | null>(null);
  const toast = useToast();

  const load = useCallback((quiet = false) => {
    if (!quiet) setSpinning(true);
    api.get<Chart>(`/api/ledger/chart?include_inactive=${inactive}`)
      .then(setChart)
      .catch((e) => toast.error(errorText(e, "The chart could not be loaded.")))
      .finally(() => window.setTimeout(() => setSpinning(false), 300));
  }, [inactive]);
  useEffect(() => { load(); }, [load]);

  async function print() {
    const head = await letterhead();
    printDocument(head, {
      kind: "Chart of accounts",
      meta: [
        { label: "Accounts", value: String(chart?.count ?? 0) },
        { label: "As at", value: new Date().toLocaleDateString() },
      ],
      columns: [
        { key: "code", label: "Code", width: "20mm" },
        { key: "name", label: "Account" },
        { key: "type", label: "Type", width: "24mm" },
        { key: "section", label: "Where it appears", width: "42mm" },
        { key: "balance", label: "Balance", numeric: true, width: "28mm" },
      ],
      // The section headings survive into the document as rows of their own:
      // a printed chart that loses its grouping is an alphabetical list, and
      // an alphabetical list is what everybody already has in a spreadsheet.
      rows: (chart?.groups ?? []).flatMap((g) => [
        { code: "", name: g.label.toUpperCase(), type: "", section: "",
          balance: money(g.total) },
        ...g.accounts.map((a) => ({
          code: a.code, name: a.name + (a.active ? "" : " (retired)"),
          type: a.type, section: g.label, balance: money(a.balance),
        })),
      ]),
      note: "Balances are as at the date shown and include every posted entry.",
    });
  }

  const equationOff = Math.abs(chart?.difference ?? 0) > 0.005;

  return (
    <>
      <div className="card-head">
        <div>
          <h3>Chart of accounts</h3>
          <span className="muted small">
            Where every figure in this pharmacy is filed. Grouped as a balance
            sheet groups it, not by code.
          </span>
        </div>
        <div className="row-actions">
          <Checkbox checked={inactive} onChange={setInactive}>
            Show retired
          </Checkbox>
          <button className="btn secondary" onClick={() => load()}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
          </button>
          <button className="btn secondary" onClick={print} disabled={!chart}>
            <Printer size={15} /> Print
          </button>
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Plus size={15} weight="bold" /> New account
          </button>
        </div>
      </div>

      <Refreshable loading={spinning || !chart} hasData={!!chart}
                   skeleton={<TableSkeleton rows={12} cols={4}
                                            widths={["8rem", "auto", "12rem", "10rem"]} />}>
        {chart && (
          <>
          <div className="wc-bands">
            <div className="wc-band">
              <span className="wc-band-label">Assets</span>
              <b>{money(chart.totals.assets)}</b>
              <span className="muted small">
                {money(chart.totals.current_assets)} current
              </span>
            </div>
            <div className="wc-band">
              <span className="wc-band-label">Liabilities</span>
              <b>{money(chart.totals.liabilities)}</b>
              <span className="muted small">
                {money(chart.totals.current_liabilities)} due inside a year
              </span>
            </div>
            <div className="wc-band">
              <span className="wc-band-label">Working capital</span>
              <b className={chart.totals.working_capital < 0 ? "neg" : undefined}>
                {money(chart.totals.working_capital)}
              </b>
              <span className="muted small">
                current assets less current liabilities
              </span>
            </div>
            <div className="wc-band">
              <span className="wc-band-label">Profit to date</span>
              <b className={chart.totals.profit < 0 ? "neg" : undefined}>
                {money(chart.totals.profit)}
              </b>
              <span className="muted small">
                {money(chart.totals.revenue)} earned, {money(chart.totals.expenses)} spent
              </span>
            </div>
          </div>

          {equationOff && (
            <div className="alert warn">
              Assets are {money(Math.abs(chart.difference))}{" "}
              {chart.difference > 0 ? "more" : "less"} than liabilities, equity
              and profit together. The books do not balance, and every statement
              drawn from them carries that difference. Start at the trial
              balance.
            </div>
          )}

          {chart.groups.map((g) => (
            <div key={g.section} className="coa-group">
              <div className="coa-group-head">
                <h4>{g.label}</h4>
                <b><Balance value={g.total} /></b>
              </div>
              <table className="dt">
                <thead>
                  <tr>
                    <th style={{ width: "8rem" }}>Code</th>
                    <th>Account</th>
                    <th style={{ width: "12rem" }}>Notes</th>
                    <th className="num" style={{ width: "10rem" }}>Balance</th>
                    <th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {g.accounts.map((a) => (
                    <tr key={a.code} className={a.active ? undefined : "is-muted"}>
                      <td className="mono">
                        <EntityLink to={`/ledger/accounts/${a.code}`}>
                          {a.code}
                        </EntityLink>
                      </td>
                      <td>
                        {a.name}
                        {a.is_cash && <span className="badge ok">cash</span>}
                        {a.subledger && <span className="badge">{a.subledger}</span>}
                        {!a.active && <span className="badge">retired</span>}
                      </td>
                      <td className="muted small wrap">
                        {a.notes || (a.protected
                          ? "Used by the posting rules"
                          : a.posted_to ? "" : "Never posted to")}
                      </td>
                      <td className="num"><Balance value={a.balance} /></td>
                      <td className="actions">
                        <button className="btn ghost small" title="Edit this account"
                                onClick={() => setEditing(a)}>
                          <PencilSimple size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          </>
        )}
      </Refreshable>

      {adding && chart && (
        <NewAccount sections={chart.sections}
                    onClose={() => setAdding(false)}
                    onAdded={() => { setAdding(false); load(true); }} />
      )}

      {editing && chart && (
        <EditAccount account={editing} sections={chart.sections}
                     onClose={() => setEditing(null)}
                     onSaved={() => { setEditing(null); load(true); }} />
      )}
    </>
  );
}

/** Add an account.
 *
 *  The section is chosen, not derived. A type says what an account is; a
 *  section says where a reader expects to find it, and only the person adding
 *  it knows whether this new asset is stock or a shopfitting.
 */
function NewAccount({ sections, onClose, onAdded }: {
  sections: { key: string; label: string; type: string }[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("expense");
  const [section, setSection] = useState("operating_expense");
  const [isCash, setIsCash] = useState(false);
  const [notes, setNotes] = useState("");
  const toast = useToast();

  // Only the sections that belong to this type. Offering "Current liabilities"
  // for an expense account is offering a mistake.
  const allowed = useMemo(
    () => sections.filter((s) => s.type === type), [sections, type]);

  useEffect(() => {
    if (!allowed.some((s) => s.key === section)) {
      setSection(allowed[0]?.key ?? "");
    }
  }, [allowed, section]);

  const ready = code.trim().length >= 3 && name.trim().length >= 2;

  async function save() {
    try {
      const r = await api.post<{ message: string }>("/api/ledger/accounts", {
        code: code.trim(), name: name.trim(), type, section,
        is_cash: isCash, notes: notes.trim(),
      });
      toast.ok(r.message);
      onAdded();
    } catch (e) {
      // The server refuses a duplicate code, a section that does not suit the
      // type, and a code with punctuation in it — and its wording says which.
      toast.error(errorText(e, "That account could not be added."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>New account</h2>
        <p className="muted">
          Add what this pharmacy actually spends and owns. A chart that cannot
          be extended is one where everything unclassifiable ends up in
          "sundry".
        </p>

        <div className="form-row">
          <div className="field span-4">
            <label>Code</label>
            <input value={code} autoFocus maxLength={10}
                   onChange={(e) => setCode(e.target.value)}
                   placeholder="6900" />
            <span className="hint">
              Digits, grouped like the accounts around it — 6xxx for running
              costs, 1xxx for what is owned.
            </span>
          </div>
          <div className="field span-8">
            <label>Name</label>
            <input value={name} maxLength={120}
                   onChange={(e) => setName(e.target.value)}
                   placeholder="Cleaning and consumables" />
          </div>
        </div>

        <div className="form-row">
          <div className="field span-6">
            <label>What it is</label>
            <Select value={type} onChange={setType} options={TYPES}
                    ariaLabel="Account type" />
          </div>
          <div className="field span-6">
            <label>Where it appears</label>
            <Select value={section} onChange={setSection}
                    options={allowed.map((s) => ({ value: s.key, label: s.label }))}
                    ariaLabel="Section" />
          </div>
        </div>

        {type === "asset" && (
          <Checkbox checked={isCash} onChange={setIsCash}
                    hint={"Cash, a bank account or a mobile money float. The cash "
                        + "flow statement needs to know, and no combination of "
                        + "type and section can tell it."}>
            This account is cash
          </Checkbox>
        )}

        <div className="field">
          <label>Notes <span className="muted">optional</span></label>
          <input value={notes} onChange={(e) => setNotes(e.target.value)}
                 placeholder="What belongs in here, so the next person files it the same way" />
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" disabled={!ready} onClick={save}
                      busyLabel="Adding…">
            Add account
          </BusyButton>
        </div>
      </div>
    </div>
  );
}

/** Change an account.
 *
 *  What may change and what may not is the server's business, and it is strict
 *  for reasons that only show up months later: a code is what every journal
 *  line ever posted refers to, and an account's type is the sign of every
 *  figure already in it. So the code is shown and not editable, and the type is
 *  offered only where the server would accept the change — which the row itself
 *  says, because it knows whether anything has been posted to it.
 */
function EditAccount({ account, sections, onClose, onSaved }: {
  account: Row;
  sections: { key: string; label: string; type: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(account.name);
  const [section, setSection] = useState(account.section);
  const [isCash, setIsCash] = useState(account.is_cash);
  const [notes, setNotes] = useState(account.notes);
  const toast = useToast();

  const allowed = useMemo(
    () => sections.filter((sec) => sec.type === account.type),
    [sections, account.type]);

  const locked = account.protected || account.posted_to;

  async function save() {
    try {
      const r = await api.patch<{ message: string }>(
        `/api/ledger/accounts/${account.code}`,
        { name: name.trim(), section, is_cash: isCash, notes: notes.trim() });
      toast.ok(r.message);
      onSaved();
    } catch (e) {
      toast.error(errorText(e, "That account could not be changed."));
    }
  }

  async function retire() {
    try {
      const r = await api.patch<{ message: string }>(
        `/api/ledger/accounts/${account.code}`, { active: false });
      toast.ok(r.message);
      onSaved();
    } catch (e) {
      // The server refuses to retire a protected account or one with a balance
      // on it, and says which. Shown as written.
      toast.error(errorText(e, "That account could not be retired."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{account.code} · {account.name}</h2>
        <p className="muted">
          {account.protected
            ? "The posting rules name this account, so its type cannot change "
              + "and it cannot be retired. Its name and where it appears can."
            : account.posted_to
              ? "This account has been posted to. Its name and section can "
                + "change; its type cannot, because that would flip the sign of "
                + "every figure already in it."
              : "Nothing has been posted to this account yet."}
        </p>

        <div className="field">
          <label>Name</label>
          <input value={name} autoFocus maxLength={120}
                 onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="field">
          <label>Where it appears</label>
          <Select value={section} onChange={setSection}
                  options={allowed.map((sec) => ({ value: sec.key, label: sec.label }))}
                  ariaLabel="Section" />
        </div>

        {account.type === "asset" && (
          <Checkbox checked={isCash} onChange={setIsCash}
                    hint="Counted as cash by the cash flow statement.">
            This account is cash
          </Checkbox>
        )}

        <div className="field">
          <label>Notes <span className="muted">optional</span></label>
          <input value={notes} onChange={(e) => setNotes(e.target.value)}
                 placeholder="What belongs in here" />
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          {!locked && account.active && (
            <BusyButton className="btn secondary" onClick={retire}
                        busyLabel="Retiring…">
              Retire
            </BusyButton>
          )}
          <BusyButton className="btn primary" onClick={save}
                      disabled={name.trim().length < 2} busyLabel="Saving…">
            Save
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
