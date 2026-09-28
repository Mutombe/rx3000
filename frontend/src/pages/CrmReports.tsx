import { useEffect, useMemo, useState } from "react";
import { useToast } from "../components/Toast";
import { useSearchParams } from "react-router-dom";
import { api, money, errorText  } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { BarList, ColumnChart, Donut, FunnelChart, Legend, useSeries } from "../components/charts";
import { CampaignROI, ForecastMonth, FunnelReport, OwnerReport } from "../types";
import { Block, Figure, GhostRows } from "../components/Skeleton";
import { TabStrip } from "../components/PageTabs";
import { Printer } from "@phosphor-icons/react";
import PageHead from "../components/PageHead";
import ExportButton from "../components/ExportButton";
import Th from "../components/Th";

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
  /* Null until the tab's own request answers, and an empty array once it has.
     These were all `[]` from the first frame, which made "no campaigns to
     attribute yet" and "no users to report on" true statements about a request
     that had not been sent. A report cannot say there is nothing until it has
     been told. */
  const [forecast, setForecast] = useState<ForecastMonth[] | null>(null);
  const [funnel, setFunnel] = useState<FunnelReport | null>(null);
  const [owners, setOwners] = useState<OwnerReport[] | null>(null);
  const [roi, setRoi] = useState<CampaignROI[] | null>(null);
  // Follows the theme, so the charts repaint rather than keeping the light hues
  // on a dark surface.
  const SERIES = useSeries();
  const toast = useToast();

  useEffect(() => {
    /* A failed read sets the tab's state to an empty answer rather than
       leaving it null, because null is "still coming" and a skeleton that
       never resolves is the one failure nobody reports. The toast says what
       went wrong; the tab then says it has nothing. */
    if (tab === "forecast") api.get<ForecastMonth[]>("/api/crm/reports/forecast?months=6").then(setForecast)
      .catch((e) => { setForecast([]); toast.error(errorText(e)); });
    if (tab === "funnel") api.get<FunnelReport>("/api/crm/reports/funnel").then(setFunnel).catch((e) => toast.error(errorText(e)));
    if (tab === "owners") api.get<OwnerReport[]>("/api/crm/reports/by-owner").then(setOwners)
      .catch((e) => { setOwners([]); toast.error(errorText(e)); });
    if (tab === "campaigns") api.get<CampaignROI[]>("/api/crm/reports/campaign-roi").then(setRoi)
      .catch((e) => { setRoi([]); toast.error(errorText(e)); });
  }, [tab]);

  const totals = useMemo(() => ({
    open: (forecast ?? []).reduce((s, f) => s + f.open_value, 0),
    weighted: (forecast ?? []).reduce((s, f) => s + f.weighted_value, 0),
    won: (forecast ?? []).reduce((s, f) => s + f.won_value, 0),
    deals: (forecast ?? []).reduce((s, f) => s + f.deals, 0),
  }), [forecast]);

  const channelMix = useMemo(() => {
    const byChannel = new Map<string, number>();
    (roi ?? []).forEach((c) => byChannel.set(c.channel, (byChannel.get(c.channel) ?? 0) + c.pipeline_value));

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
    // Empty rather than "none": where no stage loses more than another the
    // tile says so in a sentence, below, rather than printing a word that
    // reads as the name of a stage.
    let worst = { from: "", lost: 0 };
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

    if (tab === "forecast" && forecast?.length) {
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

    if (tab === "owners" && owners?.length) {
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

    if (tab === "campaigns" && roi?.length) {
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
      <PageHead
        title="Revenue Intelligence"
        sub="Forecast, conversion economics, rep performance and campaign attribution"
        // The forecast, in the spreadsheet a board paper is built from.
        take={<ExportButton dataset="deals" />}
        also={
          <button className="btn secondary" onClick={printTab}>
            <Printer size={14} /> Print report
          </button>
        }
      />

      <TabStrip>
        {TABS.map(([t, label]) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{label}</button>
        ))}
      </TabStrip>

      {tab === "forecast" && (
        <>
          {/* SCOPED LOADING.
           *
           * The four labels and three of the hints are written here and are
           * the same on every visit. They used to be drawn over a total of
           * nought, which is worse than a skeleton: a forecast that says
           * "Open pipeline 0" while it is still asking has told a board
           * meeting something untrue. Only the figures wait. */}
          <div className="grid cols-4">
            <div className="card stat hero">
              <div className="label">Open pipeline</div>
              <div className="value">
                <Figure ready={!!forecast} w="9ch">{money(totals.open)}</Figure>
              </div>
              <div className="hint">next six months</div>
            </div>
            <div className="card stat">
              <div className="label">Weighted forecast</div>
              <div className="value">
                <Figure ready={!!forecast} w="9ch">{money(totals.weighted)}</Figure>
              </div>
              <div className="hint">
                <Figure ready={!!forecast} w="3ch">
                  {totals.open ? Math.round((totals.weighted / totals.open) * 100) : 0}
                </Figure>% of open value
              </div>
            </div>
            <div className="card stat">
              <div className="label">Closed won</div>
              <div className="value">
                <Figure ready={!!forecast} w="9ch">{money(totals.won)}</Figure>
              </div>
              <div className="hint">booked in period</div>
            </div>
            <div className="card stat">
              <div className="label">Deals in play</div>
              <div className="value">
                <Figure ready={!!forecast} w="3ch">{totals.deals}</Figure>
              </div>
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
            {/* Three arms, in this order: the plot area and the ghost rows
                while the months are still coming, the empty answer once they
                have come and there are none, and the report itself. The head
                is written a few lines down, so it is drawn for real either
                way and a reader waiting on a slow answer can at least see
                what they are waiting for. */}
            {!forecast ? (
              <>
                <Block h={230} round="md" />
                <table>
                  <thead><tr><Th>Month</Th><Th className="num">Deals</Th><Th className="num">Open</Th>
                    <Th className="num">Weighted</Th><Th className="num">Won</Th><Th className="num">Coverage</Th></tr></thead>
                  <GhostRows cols={6} rows={6} rowHeight={45}
                             widths={["10ch", "4ch", "9ch", "9ch", "9ch", "5ch"]} />
                </table>
              </>
            ) : forecast.length === 0 ? (
              <div className="empty">
                <b>No dated opportunities to forecast</b>
                <p>
                  A forecast is built from deals with an expected close date.
                  Give the open ones a date and they will appear here.
                </p>
              </div>
            ) : (
              <>
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
                  <thead><tr><Th>Month</Th><Th className="num">Deals</Th><Th className="num">Open</Th>
                    <Th className="num">Weighted</Th><Th className="num">Won</Th><Th className="num">Coverage</Th></tr></thead>
                  <tbody>
                    {forecast.map((f) => (
                      <tr key={f.month}>
                        <td><b>{f.month}</b></td>
                        <td className="num">{f.deals}</td>
                        <td className="num">{money(f.open_value)}</td>
                        <td className="num">{money(f.weighted_value)}</td>
                        <td className="num">{money(f.won_value)}</td>
                        <td className="num">
                          {f.weighted_value
                            ? `${Math.round((f.open_value / f.weighted_value) * 10) / 10}×`
                            : "nothing weighted"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </>
      )}

      {tab === "funnel" && (
        <>
          {/* The three labels, the hints and the panel heading below are all
              written here. They used to sit behind `funnel &&`, so this tab
              opened as a blank page and then dropped a whole screen into
              place at once. */}
          <div className="grid cols-3">
            <div className="card stat hero">
              <div className="label">Lead → customer</div>
              <div className="value">
                <Figure ready={!!funnel} w="4ch">
                  {funnel && `${funnel.lead_to_customer_rate}%`}
                </Figure>
              </div>
              <div className="hint">end-to-end conversion</div>
            </div>
            <div className="card stat">
              <div className="label">Disqualified</div>
              <div className="value">
                <Figure ready={!!funnel} w="3ch">{funnel?.disqualified}</Figure>
              </div>
              <div className="hint">removed before conversion</div>
            </div>
            <div className="card stat">
              <div className="label">Biggest drop-off</div>
              {/* A stage name rather than a number, so the block that stands
                  in for it is the width of a stage name. */}
              <div className="value" style={{ fontSize: 22 }}>
                <Figure ready={!!funnel} w="12ch">
                  {funnel && (worstDrop.from
                    ? worstDrop.from
                    : <span className="muted">No stage loses more than another</span>)}
                </Figure>
              </div>
              <div className="hint">
                <Figure ready={!!funnel} w="3ch">{funnel && worstDrop.lost}</Figure>
                {" "}lost at this step
              </div>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>Conversion funnel</h3></div>
            {funnel
              ? <FunnelChart stages={funnel.stages} />
              : <Block h={220} round="md" />}
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
            {/* "No users to report on" was reachable before the request had
                answered, which told a sales manager their team did not exist.
                Ghost, then the empty answer, then the bars. */}
            {!owners ? (
              <Block h={180} round="md" />
            ) : owners.length === 0 ? (
              <div className="empty">No users to report on</div>
            ) : (
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
            )}
          </div>

          <div className="card">
            <div className="card-head"><h3>Workload &amp; quality</h3></div>
            {/* Nine column names, every one of them written here, so the head
                is real and the rows alone are ghosted. A rep's name carries
                their role underneath, so that column ghosts with a second
                line or the table lifts when the people land. */}
            <table>
              <thead>
                <tr><Th>Rep</Th><Th className="num">Open deals</Th><Th className="num">Pipeline</Th>
                  <Th className="num">Weighted</Th><Th className="num">Won</Th><Th className="num">Win rate</Th>
                  <Th className="num">Leads</Th><Th className="num">Cases</Th><Th className="num">Overdue</Th></tr>
              </thead>
              {!owners ? (
                <GhostRows cols={9} rows={4} secondLine={[0]}
                           widths={["16ch", "4ch", "9ch", "9ch", "9ch",
                                    "5ch", "4ch", "4ch", "4ch"]} />
              ) : (
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
              )}
            </table>
          </div>
        </>
      )}

      {tab === "campaigns" && (
        <>
          <div className="grid cols-2">
            <div className="card">
              <div className="card-head"><h3>Pipeline sourced by channel</h3></div>
              {/* The donut's own empty sentence is an answer about the
                  campaigns, so it waits until the campaigns have been read. */}
              {roi
                ? <Donut slices={channelMix} format={compact}
                         empty="No attributed pipeline yet. Campaigns have not sourced a deal." />
                : <Block w={168} h={168} round="pill" />}
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
              {!roi ? (
                <Block h={180} round="md" />
              ) : roi.length === 0 ? (
                <div className="empty">No campaigns to attribute yet</div>
              ) : (
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
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>Attribution detail</h3></div>
            <table>
              <thead>
                <tr><Th>Campaign</Th><Th>Channel</Th><Th className="num">Sent</Th><Th className="num">Leads</Th>
                  <Th className="num">Response</Th><Th className="num">Converted</Th><Th className="num">Opportunities</Th>
                  <Th className="num">Pipeline</Th><Th className="num">Won</Th></tr>
              </thead>
              {!roi ? (
                /* A campaign carries its segment underneath, so that column
                   ghosts with a second line. */
                <GhostRows cols={9} rows={4} secondLine={[0]}
                           widths={["18ch", "6ch", "5ch", "4ch", "5ch",
                                    "5ch", "5ch", "9ch", "9ch"]} />
              ) : (
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
              )}
            </table>
          </div>
        </>
      )}
    </>
  );
}
