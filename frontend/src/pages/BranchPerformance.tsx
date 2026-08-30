/** One branch, in full.
 *
 *  The scorecard answers "which of my shops is working". This answers the
 *  question that follows it, which is always "why" — and that one needs the
 *  workings rather than the verdict: not "cash-up 46%" but twelve counted out
 *  of twenty-six and thirty-five dollars adrift; not "claims 80%" but what was
 *  raised, what came back, and what was refused.
 *
 *  It reads the same endpoint the scorecard does and shows one branch of it.
 *  Deliberately: two endpoints answering the same question about the same
 *  branch is how a group manager ends up with a summary and a detail page that
 *  disagree, and then trusts neither.
 *
 *  Every section links to the screen that can do something about it. A number
 *  a manager cannot act on is a number they stop reading.
 */
import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowClockwise } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import Breadcrumbs from "../components/Breadcrumbs";
import { EntityLink } from "../components/Filters";
import Select from "../components/Select";
import { DetailSkeleton } from "../components/Skeleton";
import { rateTone } from "../tone";

const WINDOWS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "60", label: "Last 60 days" },
  { value: "90", label: "Last quarter" },
  { value: "365", label: "Last year" },
];

/** A percentage, or the reason there is not one. */
function pct(value: number | null, good = 90) {
  if (value === null || value === undefined) {
    return <span className="muted">not counted</span>;
  }
  return <span className={`badge ${rateTone(value, good)}`}>{value}%</span>;
}

/** One figure, with what it is measured against underneath it.
 *
 *  A bare number is a fact; a number with its denominator is a judgement
 *  somebody can make. "12 exact" means nothing until it says "of 26".
 */
function Fact({ label, value, hint, tone }: {
  label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: string;
}) {
  return (
    <div className={`bpd-fact${tone ? ` is-${tone}` : ""}`}>
      <span className="bpd-label">{label}</span>
      <b className="bpd-value">{value}</b>
      {hint && <span className="bpd-hint">{hint}</span>}
    </div>
  );
}

function Section({ title, sub, link, children }: {
  title: string; sub?: string;
  link?: { to: string; label: string };
  children: React.ReactNode;
}) {
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>{title}</h3>
          {sub && <span className="muted small">{sub}</span>}
        </div>
        {link && (
          <EntityLink to={link.to}>
            <button className="btn small secondary">{link.label}</button>
          </EntityLink>
        )}
      </div>
      {children}
    </section>
  );
}

