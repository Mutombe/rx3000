/** Handing the books to the pharmacy's accountant.
 *
 *  Almost every pharmacy in this market keeps its financials in Pastel, and
 *  the person who does that is not the person at the counter. They want a
 *  file, once a month, that goes into their own ledger without being re-keyed.
 *
 *  WHY THIS IS A SCREEN AND NOT A BUTTON
 *
 *  A button would produce a file, and a file that imports into the wrong
 *  accounts balances perfectly and is the hardest error in bookkeeping to
 *  find. So everything that could be wrong is said BEFORE the download: how
 *  many lines, whether they balance, and which accounts have no Pastel code
 *  yet. The download is the last thing on the screen because it is the last
 *  thing that should happen.
 */
import { useCallback, useEffect, useState } from "react";
import { DownloadSimple, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "./BusyButton";
import { Refreshable, StatsSkeleton } from "./Skeleton";
import { useToast } from "./Toast";

interface Unmapped { code: string; name: string }
interface Summary {
  from: string; to: string; lines: number;
  debit: number; credit: number; balanced: boolean;
  unmapped: Unmapped[];
  settings: {
    date_format: string; separator: string; header: boolean;
    single_amount: boolean; tax_type: string;
  };
  says: string;
}

/** The first and last day of the month before this one.
 *
 *  Defaulted to last month rather than this one, because this month is not
 *  finished and a part month sent to an accountant is a part month they will
 *  have to ask about.
 */
function lastMonth(): { start: string; end: string } {
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const last = new Date(now.getFullYear(), now.getMonth(), 0);
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { start: iso(first), end: iso(last) };
}

export default function PastelExport({ onFixMapping }: {
  /** Takes the reader to the chart of accounts, where the codes are set.
   *  Passed in rather than routed here: the chart is a tab on this same page
   *  and a link that reloads the page to arrive back where it started is a
   *  worse answer than switching tabs. */
  onFixMapping?: () => void;
}) {
  const initial = lastMonth();
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const look = useCallback(() => {
    if (!start || !end) return;
    setLoading(true);
    api.get<Summary>(
      `/api/ledger/pastel-export/preview?start=${start}&end=${end}`)
      .then(setSummary)
      .catch((e) => toast.error(errorText(e, "Those days could not be read.")))
      .finally(() => setLoading(false));
  }, [start, end]);
  useEffect(() => { look(); }, [look]);

  async function download(force: boolean) {
    try {
      const file = await api.blob(
        `/api/ledger/pastel-export?start=${start}&end=${end}`
        + (force ? "&force=true" : ""));
      const url = URL.createObjectURL(file.body);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename || `pastel-${start}-${end}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Released on a delay: revoked at once, Safari cancels the download it
      // has not started yet.
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      toast.ok(force
        ? "Exported. Check where the unmapped lines landed before posting it."
        : `${summary?.lines ?? 0} line(s) exported.`);
    } catch (e) {
      toast.error(errorText(e, "That could not be exported."));
    }
  }

  const missing = summary?.unmapped ?? [];
  const nothing = !!summary && summary.lines === 0;

  return (
    <>
      <div className="card-head">
        <div>
          <h3>Export to Pastel</h3>
          <span className="muted small">
            The journal for these days, in the accountant's own account
            numbers, as a file their Pastel can import.
          </span>
        </div>
        {/* The same date control the statements beside this use. An export
            screen that invents its own date picker is a screen that looks
            bolted on, which is what it would be. */}
        <div className="st-controls">
          <label className="st-control">
            <span>From</span>
            <input type="date" value={start}
                   onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="st-control">
            <span>To</span>
            <input type="date" value={end}
                   onChange={(e) => setEnd(e.target.value)} />
          </label>
        </div>
      </div>

      <Refreshable loading={loading && !summary} hasData={!!summary}
                   skeleton={<StatsSkeleton tiles={4} />}>
        {summary && (
          <>
            {/* WHAT IS IN THE FILE, BEFORE IT IS A FILE.
                Three figures, because three is what an accountant checks: how
                much of it there is, and whether the two sides agree. Pastel
                refuses an import that does not balance, and finding that out
                in their office the next day costs both of them a day. */}
            <div className="wc-bands">
              <div className="wc-band">
                <span className="wc-band-label">Lines</span>
                <b>{summary.lines.toLocaleString()}</b>
                <span className="muted small">
                  every posted journal line in those days
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">Debits</span>
                <b>{money(summary.debit)}</b>
                <span className="muted small">
                  against {money(summary.credit)} credited
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">Balanced</span>
                <b className={summary.balanced ? undefined : "neg"}>
                  {summary.balanced ? "Yes" : "No"}
                </b>
                <span className="muted small">
                  {summary.balanced
                    ? "Pastel will accept it"
                    : "Pastel will refuse the file"}
                </span>
              </div>
              <div className="wc-band">
                <span className="wc-band-label">Unmapped accounts</span>
                <b className={missing.length ? "neg" : undefined}>
                  {missing.length}
                </b>
                <span className="muted small">
                  {missing.length
                    ? "these lines would go under our numbering"
                    : "every account has a Pastel code"}
                </span>
              </div>
            </div>

            {nothing && (
              <div className="alert">
                Nothing was posted between those days, so there is nothing to
                export. Widen the dates.
              </div>
            )}

            {!summary.balanced && !nothing && (
              <div className="alert error">
                The two sides differ by{" "}
                {money(Math.abs(summary.debit - summary.credit))}. Pastel will
                refuse an import that does not balance. Start at the trial
                balance rather than at this file.
              </div>
            )}

            {/* WHICH ACCOUNTS ARE NOT MAPPED, NAMED.
                A count alone leaves somebody hunting down a chart of forty
                accounts. Named, it is a list to work through, and the button
                beside it goes to where they are set. */}
            {missing.length > 0 && (
              <div className="alert warn">
                <p>
                  <Warning size={15} weight="fill" />{" "}
                  {missing.length} account{missing.length === 1 ? "" : "s"} used
                  in these days {missing.length === 1 ? "has" : "have"} no
                  Pastel code. Exported as they are, those lines arrive under
                  this system's numbering and land in whatever account holds
                  that number in their books. That imports cleanly and balances,
                  which is what makes it hard to find later.
                </p>
                <ul className="pe-missing">
                  {missing.map((a) => (
                    <li key={a.code}>
                      <span className="mono">{a.code}</span> {a.name}
                    </li>
                  ))}
                </ul>
                {onFixMapping && (
                  <button className="btn secondary small" onClick={onFixMapping}>
                    Set them on the chart of accounts
                  </button>
                )}
              </div>
            )}

            <div className="pe-foot">
              {/* HOW THE FILE IS SHAPED.
                  Shown, not hidden in a settings page, because Pastel's import
                  layout varies by version and by how the practice set it up.
                  The first thing anybody should do is send one file and ask. */}
              <p className="muted small">
                Written as{" "}
                <b>{summary.settings.single_amount
                  ? "one signed amount" : "separate debit and credit columns"}</b>,
                dates as <b>{summary.settings.date_format}</b>
                {summary.settings.header ? ", with a header row" : ", with no header row"}.
                Pastel's import layout differs between versions, so send one
                file to the accountant and have them confirm it before relying
                on a month of them.
              </p>

              <div className="row-actions">
                {missing.length > 0 && !nothing && (
                  <BusyButton className="btn secondary"
                              onClick={() => download(true)}
                              busyLabel="Exporting…">
                    Export anyway
                  </BusyButton>
                )}
                <BusyButton className="btn primary"
                            disabled={nothing || missing.length > 0}
                            onClick={() => download(false)}
                            busyLabel="Exporting…">
                  <DownloadSimple size={15} /> Export for Pastel
                </BusyButton>
              </div>
            </div>
          </>
        )}
      </Refreshable>
    </>
  );
}
