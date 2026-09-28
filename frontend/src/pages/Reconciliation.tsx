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
import { Block, Figure } from "../components/Skeleton";
import SectionNav from "../components/SectionNav";
import { useToast } from "../components/Toast";
import { RECON_TABS } from "../reconTabs";
import PageHead from "../components/PageHead";

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
      <PageHead title="Reconciliation" sub={data?.headline ?? "Two records of one thing, and the difference."} />

      {/* The family this page belongs to. It used to sit in the
          page's action slot beside a primary button, and on Authorisations
          beside a search box as well, so three different kinds of control
          shared one corner and wrapped the header to 176px against 76 on an
          ordinary page. Navigation is not an action. */}
      <SectionNav tabs={RECON_TABS} end="/reconciliation" />

      {/* SCOPED LOADING.
          The whole body used to sit behind a four column grey table, so the
          four band labels — which are written here, and say the same thing on
          every visit — were withheld and then arrived as though they had been
          fetched. They had not. Only the figures and the areas themselves come
          from the server, so only those pulse; and the warning tones wait for
          the figure behind them, because a band cannot be flagged on the
          strength of a nought nobody has counted yet. */}
      {!loading && !data ? (
        <p className="alert error">
          <Warning size={16} weight="fill" />
          <span>
            None of the reconciliations could be read. That is not the same as
            them agreeing: nothing has been compared, so nothing is known.
            Reload the page.
          </span>
        </p>
      ) : (
        <>
          <div className="wc-bands">
            <div className={`wl-stat${data?.at_stake ? " wc-abandoned" : ""}`}>
              <b className={data?.at_stake ? "tone-danger" : undefined}>
                <Figure ready={!!data} w="9ch">
                  {data && money(data.at_stake)}
                </Figure>
              </b>
              <span>Two records disagree about this much</span>
            </div>
            <div className="wl-stat">
              <b><Figure ready={!!data} w="3ch">{data?.unchecked}</Figure></b>
              <span>Closed without being checked</span>
            </div>
            <div className={`wl-stat${data?.not_run.length ? " wc-stale" : ""}`}>
              <b><Figure ready={!!data} w="3ch">{data?.not_run.length}</Figure></b>
              <span>Not run at all this period</span>
            </div>
            <div className="wl-stat">
              <b><Figure ready={!!data} w="3ch">{data?.days}</Figure></b>
              <span>Days covered</span>
            </div>
          </div>

          <div className="recon-grid">
            {!data && Array.from({ length: 6 }).map((_, i) => (
              // An area card is nothing but its area: the name, the figure
              // and the sentence are all fetched, so there are no words here
              // to keep. Cards of the right shape hold the grid open, and
              // there are six of them, not the five this used to draw: a
              // sixth card appearing under the fifth is the jump a skeleton
              // exists to prevent.
              <div key={i} className="recon-card" aria-busy="true">
                <Block w="14ch" h={15} />
                <Block w="9ch" h={22} />
                <Block w="24ch" h={12} />
              </div>
            ))}
            {data?.areas.map((a) => {
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

          {data && data.not_run.length > 0 && (
            <p className="alert warn">
              <Warning size={16} weight="fill" />
              <span>
                <b>{data.not_run.join(" and ")}</b>{" "}
                {data.not_run.length === 1 ? "has" : "have"} not been run this
                period. That is not the same as agreeing. Nothing has been
                compared, so nothing is known. Both need a file from outside
                the pharmacy, which is exactly why they are the two that get
                skipped.
              </span>
            </p>
          )}
        </>
      )}
    </div>
  );
}
