/** Is each funder paying us, in full, on time.
 *
 *  A remittance answers "what did this deposit cover". This answers the
 *  question above it, and it is three questions rather than one:
 *
 *    **paying** — how much of what was claimed ever arrives
 *    **in full** — where the difference went: short-paid, refused, or held
 *    **on time** — days from submission to money, against the terms the scheme
 *    itself states, so "late" is measured against their promise rather than an
 *    opinion
 *
 *  A pharmacy carries a slow funder for sixty days without noticing, because
 *  each claim is small and the delay is invisible one claim at a time. It
 *  becomes visible when the working capital has gone, and by then the
 *  conversation with the funder is about a number nobody has kept.
 *
 *  **Held is not refused, and this screen exists largely to say so.** A funder
 *  can pay a claim, refuse it, or hold it pending a query — and to the money,
 *  held and refused look identical: nothing arrived. Everything here used to
 *  read the money and call both a rejection, which sent held claims to the
 *  write-off pile or to a patient whose scheme was always going to pay.
 */
import { useEffect, useState } from "react";
import { Info, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import SectionNav from "../components/SectionNav";
import Select from "../components/Select";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { RECON_TABS } from "../reconTabs";

interface Funder {
  funder_id: string; funder: string;
  advices: number; lines: number;
  claimed: number; paid: number;
  short: number; rejected: number; held: number;
  short_lines: number; rejected_lines: number; held_lines: number;
  average_days: number | null; slowest_days: number | null;
  promised_days: number | null; late_by: number | null;
  paying_rate: number | null; shortfall: number;
  last_paid: string | null; says: string;
}
interface Report {
  days: number; funders: Funder[];
  claimed: number; paid: number; shortfall: number; held: number;
  paying_rate: number | null; headline: string;
}
interface Held {
  count: number; value: number;
  lines: { id: number; remittance_number: string; funder_id: string;
           claim_reference: string; member_name: string; policy_number: string;
           service_date: string | null; amount_claimed: number;
           reason_code: string; reason: string }[];
}

type Tab = "funders" | "held";

export default function Settlements() {
  const [report, setReport] = useState<Report | null>(null);
  const [held, setHeld] = useState<Held | null>(null);
  const [days, setDays] = useState(180);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "funders", label: "By funder",
      hint: "Paying, in full, on time — three separate questions" },
    { key: "held", label: "Held pending a query", count: held?.count,
      hint: "Not refused. These pay when the query is answered" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "funders");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<Report>(`/api/settlements?days=${days}`),
      api.get<Held>("/api/settlements/held?limit=200"),
    ])
      .then(([r, h]) => { setReport(r); setHeld(h); })
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, [days]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Settlements</h1>
          <p className="muted">
            {report?.headline ?? "What each funder actually paid, and when."}
          </p>
        </div>
        <div className="page-actions">
          <SectionNav tabs={RECON_TABS} end="/reconciliation" />
          <Select value={String(days)} onChange={(v) => setDays(Number(v))}
            options={[90, 180, 365].map((d) => ({
              value: String(d), label: `Last ${d} days` }))} />
        </div>
      </header>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      <Refreshable loading={loading} hasData={!!report}
        skeleton={<TableSkeleton cols={6} rows={5} />}>

        {tab === "funders" && report && (
          <>
            <div className="wc-bands">
              <div className="wl-stat">
                <b>{money(report.claimed)}</b><span>claimed</span>
              </div>
              <div className="wl-stat">
                <b className="tone-ok">{money(report.paid)}</b><span>settled</span>
              </div>
              <div className={`wl-stat${report.shortfall ? " wc-abandoned" : ""}`}>
                <b className={report.shortfall ? "tone-danger" : undefined}>
                  {money(report.shortfall)}
                </b>
                <span>short-paid or refused</span>
              </div>
              <div className={`wl-stat${report.held ? " wc-stale" : ""}`}>
                <b>{money(report.held)}</b>
                {/* Its own figure, deliberately not inside the shortfall. A
                    held claim is not the patient's to pay and not the shop's
                    to write off — it is still in play. */}
                <span>held pending a query</span>
              </div>
              <div className="wl-stat">
                <b>{report.paying_rate !== null ? `${report.paying_rate}%` : "—"}</b>
                <span>of what is claimed arrives</span>
              </div>
            </div>

            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Funder</th>
                    <th className="num">Claimed</th>
                    <th className="num">Settled</th>
                    <th className="num">Pays</th>
                    <th className="num">Takes</th>
                    <th className="num">Held</th>
                    <th>What that means</th>
                  </tr>
                </thead>
                <tbody>
                  {report.funders.map((f) => (
                    <tr key={f.funder_id}
                        className={(f.paying_rate ?? 100) < 85
                          || (f.late_by ?? 0) > 14 ? "row-flag" : undefined}>
                      <td>
                        <b>{f.funder}</b>
                        <div className="muted small mono">{f.funder_id}</div>
                      </td>
                      <td className="num mono">{money(f.claimed)}</td>
                      <td className="num mono">{money(f.paid)}</td>
                      <td className="num">
                        {f.paying_rate !== null ? (
                          <b className={f.paying_rate < 85 ? "tone-danger"
                            : f.paying_rate < 95 ? "tone-warn" : "tone-ok"}>
                            {f.paying_rate}%
                          </b>
                        ) : <span className="muted">—</span>}
                      </td>
                      <td className="num">
                        {f.average_days !== null ? (
                          <>
                            {f.average_days}d
                            {/* Against their own stated terms, not against an
                                opinion about what is reasonable. */}
                            {f.promised_days && (
                              <div className={`muted small${
                                (f.late_by ?? 0) > 7 ? " tone-danger" : ""}`}>
                                {(f.late_by ?? 0) > 0
                                  ? `${f.late_by} beyond their ${f.promised_days}`
                                  : `within their ${f.promised_days}`}
                              </div>
                            )}
                          </>
                        ) : <span className="muted">—</span>}
                      </td>
                      <td className="num mono">
                        {f.held
                          ? <>{money(f.held)}
                              <div className="muted small">{f.held_lines} line(s)</div></>
                          : <span className="muted">—</span>}
                      </td>
                      <td className="wrap muted small">{f.says}</td>
                    </tr>
                  ))}
                  {!report.funders.length && (
                    <tr><td colSpan={7} className="muted pad">
                      No remittances in this period, so nothing can be said
                      about who pays and how fast.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

        {tab === "held" && held && (
          <>
            <div className="alert warn">
              <Info size={16} weight="fill" />
              <span>
                <b>These are not rejections.</b> The funder is holding them
                pending a query, a document or a review, and they pay when it is
                answered. They are kept out of the shortfall for exactly that
                reason — a held claim billed to a patient is a bill for
                something their scheme was always going to settle.
              </span>
            </div>

            <div className="wc-bands">
              <div className="wl-stat">
                <b>{held.count}</b><span>claims held</span>
              </div>
              <div className="wl-stat">
                <b>{money(held.value)}</b><span>waiting on an answer</span>
              </div>
            </div>

            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Member</th><th>Claim</th><th>Service date</th>
                    <th className="num">Claimed</th><th>Why it is held</th>
                  </tr>
                </thead>
                <tbody>
                  {held.lines.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <b>{l.member_name || "—"}</b>
                        <div className="muted small mono">{l.policy_number}</div>
                      </td>
                      <td className="mono small">
                        {l.claim_reference || "—"}
                        <div className="muted">{l.remittance_number}</div>
                      </td>
                      <td>
                        {l.service_date ? fmtDate(l.service_date)
                          : <span className="muted">—</span>}
                      </td>
                      <td className="num mono">{money(l.amount_claimed)}</td>
                      <td className="wrap">
                        <span className="badge warn">{l.reason_code}</span>
                        <div className="muted small">{l.reason}</div>
                      </td>
                    </tr>
                  ))}
                  {!held.lines.length && (
                    <tr><td colSpan={5} className="muted pad">
                      Nothing is being held. Every claim has been paid, refused
                      or short-paid.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Refreshable>
    </div>
  );
}
