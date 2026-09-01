/** Everything that has two records of one fact, and whether they agree.
 *
 *  A pharmacy reconciles five different things and had five different places to
 *  do it: card settlement on its own page, the bank statement inside a tab in
 *  the ledger, claims from the remittances screen, cash in the cash office, and
 *  stock drift inside a tab in the catalogue. Each of those was fine on its
 *  own, and together they answered nobody's actual question, which on a Monday
 *  morning is not "how do I reconcile cards" but **what does not tie up**.
 *
 *  So the reconciliations keep their own screens, and this sits above them.
 *
 *  The one thing it refuses to do is show a clean tick for an exercise nobody
 *  ran. Card and bank both need a file somebody uploads; until one is loaded
 *  they read as *not run*, not as *nought differences*. Turning "unchecked"
 *  into "checked and fine" is the failure mode every control in this system is
 *  built to avoid, and a summary screen is the easiest place in the world to
 *  do it by accident.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Question, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import SectionNav from "../components/SectionNav";
import { useToast } from "../components/Toast";
import { RECON_TABS } from "../reconTabs";

interface Area {
  key: string; label: string;
  runs: number; reconciled: number; not_reconciled: number;
  /** null means nobody has run it. Not the same as nought. */
  differences: number | null;
  value: number; net: number;
  worst: number; worst_where: string;
  href: string; says: string;
}
interface Overview {
  days: number; areas: Area[];
  at_stake: number; not_run: string[]; unchecked: number;
  headline: string;
}

export default function Reconciliation() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    api.get<Overview>("/api/reconciliation/overview")
      .then(setData)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Reconciliation</h1>
          <p className="muted">
            {data?.headline ?? "Two records of one thing, and the difference."}
          </p>
        </div>
        <div className="page-actions">
          <SectionNav tabs={RECON_TABS} end="/reconciliation" />
        </div>
      </header>

      <Refreshable loading={loading} hasData={!!data}
        skeleton={<TableSkeleton cols={4} rows={5} />}>
        {data && (
          <>
            <div className="wc-bands">
              <div className={`wl-stat${data.at_stake ? " wc-abandoned" : ""}`}>
                <b className={data.at_stake ? "tone-danger" : undefined}>
                  {money(data.at_stake)}
                </b>
                <span>two records disagree about this much</span>
              </div>
              <div className="wl-stat">
                <b>{data.unchecked}</b>
                <span>closed without being checked</span>
              </div>
              <div className={`wl-stat${data.not_run.length ? " wc-stale" : ""}`}>
                <b>{data.not_run.length}</b>
                <span>not run at all this period</span>
              </div>
              <div className="wl-stat">
                <b>{data.days}</b><span>days covered</span>
              </div>
            </div>

            <div className="recon-grid">
              {data.areas.map((a) => {
                const unrun = a.differences === null;
                const off = !unrun && (a.differences! > 0 || a.not_reconciled > 0);
                return (
                  <Link key={a.key} to={a.href}
                    className={`recon-card ${
                      unrun ? "is-unrun" : off ? "is-off" : "is-clean"}`}>
                    <h4>{a.label}</h4>
                    <div className="recon-value">
                      {unrun ? (
                        <span className="muted">
                          <Question size={18} weight="bold" /> not run
                        </span>
                      ) : a.value ? (
                        money(a.value)
                      ) : (
                        <span className="tone-ok">agrees</span>
                      )}
                    </div>
                    <div className="recon-says">{a.says}</div>
                    {/* The worst single one, where there is a worst. A total
                        of 153 across three tills is a different problem from
                        150 on one of them, and only this says which. */}
                    {!unrun && a.worst_where && Math.abs(a.worst) >= 0.01 && (
                      <div className="recon-says">
                        Worst single: {money(a.worst)} on {a.worst_where}.
                      </div>
                    )}
                    <div className="recon-says">
                      Open <ArrowRight size={12} weight="bold" />
                    </div>
                  </Link>
                );
              })}
            </div>

            {data.not_run.length > 0 && (
              <p className="alert warn">
                <Warning size={16} weight="fill" />
                <span>
                  <b>{data.not_run.join(" and ")}</b>{" "}
                  {data.not_run.length === 1 ? "has" : "have"} not been run this
                  period. That is not the same as agreeing — nothing has been
                  compared, so nothing is known. Both need a file from outside
                  the pharmacy, which is exactly why they are the two that get
                  skipped.
                </span>
              </p>
            )}
          </>
        )}
      </Refreshable>
    </div>
  );
}