export default function BranchPerformance() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const days = params.get("days") || "30";
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [spinning, setSpinning] = useState(false);

  const load = useCallback(() => {
    setSpinning(true);
    api.get<any>(`/api/scorecard?days=${days}`)
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e) => setError(errorText(e, "That branch could not be loaded.")))
      .finally(() => window.setTimeout(() => setSpinning(false), 350));
  }, [days]);
  useEffect(load, [load]);

  const branch = data?.branches?.find(
    (b: any) => String(b.branch_id) === String(id));

  const trail = [
    { label: "Dashboard", to: "/" },
    { label: "Branch performance", to: "/scorecard" },
    { label: branch?.branch ?? "This branch" },
  ];

  if (error) {
    return (
      <>
        <Breadcrumbs trail={trail} />
        <div className="alert error">{error}</div>
      </>
    );
  }
  if (!data) {
    return <DetailSkeleton trail={trail} eyebrow="Branch" cards={4} />;
  }
  if (!branch) {
    return (
      <>
        <Breadcrumbs trail={trail} />
        <div className="empty">
          <b>No such branch on this pharmacy</b>
          <p>
            It may belong to another pharmacy, or have been removed since this
            link was made.
          </p>
        </div>
      </>
    );
  }

  const b = branch;

  return (
    <>
      <Breadcrumbs trail={trail} />
      <div className="page-head">
        <div>
          <div className="eyebrow">Branch</div>
          <h1>{b.branch}</h1>
          <div className="sub">
            {b.code}{b.city ? ` · ${b.city}` : ""}
            {b.is_default && " · the default branch"}
            {!b.active && " · closed"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Select value={days}
                  onChange={(v) => setParams({ days: v }, { replace: true })}
                  options={WINDOWS} />
          <button className="btn secondary" onClick={load}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
          </button>
          <EntityLink to="/scorecard">
            <button className="btn secondary">
              <ArrowLeft size={13} weight="bold" /> All branches
            </button>
          </EntityLink>
        </div>
      </div>

      <Section title="What it took" sub={`Over the last ${data.days} days`}
               link={{ to: "/pos?tab=history", label: "The sales" }}>
        <div className="bpd-facts">
          <Fact label="Taken" value={money(b.sales.value)}
                hint={`${b.sales.count.toLocaleString()} sales`} />
          <Fact label="Average sale" value={money(b.sales.average)} />
          <Fact label="Cash" value={money(b.money.cash.amount)}
                hint={`${b.money.cash.count} payments`} />
          <Fact label="Card" value={money(b.money.card.amount)}
                hint={`${b.money.card.count} payments`} />
          <Fact label="Mobile money" value={money(b.money.mobile_money.amount)}
                hint={`${b.money.mobile_money.count} payments`} />
          <Fact label="Medical aid" value={money(b.money.medical_aid.amount)}
                hint={`${b.money.medical_aid.count} claims`} />
          <Fact label="Unpaid" value={b.sales.pending}
                hint="dispensed, never settled"
                tone={b.sales.pending > 0 ? "bad" : undefined} />
          <Fact label="Part paid" value={b.sales.part_paid} />
        </div>
      </Section>

      <Section title="The drawer" sub="Whether what was counted matches what was taken"
               link={{ to: "/shifts", label: "Shifts" }}>
        <div className="bpd-facts">
          <Fact label="Accuracy" value={pct(b.cashup.accuracy, 95)} />
          <Fact label="Counted exactly" value={b.cashup.exact}
                hint={`of ${b.cashup.shifts_counted} cashed up`} />
          <Fact label="Out by" value={money(b.cashup.total_variance)}
                tone={b.cashup.total_variance > 0.005 ? "bad" : undefined}
                hint="across the period" />
          <Fact label="Shifts" value={b.people.shifts}
                hint={b.people.open_now ? `${b.people.open_now} open now` : "all closed"} />
          <Fact label="Tills" value={b.people.tills} />
          <Fact label="Staff" value={b.people.staff} />
        </div>
      </Section>

      <Section title="Dispensing" sub="What went out, and whether the steps were followed"
               link={{ to: "/dispensing-history", label: "History" }}>
        <div className="bpd-facts">
          <Fact label="Items dispensed" value={b.dispensing.items.toLocaleString()} />
          <Fact label="Checked" value={pct(b.sop.checked_rate, 95)}
                hint={`${b.sop.checked} of ${b.sop.dispensings}`} />
          <Fact label="Script sighted" value={pct(b.sop.sighted_rate, 90)}
                hint={`${b.sop.script_sighted} of ${b.sop.dispensings}`} />
          <Fact label="Uncollected" value={b.dispensing.uncollected}
                tone={b.dispensing.uncollected > 0 ? "warn" : undefined}
                hint="bagged and never fetched" />
          <Fact label="Controlled" value={b.dispensing.controlled}
                hint={b.sop.controlled > 0
                  ? <>ID seen {pct(b.sop.id_rate, 100)}</> : "none"} />
          <Fact label="Over the counter" value={b.counter.sales.toLocaleString()}
                hint={b.counter.sales > 0
                  ? <>counselled {pct(b.sop.counselling_rate, 90)}</> : undefined} />
          <Fact label="Referred to a doctor" value={b.counter.referred} />
          <Fact label="Patients served" value={b.patients.served.toLocaleString()} />
        </div>
      </Section>

      <Section title="Claims" sub="What the schemes were asked for, and what came back"
               link={{ to: "/claiming", label: "Claiming" }}>
        <div className="bpd-facts">
          <Fact label="Raised" value={b.claims.raised} />
          <Fact label="Claimed" value={b.claims.claimed} />
          <Fact label="Settled" value={b.claims.settled} />
          <Fact label="Recovered" value={pct(b.claims.recovery, 80)} />
          <Fact label="Rejected" value={b.claims.rejected}
                tone={b.claims.rejected > 0 ? "bad" : undefined} />
          <Fact label="Held" value={b.claims.held}
                hint="waiting to be sent"
                tone={b.claims.held > 0 ? "warn" : undefined} />
        </div>
      </Section>

      <Section title="Stock" sub="What is on the shelf here"
               link={{ to: "/stock", label: "Inventory" }}>
        <div className="bpd-facts">
          <Fact label="At cost" value={money(b.stock.at_cost)} />
          <Fact label="Units" value={b.stock.units.toLocaleString()} />
          <Fact label="Batches" value={b.stock.batches.toLocaleString()} />
          <Fact label="Short dated" value={b.stock.short_dated}
                tone={b.stock.short_dated > 0 ? "warn" : undefined}
                hint="expiring soon" />
          <Fact label="Lines sold" value={b.stock.product_lines_sold.toLocaleString()} />
        </div>
      </Section>

      <Section title="Buying and delivering" sub="What was ordered, and what reached a patient"
               link={{ to: "/orders", label: "Orders" }}>
        <div className="bpd-facts">
          <Fact label="Orders raised" value={b.buying.orders} />
          <Fact label="Received" value={b.buying.received} />
          <Fact label="Outstanding" value={b.buying.outstanding}
                tone={b.buying.outstanding > 0 ? "warn" : undefined} />
          <Fact label="Deliveries" value={b.deliveries.raised}
                hint={b.deliveries.raised > 0
                  ? <>{pct(b.deliveries.success, 90)} arrived</> : "none"} />
          <Fact label="Failed" value={b.deliveries.failed}
                tone={b.deliveries.failed > 0 ? "bad" : undefined} />
          <Fact label="Via the portal" value={b.portal.scripts_in}
                hint="scripts sent in by a prescriber" />
        </div>
      </Section>

      {data.not_measured?.length > 0 && (
        <Section title="What this page does not measure"
                 sub="Said in words rather than shown as nought">
          <table className="dt">
            <tbody>
              {data.not_measured.map((m: any) => (
                <tr key={m.metric}>
                  <td style={{ width: "16rem" }}><b>{m.metric}</b></td>
                  <td className="wrap muted">{m.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </>
  );
}
