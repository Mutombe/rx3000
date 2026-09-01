/** When each funder wants its claims, and when it pays.
 *
 *  Claiming is not continuous. A pharmacy signs terms with each scheme saying
 *  when a month's claims must be in and when the money comes back, and missing
 *  a cut-off costs a whole cycle, which for a shop running on its float is the
 *  difference between paying staff this month and not.
 *
 *  None of that was recorded anywhere, so "when does CIMAS pay" was answered
 *  from somebody's memory and "what have we not sent yet" was a report nobody
 *  ran until the money was already late. Soonest deadline first, because the
 *  one with a date on it is the one to act on today.
 */
import { useCallback, useEffect, useState } from "react";
import SectionNav from "../components/SectionNav";
import { CLAIMING_TABS } from "../reconTabs";
import { ArrowClockwise, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import { useToast } from "../components/Toast";
import { useStepUp, CANCELLED } from "../components/StepUp";
import { TableSkeleton } from "../components/Skeleton";

interface Scheme {
  id: number; name: string; scheme_code: string; currency_code: string;
  realtime: boolean;
  claim_cutoff_day: number; settlement_day: number; settlement_days: number;
  agreement_reference: string; agreement_note: string;
  levy_fixed: number; levy_percent: number; discount_percent: number;
  extra_markup_percent: number; credit_limit: number;
  next_cutoff: string | null; days_to_cutoff: number | null;
  next_settlement: string | null; days_to_settlement: number | null;
  awaiting_payment: number; claims_awaiting: number; held: number;
}
interface Calendar {
  as_at: string; schemes: Scheme[];
  awaiting_payment: number; held: number; without_agreement: string[];
}

function when(days: number | null, on: string | null): string {
  if (days === null || !on) return "—";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `${days} days · ${fmtDate(on)}`;
}

/** How a funder has actually behaved, out of our own claim history.
 *
 *  Everything here is a fact about what we sent and what came back — no
 *  estimate, no projection — because somebody deciding whether to keep
 *  supplying a scheme on credit is owed figures they could check themselves.
 */
interface Standing {
  scheme: string; claims: number; claimed: number; settled: number;
  outstanding: number; rejected: number; recovery: number | null;
  overdue_claims: number; overdue_value: number;
  // A ratio, not a percentage — 0.1277 means 13%. The existing panel already
  // multiplies; getting it wrong here printed "0.1277%" beside a credit limit.
  oldest_overdue_days: number | null; late_after_days: number;
  settles_in: string; verdict: string; why: string;
}

export default function SchemeCalendar() {
  const [data, setData] = useState<Calendar | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [editing, setEditing] = useState<Scheme | null>(null);
  const [standing, setStanding] = useState<Standing | null>(null);
  const [form, setForm] = useState({
    cutoff: "", settle: "", terms: "", ref: "", note: "",
    levyFixed: "", levyPercent: "", discount: "", markup: "", credit: "",
  });
  const toast = useToast();
  const { guarded, prompt: stepUpPrompt } = useStepUp();

  const load = useCallback(() => {
    setSpinning(true);
    api.get<Calendar>("/api/claiming/schemes/calendar")
      .then((d) => { setData(d); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "The claiming calendar could not be loaded.")))
      .finally(() => {
        setLoading(false);
        window.setTimeout(() => setSpinning(false), 400);
      });
  }, []);
  useEffect(() => { load(); }, [load]);

  function open(scheme: Scheme) {
    setEditing(scheme);
    // How this funder has paid us, beside the terms we agreed with them. The
    // endpoint has existed since insurance standing was written and nothing
    // called it, so the screen where somebody sets a credit limit had no idea
    // whether the scheme settles at all.
    setStanding(null);
    api.get<Standing>(`/api/medical-aids/${scheme.id}/standing`)
      .then(setStanding)
      // A standing that cannot be read must not stop anybody editing terms.
      .catch(() => setStanding(null));
    setForm({
      cutoff: scheme.claim_cutoff_day ? String(scheme.claim_cutoff_day) : "",
      settle: scheme.settlement_day ? String(scheme.settlement_day) : "",
      terms: scheme.settlement_days ? String(scheme.settlement_days) : "",
      ref: scheme.agreement_reference,
      note: scheme.agreement_note,
      levyFixed: scheme.levy_fixed ? String(scheme.levy_fixed) : "",
      levyPercent: scheme.levy_percent ? String(scheme.levy_percent) : "",
      discount: scheme.discount_percent ? String(scheme.discount_percent) : "",
      markup: scheme.extra_markup_percent ? String(scheme.extra_markup_percent) : "",
      credit: scheme.credit_limit ? String(scheme.credit_limit) : "",
    });
  }

  async function save() {
    if (!editing) return;
    try {
      await api.put(`/api/claiming/schemes/${editing.id}/agreement`, {
        claim_cutoff_day: Number(form.cutoff) || 0,
        settlement_day: Number(form.settle) || 0,
        settlement_days: Number(form.terms) || 0,
        agreement_reference: form.ref,
        agreement_note: form.note,
      });
      // The terms go to their own endpoint, which is behind a step-up because
      // a levy reprices every future claim. Sent second so the dates are saved
      // even if somebody cancels the password prompt.
      const terms = {
        levy_fixed: Number(form.levyFixed) || 0,
        levy_percent: Number(form.levyPercent) || 0,
        discount_percent: Number(form.discount) || 0,
        extra_markup_percent: Number(form.markup) || 0,
        credit_limit: Number(form.credit) || 0,
      };
      const changed = (["levy_fixed", "levy_percent", "discount_percent",
                        "extra_markup_percent", "credit_limit"] as const)
        .some((k) => (terms as any)[k] !== (editing as any)[k]);
      if (changed) {
        const res = await guarded(
          "scheme.edit",
          (token) => api.put(`/api/medical-aids/${editing.id}`, terms, token),
          `${editing.name} — levy and discount`,
        );
        if (res === CANCELLED) {
          toast.warn("The dates were saved. The terms were not changed.");
          setEditing(null);
          load();
          return;
        }
      }
      toast.ok(`The agreement with ${editing.name} is recorded.`);
      setEditing(null);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be saved."));
    }
  }

  const schemes = data?.schemes ?? [];
  const dueSoon = schemes.filter((s) => s.days_to_cutoff !== null && s.days_to_cutoff <= 3);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Claiming calendar</h1>
          <div className="sub">
            When each funder wants its claims, and when it settles
          </div>
        </div>
        <div className="page-actions">
          <SectionNav tabs={CLAIMING_TABS} end="/claiming" />
          <button className="btn secondary" onClick={load}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {failed && <div className="alert error">{failed}</div>}

      {data && (
        <>
          <div className="wc-bands">
            <div className="wl-stat">
              <b>{money(data.awaiting_payment)}</b><span>claimed, not yet paid</span>
            </div>
            <div className={`wl-stat${data.held ? " wc-stale" : ""}`}>
              <b>{data.held}</b><span>claims held, not sent</span>
            </div>
            <div className={`wl-stat${dueSoon.length ? " wc-abandoned" : ""}`}>
              <b>{dueSoon.length}</b><span>cut-offs within three days</span>
            </div>
          </div>

          {/* The deadline that costs money if it passes. */}
          {dueSoon.length > 0 && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />
              <span>
                {dueSoon.map((s) => `${s.name} (${when(s.days_to_cutoff, s.next_cutoff)})`)
                  .join(", ")}
                {" — "}anything not submitted by then waits a whole cycle.
              </span>
            </div>
          )}

          {data.without_agreement.length > 0 && (
            <div className="alert">
              No agreed dates on file for {data.without_agreement.join(", ")}.
              Until they are recorded nobody can tell when those claims are due
              or when the money is coming.
            </div>
          )}

          {/* Every funder's cut-off and payment day. A blank frame while it
              loads reads as a pharmacy with no schemes on file, which is the
              one thing that would make this page pointless. */}
          {loading && (
            <div className="card">
              <TableSkeleton cols={5} rows={5}
                widths={["20ch", "12ch", "14ch", "12ch", "14ch"]} />
            </div>
          )}
          {!loading && (
          <div className="card">
            <table className="dt">
              <thead>
                <tr>
                  <th>Funder</th><th>Claims in by</th><th>Next cut-off</th>
                  <th>Pays on</th><th>Next payment</th>
                  <th className="num">Awaiting</th><th className="num">Held</th>
                  <th className="actions" />
                </tr>
              </thead>
              <tbody>
                {schemes.map((s) => (
                  <tr key={s.id}
                      className={s.days_to_cutoff !== null && s.days_to_cutoff <= 3
                        ? "row-flag" : ""}>
                    <td>
                      <b>{s.name}</b>
                      <div className="muted small">
                        {s.scheme_code}
                        {s.agreement_reference ? ` · ${s.agreement_reference}` : ""}
                      </div>
                    </td>
                    <td>
                      {s.realtime
                        ? <span className="badge ok">realtime</span>
                        : s.claim_cutoff_day
                          ? `${s.claim_cutoff_day}${ordinal(s.claim_cutoff_day)}`
                          : <span className="muted">not agreed</span>}
                    </td>
                    <td>{s.realtime ? "—" : when(s.days_to_cutoff, s.next_cutoff)}</td>
                    <td>
                      {s.settlement_day
                        ? `${s.settlement_day}${ordinal(s.settlement_day)}`
                        : s.settlement_days
                          ? `${s.settlement_days} days after`
                          : <span className="muted">not agreed</span>}
                    </td>
                    <td>{when(s.days_to_settlement, s.next_settlement)}</td>
                    <td className="num">
                      {money(s.awaiting_payment)}
                      {s.claims_awaiting > 0 && (
                        <div className="muted small">{s.claims_awaiting} claims</div>
                      )}
                    </td>
                    <td className="num">
                      {s.held > 0
                        ? <b>{s.held}</b>
                        : <span className="muted">—</span>}
                    </td>
                    <td className="actions">
                      <button className="btn small secondary" onClick={() => open(s)}>
                        Agreement
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          )}
        </>
      )}

      {stepUpPrompt}
      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editing.name}</h2>

            {standing && standing.claims > 0 && (
              // Facts before terms. Setting a credit limit for a funder that
              // has settled 42% of what it was sent is a different decision
              // from setting one for a funder that settles everything.
              <div className={`sc-standing is-${standing.verdict}`}>
                <div className="sc-standing-head">
                  <b>How they have actually paid</b>
                  <span className="muted small">
                    {standing.claims.toLocaleString()} claims
                    {standing.settles_in ? ` · settles in ${standing.settles_in}` : ""}
                  </span>
                </div>
                <div className="sc-standing-facts">
                  <div>
                    <span className="muted small">Recovered</span>
                    <b>{standing.recovery === null
                      ? <span className="muted">not yet</span>
                      : `${Math.round(standing.recovery * 100)}%`}</b>
                  </div>
                  <div>
                    <span className="muted small">Outstanding</span>
                    <b>{money(standing.outstanding)}</b>
                  </div>
                  <div>
                    <span className="muted small">
                      Late past {standing.late_after_days} days
                    </span>
                    <b className={standing.overdue_value > 0.005 ? "neg" : undefined}>
                      {money(standing.overdue_value)}
                    </b>
                  </div>
                  <div>
                    <span className="muted small">Refused</span>
                    <b>{standing.rejected}</b>
                  </div>
                </div>
                <p className="muted small">{standing.why}</p>
              </div>
            )}

            <p className="muted">
              What was agreed with this funder. A day of the month for each,
              or terms in days where the memorandum is written that way.
            </p>
            <label className="field">
              Claims must be in by (day of the month)
              <input type="number" min="0" max="31" value={form.cutoff}
                     onChange={(e) => setForm({ ...form, cutoff: e.target.value })}
                     placeholder="0 for no cut-off" autoFocus />
            </label>
            <label className="field">
              They settle on (day of the month)
              <input type="number" min="0" max="31" value={form.settle}
                     onChange={(e) => setForm({ ...form, settle: e.target.value })}
                     placeholder="0 if terms-based" />
            </label>
            <label className="field">
              Or, days after submission
              <input type="number" min="0" value={form.terms}
                     onChange={(e) => setForm({ ...form, terms: e.target.value })}
                     placeholder="e.g. 30" />
            </label>
            <label className="field">
              Memorandum reference
              <input value={form.ref}
                     onChange={(e) => setForm({ ...form, ref: e.target.value })}
                     placeholder="so somebody can find the paper" />
            </label>
            <label className="field">
              Note
              <input value={form.note}
                     onChange={(e) => setForm({ ...form, note: e.target.value })} />
            </label>

            {/* What the member pays and what the pharmacy gives away.
                These reprice every claim this scheme touches, and there was an
                endpoint to change them with no screen that could, so they sat
                at whatever they were first set to. */}
            <h3>What the member pays</h3>
            <div className="form-row">
              <div className="field">
                <label>Levy, fixed</label>
                <input type="number" min="0" step="0.01" value={form.levyFixed}
                       onChange={(e) => setForm({ ...form, levyFixed: e.target.value })}
                       placeholder="0.00" />
                <span className="field-hint">A flat amount the member pays.</span>
              </div>
              <div className="field">
                <label>Levy, per cent</label>
                <input type="number" min="0" max="100" step="0.1" value={form.levyPercent}
                       onChange={(e) => setForm({ ...form, levyPercent: e.target.value })}
                       placeholder="0" />
                <span className="field-hint">
                  Their share of the claim. The larger of the two is taken.
                </span>
              </div>
            </div>
            <div className="form-row">
              <div className="field">
                <label>Scheme discount %</label>
                <input type="number" min="0" max="100" step="0.1" value={form.discount}
                       onChange={(e) => setForm({ ...form, discount: e.target.value })}
                       placeholder="0" />
                <span className="field-hint">What this funder is given off the price.</span>
              </div>
              <div className="field">
                <label>Extra markup %</label>
                <input type="number" min="0" max="100" step="0.1" value={form.markup}
                       onChange={(e) => setForm({ ...form, markup: e.target.value })}
                       placeholder="0" />
                <span className="field-hint">Where the scheme allows a higher margin.</span>
              </div>
            </div>
            <label className="field">
              Credit limit
              <input type="number" min="0" step="0.01" value={form.credit}
                     onChange={(e) => setForm({ ...form, credit: e.target.value })}
                     placeholder="0 for no limit" />
              <span className="field-hint">
                How much the pharmacy will carry for this funder before it stops
                claiming. Zero means no limit is set.
              </span>
            </label>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setEditing(null)}>Cancel</button>
              <BusyButton onClick={save}>Save the agreement</BusyButton>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** 1st, 2nd, 3rd, 4th: a date read aloud rather than a number. */
function ordinal(day: number): string {
  if (day % 100 >= 11 && day % 100 <= 13) return "th";
  return ["th", "st", "nd", "rd"][day % 10] ?? "th";
}
