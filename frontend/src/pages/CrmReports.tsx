import { useEffect, useMemo, useState } from "react";
import { useToast } from "../components/Toast";
import { useSearchParams } from "react-router-dom";
import { api, money, errorText  } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { BarList, ColumnChart, Donut, FunnelChart, Legend, useSeries } from "../components/charts";
import { CampaignROI, ForecastMonth, FunnelReport, OwnerReport } from "../types";
import { TableSkeleton } from "../components/Skeleton";

type Tab = "forecast" | "funnel" | "owners" | "campaigns";

const TABS: [Tab, string][] = [
  ["forecast", "Forecast"], ["funnel", "Conversion"], ["owners", "Rep performance"], ["campaigns", "Attribution"],
];

const compact = (n: number) =>
  n >= 1_000_000 ? `R${(n / 1_000_000).toFixed(1)}m`
    : n >= 1_000 ? `R${Math.round(n / 1_000)}k`
    : `R${Math.round(n)}`;

export default function CrmReports() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find(([t]) => t === params.get("tab"))?.[0] ?? "forecast") as Tab;
  const setTab = (t: Tab) => setParams(t === "forecast" ? {} : { tab: t }, { replace: true });
  const [forecast, setForecast] = useState<ForecastMonth[]>([]);
  const [funnel, setFunnel] = useState<FunnelReport | null>(null);
  const [owners, setOwners] = useState<OwnerReport[]>([]);
  const [roi, setRoi] = useState<CampaignROI[]>([]);
  // Follows the theme, so the charts repaint rather than keeping the light hues
  // on a dark surface.
  const SERIES = useSeries();
  const toast = useToast();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (tab === "forecast") api.get<ForecastMonth[]>("/api/crm/reports/forecast?months=6").then(setForecast)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
    if (tab === "funnel") api.get<FunnelReport>("/api/crm/reports/funnel").then(setFunnel).catch((e) => toast.error(errorText(e)));
    if (tab === "owners") api.get<OwnerReport[]>("/api/crm/reports/by-owner").then(setOwners).catch((e) => toast.error(errorText(e)));
    if (tab === "campaigns") api.get<CampaignROI[]>("/api/crm/reports/campaign-roi").then(setRoi).catch((e) => toast.error(errorText(e)));
  }, [tab]);

  const totals = useMemo(() => ({
    open: forecast.reduce((s, f) => s + f.open_value, 0),
    weighted: forecast.reduce((s, f) => s + f.weighted_value, 0),
    won: forecast.reduce((s, f) => s + f.won_value, 0),
    deals: forecast.reduce((s, f) => s + f.deals, 0),
  }), [forecast]);

  const channelMix = useMemo(() => {
    const byChannel = new Map<string, number>();
    roi.forEach((c) => byChannel.set(c.channel, (byChannel.get(c.channel) ?? 0) + c.pipeline_value));

    /* Biggest first, and never more slices than there are colours.
       The old line took `SERIES[i % SERIES.length]`, so a seventh channel was
       painted the same blue as the first: two slices of one donut in one colour,
       with a legend insisting they were different things. Anything past the
       sixth is added up as "Other" instead, which is also the honest reading of
       a tail of channels that sourced almost nothing. */
    const ranked = [...byChannel.entries()].sort((a, b) => b[1] - a[1]);
    const shown = ranked.slice(0, SERIES.length - (ranked.length > SERIES.length ? 1 : 0));
    const rest = ranked.slice(shown.length);

    const slices = shown.map(([key, value], i) => ({
      key: key.toUpperCase(), value, colour: SERIES[i],
    }));
    if (rest.length) {
      slices.push({
        key: `OTHER (${rest.length})`,
        value: rest.reduce((s, [, v]) => s + v, 0),
        colour: SERIES[SERIES.length - 1],
      });
    }
    return slices;
  }, [roi, SERIES]);

  const worstDrop = useMemo(() => {
    let worst = { from: "—", lost: 0 };
    funnel?.stages.forEach((s, i) => {
      if (i === 0) return;
      const lost = funnel.stages[i - 1].count - s.count;
      if (lost > worst.lost) worst = { from: funnel.stages[i - 1].stage, lost };
    });
    return worst;
  }, [funnel]);

  /** Print the tab that is open, as a document.
   *
   *  This one is taken into a sales meeting, so it has to survive being handed
   *  round a table. A screen print of a dashboard does not — half of it is
   *  navigation, and the figures somebody is being asked to commit to are
   *  sitting next to a sidebar.
   */
  async function printTab() {
    const head = await letterhead();
    const today = new Date().toLocaleDateString();

    if (tab === "forecast" && forecast.length) {
      printDocument(head, {
        kind: "Revenue forecast",
        meta: [
          { label: "Prepared", value: today },
          { label: "Months", value: String(forecast.length) },
          { label: "Weighted pipeline",
            value: money(forecast.reduce((n, m2) => n + m2.weighted_value, 0)),
            strong: true },
        ],
        columns: [
          { key: "month", label: "Month", width: "28mm" },
          { key: "deals", label: "Deals", numeric: true, width: "20mm" },
          { key: "open", label: "Open value", numeric: true, width: "30mm" },
          { key: "weighted", label: "Weighted", numeric: true, width: "30mm" },
          { key: "won", label: "Won", numeric: true, width: "30mm" },
        ],
        rows: forecast.map((m2) => ({
          month: m2.month, deals: String(m2.deals),
          open: money(m2.open_value), weighted: money(m2.weighted_value),
          won: money(m2.won_value),
        })),
        totals: {
          month: "Total",
          deals: String(forecast.reduce((n, m2) => n + m2.deals, 0)),
          open: money(forecast.reduce((n, m2) => n + m2.open_value, 0)),
          weighted: money(forecast.reduce((n, m2) => n + m2.weighted_value, 0)),
          won: money(forecast.reduce((n, m2) => n + m2.won_value, 0)),
        },
        note: "Weighted value is each deal's value multiplied by the probability "
            + "of its stage. It is a forecast, not an order book.",
      });
      return;
    }

    if (tab === "funnel" && funnel) {
      printDocument(head, {
        kind: "Conversion funnel",
        meta: [
          { label: "Prepared", value: today },
          { label: "Disqualified", value: String(funnel.disqualified) },
          { label: "Lead to customer",
            value: `${funnel.lead_to_customer_rate}%`, strong: true },
        ],
        columns: [
          { key: "stage", label: "Stage" },
          { key: "count", label: "At this stage", numeric: true, width: "30mm" },
          { key: "conversion", label: "Carried forward", numeric: true, width: "32mm" },
        ],
        rows: funnel.stages.map((st) => ({
          stage: st.stage, count: String(st.count),
          conversion: `${st.conversion}%`,
        })),
        note: "Carried forward is the share of the previous stage that reached "
            + "this one.",
      });
      return;
    }

    if (tab === "owners" && owners.length) {
      printDocument(head, {
        kind: "Performance by owner",
        meta: [
          { label: "Prepared", value: today },
          { label: "People", value: String(owners.length) },
          { label: "Won",
            value: money(owners.reduce((n, o) => n + o.won_value, 0)),
            strong: true },
        ],
        columns: [
          { key: "name", label: "Owner" },
          { key: "open", label: "Open deals", numeric: true, width: "24mm" },
          { key: "pipeline", label: "Pipeline", numeric: true, width: "28mm" },
          { key: "weighted", label: "Weighted", numeric: true, width: "28mm" },
          { key: "won", label: "Won", numeric: true, width: "28mm" },
          { key: "rate", label: "Win rate", numeric: true, width: "22mm" },
          { key: "overdue", label: "Overdue", numeric: true, width: "22mm" },
        ],
        rows: owners.map((o) => ({
          name: o.name, open: String(o.open_deals),
          pipeline: money(o.pipeline_value), weighted: money(o.weighted_value),
          won: money(o.won_value), rate: `${o.win_rate}%`,
          overdue: String(o.overdue_tasks),
        })),
        totals: {
          name: "Total",
          open: String(owners.reduce((n, o) => n + o.open_deals, 0)),
          pipeline: money(owners.reduce((n, o) => n + o.pipeline_value, 0)),
          weighted: money(owners.reduce((n, o) => n + o.weighted_value, 0)),
          won: money(owners.reduce((n, o) => n + o.won_value, 0)),
          overdue: String(owners.reduce((n, o) => n + o.overdue_tasks, 0)),
        },
      });
      return;
    }

    if (tab === "campaigns" && roi.length) {
      printDocument(head, {
        kind: "Campaign returns",
        meta: [
          { label: "Prepared", value: today },
          { label: "Campaigns", value: String(roi.length) },
          { label: "Won from campaigns",
            value: money(roi.reduce((n, c) => n + c.won_value, 0)), strong: true },
        ],
        columns: [
          { key: "name", label: "Campaign" },
          { key: "channel", label: "Channel", width: "24mm" },
          { key: "sent", label: "Sent", numeric: true, width: "20mm" },
          { key: "leads", label: "Leads", numeric: true, width: "20mm" },
          { key: "rate", label: "Response", numeric: true, width: "24mm" },
          { key: "pipeline", label: "Pipeline", numeric: true, width: "28mm" },
          { key: "won", label: "Won", numeric: true, width: "28mm" },
        ],
        rows: roi.map((c) => ({
          name: c.name, channel: c.channel, sent: String(c.sent),
          leads: String(c.leads), rate: `${c.response_rate}%`,
          pipeline: money(c.pipeline_value), won: money(c.won_value),
        })),
        totals: {
          name: "Total",
          sent: String(roi.reduce((n, c) => n + c.sent, 0)),
          leads: String(roi.reduce((n, c) => n + c.leads, 0)),
          pipeline: money(roi.reduce((n, c) => n + c.pipeline_value, 0)),
          won: money(roi.reduce((n, c) => n + c.won_value, 0)),
        },
      });
      return;
    }

    toast.warn("There is nothing on this tab to print yet.");
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Revenue Intelligence</h1>
          <div className="sub">Forecast, conversion economics, rep performance and campaign attribution</div>
        </div>
        <button className="secondary" onClick={printTab}>Print report</button>
      </div>

      <div className="pill-tabs">
        {TABS.map(([t, label]) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{label}</button>
        ))}
      </div>

      {tab === "forecast" && (
        <>
          <div className="grid cols-4">
            <div className="card stat hero">
              <div className="label">Open pipeline</div>
              <div className="value">{money(totals.open)}</div>
              <div className="hint">next six months</div>
            </div>
            <div className="card stat">
              <div className="label">Weighted forecast</div>
              <div className="value">{money(totals.weighted)}</div>
              <div className="hint">
                {totals.open ? Math.round((totals.weighted / totals.open) * 100) : 0}% of open value
              </div>
            </div>
            <div className="card stat">
              <div className="label">Closed won</div>
              <div className="value">{money(totals.won)}</div>
              <div className="hint">booked in period</div>
            </div>
            <div className="card stat">
              <div className="label">Deals in play</div>
              <div className="value">{totals.deals}</div>
              <div className="hint">with an expected close date</div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Expected close by month</h3>
              <Legend items={[
                { key: "Closed won", colour: SERIES[0] },
                { key: "Open pipeline", colour: SERIES[2] },
                { key: "Weighted", colour: SERIES[0], dashed: true },
              ]} />
            </div>
            <ColumnChart
              format={compact}
              markerLabel="weighted"
              columns={forecast.map((f) => ({
                label: f.month,
                marker: f.weighted_value,
                segments: [
                  { key: "Closed won", value: f.won_value, colour: SERIES[0] },
                  { key: "Open pipeline", value: f.open_value, colour: SERIES[2] },
                ],
              }))}
            />
            <table>
              <thead><tr><th>Month</th><th className="num">Deals</th><th className="num">Open</th>
                <th className="num">Weighted</th><th className="num">Won</th><th className="num">Coverage</th></tr></thead>
              <tbody>
                {forecast.map((f) => (
                  <tr key={f.month}>
                    <td><b>{f.month}</b></td>
                    <td className="num">{f.deals}</td>
                    <td className="num">{money(f.open_value)}</td>
                    <td className="num">{money(f.weighted_value)}</td>
                    <td className="num">{money(f.won_value)}</td>
                    <td className="num">
                      {f.weighted_value ? `${Math.round((f.open_value / f.weighted_value) * 10) / 10}×` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {loading && forecast.length === 0 && <TableSkeleton cols={4} rows={4} />}
            {!loading && forecast.length === 0 && (
              <div className="empty">
                <b>No dated opportunities to forecast</b>
                <p>
                  A forecast is built from deals with an expected close date.
                  Give the open ones a date and they will appear here.
                </p>
              </div>
            )}
          </div>
        </>
      )}

      {tab === "funnel" && funnel && (
        <>
          <div className="grid cols-3">
            <div className="card stat hero">
              <div className="label">Lead → customer</div>
              <div className="value">{funnel.lead_to_customer_rate}%</div>
              <div className="hint">end-to-end conversion</div>
            </div>
            <div className="card stat">
              <div className="label">Disqualified</div>
              <div className="value">{funnel.disqualified}</div>
              <div className="hint">removed before conversion</div>
            </div>
            <div className="card stat">
              <div className="label">Biggest drop-off</div>
              <div className="value" style={{ fontSize: 22 }}>{worstDrop.from}</div>
              <div className="hint">{worstDrop.lost} lost at this step</div>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>Conversion funnel</h3></div>
            <FunnelChart stages={funnel.stages} />
          </div>
        </>
      )}

      {tab === "owners" && (
        <>
          <div className="card">
            <div className="card-head">
              <h3>Pipeline by rep</h3>
              <Legend items={[
                { key: "Open pipeline", colour: SERIES[0] },
                { key: "Closed won", colour: SERIES[2] },
              ]} />
            </div>
            {/* The same two slots the legend above draws from, passed in rather
                than left to the stylesheet. That mismatch is what made these
                charts look wrong: the key said blue and green, the bars were
                black and pink. */}
            <BarList
              format={money}
              colours={[SERIES[0], SERIES[2]]}
              labels={["Open pipeline", "Closed won"]}
              rows={owners.map((o) => ({
                label: o.name,
                sub: `${o.role} · ${o.open_deals} open · ${o.win_rate}% win rate`,
                primary: o.pipeline_value,
                secondary: o.won_value,
              }))}
            />
            {owners.length === 0 && <div className="empty">No users to report on</div>}
          </div>

          <div className="card">
            <div className="card-head"><h3>Workload &amp; quality</h3></div>
            <table>
              <thead>
                <tr><th>Rep</th><th className="num">Open deals</th><th className="num">Pipeline</th>
                  <th className="num">Weighted</th><th className="num">Won</th><th className="num">Win rate</th>
                  <th className="num">Leads</th><th className="num">Cases</th><th className="num">Overdue</th></tr>
              </thead>
              <tbody>
                {owners.map((o) => (
                  <tr key={o.user_id}>
                    <td><b>{o.name}</b><div className="muted">{o.role}</div></td>
                    <td className="num">{o.open_deals}</td>
                    <td className="num">{money(o.pipeline_value)}</td>
                    <td className="num">{money(o.weighted_value)}</td>
                    <td className="num">{money(o.won_value)} <span className="muted">({o.won_count})</span></td>
                    <td className="num">{o.win_rate}%</td>
                    <td className="num">{o.open_leads}</td>
                    <td className="num">{o.open_tickets}</td>
                    <td className="num">
                      {o.overdue_tasks > 0 ? <span className="badge danger">{o.overdue_tasks}</span> : 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "campaigns" && (
        <>
          <div className="grid cols-2">
            <div className="card">
              <div className="card-head"><h3>Pipeline sourced by channel</h3></div>
              <Donut slices={channelMix} format={compact}
                     empty="No attributed pipeline yet. Campaigns have not sourced a deal." />
            </div>
            <div className="card">
              <div className="card-head">
                <h3>Pipeline by campaign</h3>
                {/* Two series, so a legend is not optional. */}
                <Legend items={[
                  { key: "Pipeline sourced", colour: SERIES[0] },
                  { key: "Closed won", colour: SERIES[2] },
                ]} />
              </div>
              <BarList
                format={money}
                colours={[SERIES[0], SERIES[2]]}
                labels={["Pipeline sourced", "Closed won"]}
                rows={roi.map((c) => ({
                  label: c.name,
                  sub: `${c.channel.toUpperCase()} · ${c.sent} sent · ${c.response_rate}% response`,
                  primary: c.pipeline_value,
                  secondary: c.won_value,
                }))}
              />
              {roi.length === 0 && <div className="empty">No campaigns to attribute yet</div>}
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>Attribution detail</h3></div>
            <table>
              <thead>
                <tr><th>Campaign</th><th>Channel</th><th className="num">Sent</th><th className="num">Leads</th>
                  <th className="num">Response</th><th className="num">Converted</th><th className="num">Opportunities</th>
                  <th className="num">Pipeline</th><th className="num">Won</th></tr>
              </thead>
              <tbody>
                {roi.map((c) => (
                  <tr key={c.campaign_id}>
                    <td><b>{c.name}</b><div className="muted">{c.segment.replace(/_/g, " ")}</div></td>
                    <td>{c.channel.toUpperCase()}</td>
                    <td className="num">{c.sent}</td>
                    <td className="num">{c.leads}</td>
                    <td className="num">{c.response_rate}%</td>
                    <td className="num">{c.converted_leads}</td>
                    <td className="num">{c.opportunities}</td>
                    <td className="num">{money(c.pipeline_value)}</td>
                    <td className="num">{money(c.won_value)}</td>
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
