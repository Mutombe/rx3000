import { useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { api, money, errorText  } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import ReportCatalogue from "../components/ReportCatalogue";
import { Patient } from "../types";
import Pagination from "../components/Pagination";
import { useClientPage } from "../hooks/useClientPage";
import ReportChart from "../components/ReportChart";
import { ChartBar, Table } from "@phosphor-icons/react";
import { TableSkeleton } from "../components/Skeleton";

type Tab = "all" | "daily" | "vat" | "valuation" | "tax";

export default function Reports() {
  const TABS: TabDef<Tab>[] = [
    { key: "all", label: "All reports",
      hint: "Every report in the system, by module" },
    { key: "daily", label: "Daily totals" },
    { key: "vat", label: "VAT / tax" },
    { key: "valuation", label: "Stock valuation" },
    { key: "tax", label: "Patient tax statement" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [daily, setDaily] = useState<any[]>([]);
  const [vat, setVat] = useState<any>(null);
  const [valuation, setValuation] = useState<any>(null);
  const [view, setView] = useState<"table" | "chart">("table");
  // Totals come from the endpoint, over every line; only the render is paged.
  const valuationRows = useClientPage<any>(valuation?.lines ?? [], 25);
  const [patientQ, setPatientQ] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [taxReport, setTaxReport] = useState<any>(null);
  const toast = useToast();
  const [loading, setLoading] = useState(true);

  const range = `date_from=${dateFrom}&date_to=${dateTo}`;

  useEffect(() => {
    if (tab === "daily") api.get<any[]>(`/api/reports/daily-totals?${range}`).then(setDaily)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
    if (tab === "vat") api.get(`/api/reports/vat?${range}`).then(setVat).catch((e) => toast.error(errorText(e)));
    if (tab === "valuation") api.get(`/api/reports/stock-valuation`).then(setValuation).catch((e) => toast.error(errorText(e)));
  }, [tab, dateFrom, dateTo]);

  useEffect(() => {
    if (patientQ.length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=6`).then(setPatients);
  }, [patientQ]);

  function loadTax(p: Patient) {
    setPatients([]);
    setPatientQ("");
    api.get(`/api/reports/patient/${p.id}/tax`).then(setTaxReport).catch((e) => toast.error(errorText(e)));
  }

  /** Print what is on the tab, as a document.
   *
   *  One button that printed the whole browser window regardless of which tab
   *  was open, so the takings report, the VAT summary and the stock valuation
   *  all came out as a photograph of a web page with the navigation down the
   *  side. The dataset that leaves now follows the tab, which is the only thing
   *  the button could ever have honestly meant.
   */
  async function printTab() {
    const head = await letterhead();
    const period = { label: "Period",
                     value: `${dateFrom || "last 30 days"}${dateTo ? ` to ${dateTo}` : ""}` };

    if (tab === "daily" && daily.length) {
      const sum = (pick: (d: any) => number) =>
        daily.reduce((n, d) => n + (pick(d) || 0), 0);
      printDocument(head, {
        kind: "Daily takings",
        meta: [period, { label: "Days", value: String(daily.length) },
               { label: "Total", value: money(sum((d) => d.total)), strong: true }],
        columns: [
          { key: "day", label: "Day", width: "26mm" },
          { key: "transactions", label: "Sales", numeric: true, width: "20mm" },
          { key: "cash", label: "Cash", numeric: true, width: "26mm" },
          { key: "card", label: "Card", numeric: true, width: "26mm" },
          { key: "aid", label: "Medical aid", numeric: true, width: "28mm" },
          { key: "vat", label: "VAT", numeric: true, width: "24mm" },
          { key: "total", label: "Total", numeric: true, width: "28mm" },
        ],
        rows: daily.map((d) => ({
          day: d.day, transactions: String(d.transactions),
          cash: money(d.by_method.cash ?? 0), card: money(d.by_method.card ?? 0),
          aid: money(d.by_method.medical_aid ?? 0),
          vat: money(d.vat), total: money(d.total),
        })),
        totals: {
          day: "Total",
          transactions: String(sum((d) => d.transactions)),
          cash: money(sum((d) => d.by_method.cash ?? 0)),
          card: money(sum((d) => d.by_method.card ?? 0)),
          aid: money(sum((d) => d.by_method.medical_aid ?? 0)),
          vat: money(sum((d) => d.vat)),
          total: money(sum((d) => d.total)),
        },
        note: "Paid sales only. A sale dispensed and not yet settled appears on "
            + "the day it is paid, not the day it went out.",
      });
      return;
    }

    if (tab === "vat" && vat) {
      printDocument(head, {
        kind: "VAT summary",
        meta: [{ label: "From", value: vat.date_from },
               { label: "To", value: vat.date_to },
               { label: "Rate", value: `${(vat.vat_rate * 100).toFixed(0)}%` },
               { label: "VAT collected", value: money(vat.vat_collected),
                 strong: true }],
        columns: [{ key: "item", label: "" },
                  { key: "amount", label: "Amount", numeric: true, width: "36mm" }],
        rows: [
          { item: "Sales including VAT", amount: money(vat.sales_inc_vat) },
          { item: "Sales excluding VAT", amount: money(vat.sales_ex_vat) },
          { item: "Transactions", amount: String(vat.transactions) },
        ],
        totals: { item: "VAT collected", amount: money(vat.vat_collected) },
        // Two VAT figures exist in this software and only one is filed. Saying
        // so on the face of the paper is the difference between a summary and
        // a return somebody submits by mistake.
        note: "Worked out from till sales. This is a management summary — the "
            + "return to file is the one under Periods, which is drawn from the "
            + "posted accounts and will differ while anything is unposted.",
      });
      return;
    }

    if (tab === "valuation" && valuation) {
      printDocument(head, {
        kind: "Stock valuation",
        meta: [{ label: "As at", value: new Date().toLocaleDateString() },
               { label: "Lines", value: String(valuation.lines.length) },
               { label: "At retail", value: money(valuation.total_at_retail) },
               { label: "At cost", value: money(valuation.total_at_cost),
                 strong: true }],
        columns: [
          { key: "product", label: "Product" },
          { key: "on_hand", label: "On hand", numeric: true, width: "22mm" },
          { key: "cost", label: "Cost", numeric: true, width: "24mm" },
          { key: "at_cost", label: "Value at cost", numeric: true, width: "30mm" },
          { key: "at_retail", label: "Value at retail", numeric: true, width: "30mm" },
        ],
        // Every line, not the page on screen. A valuation that stops at
        // twenty-five products is not a valuation.
        rows: valuation.lines.map((l: any) => ({
          product: l.product, on_hand: String(l.on_hand),
          cost: money(l.cost_price), at_cost: money(l.value_at_cost),
          at_retail: money(l.value_at_retail),
        })),
        totals: { product: "Total", at_cost: money(valuation.total_at_cost),
                  at_retail: money(valuation.total_at_retail) },
        note: "Valued at the cost last paid for each line. Stock held at a "
            + "branch is included.",
      });
      return;
    }

    toast.warn("There is nothing on this tab to print yet.");
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Analytics</h1>
          <div className="sub">Automated daily totals, VAT, stock valuation and patient tax statements</div>
        </div>
        <button className="secondary" onClick={printTab}>Print report</button>
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {(tab === "daily" || tab === "vat") && (
        <div className="toolbar">
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} style={{ maxWidth: 180 }} />
          <span className="muted">to</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} style={{ maxWidth: 180 }} />
          <span className="muted">(blank = last 30 days)</span>
        </div>
      )}

      {/* One switch, used by both tabs that carry rows. Declared here rather than
          twice, so the two cannot drift into behaving differently. */}
      {(tab === "daily" || tab === "valuation") && (
        <div className="view-switch" role="tablist" aria-label="How to read this">
          {(["table", "chart"] as const).map((v) => (
            <button key={v} role="tab" aria-selected={view === v}
              className={view === v ? "on" : ""} onClick={() => setView(v)}>
              {v === "table" ? <Table size={14} weight="bold" /> : <ChartBar size={14} weight="bold" />}
              {v === "table" ? "Table" : "Chart"}
            </button>
          ))}
        </div>
      )}

      {tab === "all" && <ReportCatalogue />}


      {tab === "daily" && view === "chart" && (
        <div className="card">
          <ReportChart
            format={(n) => money(n)}
            columns={[
              { key: "day", header: "Day", kind: "date", align: "left" },
              { key: "total", header: "Total taken", kind: "money", align: "right", total: true },
              { key: "cash", header: "Cash", kind: "money", align: "right", total: true },
              { key: "card", header: "Card", kind: "money", align: "right", total: true },
              { key: "medical_aid", header: "Medical aid", kind: "money", align: "right", total: true },
              { key: "vat", header: "VAT", kind: "money", align: "right", total: true },
              { key: "transactions", header: "Transactions", kind: "number", align: "right", total: true },
            ]}
            // Flattened here because the API nests the tender split under
            // `by_method`, and the chart reads flat rows like every other report.
            rows={daily.map((d) => ({
              day: d.day, total: d.total, vat: d.vat, transactions: d.transactions,
              cash: d.by_method?.cash ?? 0,
              card: d.by_method?.card ?? 0,
              medical_aid: d.by_method?.medical_aid ?? 0,
            }))}
          />
        </div>
      )}

      {tab === "daily" && view === "table" && (
        <div className="card">
          <table>
            <thead>
              <tr><th>Day</th><th className="num">Transactions</th><th className="num">Cash</th><th className="num">Card</th><th className="num">Medical aid</th><th className="num">VAT</th><th className="num">Total</th></tr>
            </thead>
            <tbody>
              {daily.map((d) => (
                <tr key={d.day}>
                  <td><b>{d.day}</b></td>
                  <td className="num">{d.transactions}</td>
                  <td className="num">{money(d.by_method.cash ?? 0)}</td>
                  <td className="num">{money(d.by_method.card ?? 0)}</td>
                  <td className="num">{money(d.by_method.medical_aid ?? 0)}</td>
                  <td className="num">{money(d.vat)}</td>
                  <td className="num"><b>{money(d.total)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* A takings report that says "no paid sales" while it is still
              fetching them is a report somebody acts on. */}
          {loading && daily.length === 0 && <TableSkeleton cols={5} rows={5} />}
          {!loading && daily.length === 0 && (
            <div className="empty">
              <b>No paid sales in this period</b>
              <p>Widen the dates, or check the till was in use.</p>
            </div>
          )}
        </div>
      )}

      {tab === "vat" && vat && (
        <div className="grid cols-4">
          <div className="card stat hero">
            <div className="label">Sales incl. VAT</div>
            <div className="value">{money(vat.sales_inc_vat)}</div>
            <div className="hint">{vat.date_from} → {vat.date_to}</div>
          </div>
          <div className="card stat">
            <div className="label">Sales excl. VAT</div>
            <div className="value">{money(vat.sales_ex_vat)}</div>
          </div>
          <div className="card stat">
            <div className="label">VAT collected ({(vat.vat_rate * 100).toFixed(0)}%)</div>
            <div className="value">{money(vat.vat_collected)}</div>
          </div>
          <div className="card stat">
            <div className="label">Transactions</div>
            <div className="value">{vat.transactions}</div>
          </div>
        </div>
      )}

      {tab === "valuation" && valuation && (
        <>
          <div className="grid cols-2">
            <div className="card stat hero">
              <div className="label">Stock value at cost</div>
              <div className="value">{money(valuation.total_at_cost)}</div>
            </div>
            <div className="card stat">
              <div className="label">Stock value at retail</div>
              <div className="value">{money(valuation.total_at_retail)}</div>
            </div>
          </div>
          {view === "chart" && (
            <div className="card">
              <ReportChart
                format={(n) => money(n)}
                columns={[
                  { key: "product", header: "Product", kind: "text", align: "left" },
                  { key: "value_at_cost", header: "Value at cost", kind: "money", align: "right", total: true },
                  { key: "value_at_retail", header: "Value at retail", kind: "money", align: "right", total: true },
                  { key: "on_hand", header: "On hand", kind: "number", align: "right", total: true },
                ]}
                rows={valuation.lines}
              />
            </div>
          )}

          <div className="card" hidden={view === "chart"}>
            <table>
              <thead><tr><th>Product</th><th className="num">On hand</th><th className="num">Cost</th><th className="num">Value at cost</th><th className="num">Value at retail</th></tr></thead>
              <tbody>
                {valuationRows.items.map((l: any, i: number) => (
                  <tr key={i}>
                    <td>{l.product}</td>
                    <td className="num">{l.on_hand}</td>
                    <td className="num">{money(l.cost_price)}</td>
                    <td className="num">{money(l.value_at_cost)}</td>
                    <td className="num">{money(l.value_at_retail)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination meta={valuationRows.meta} onPage={valuationRows.setPage} noun="lines" />
          </div>
        </>
      )}

      {tab === "tax" && (
        <>
          <div className="card">
            <h3>Select a patient</h3>
            <input type="search" placeholder="Search patient…" value={patientQ} onChange={(e) => setPatientQ(e.target.value)} />
            {patients.map((p) => (
              <div key={p.id} className="product-pick" onClick={() => loadTax(p)}>
                <span>{p.last_name}, {p.first_name}</span>
                <span className="muted">{p.medical_aid?.name ?? "Private"}</span>
              </div>
            ))}
          </div>
          {taxReport && (
            <div className="card">
              <h3>{taxReport.patient}, medical expenses, {taxReport.tax_year}</h3>
              <div className="grid cols-3" style={{ margin: "14px 0" }}>
                <div className="card stat"><div className="label">Total spent</div><div className="value">{money(taxReport.total_spent)}</div></div>
                <div className="card stat"><div className="label">Medical aid paid</div><div className="value">{money(taxReport.total_medical_aid_paid)}</div></div>
                <div className="card stat hero"><div className="label">Out of pocket</div><div className="value">{money(taxReport.total_out_of_pocket)}</div></div>
              </div>
              <table>
                <thead><tr><th>Date</th><th>Invoice</th><th>Items</th><th className="num">Total</th><th className="num">Aid paid</th><th className="num">Out of pocket</th></tr></thead>
                <tbody>
                  {taxReport.lines.map((l: any, i: number) => (
                    <tr key={i}>
                      <td>{l.date}</td><td className="mono">{l.invoice}</td><td>{l.items.join(", ")}</td>
                      <td className="num">{money(l.total)}</td>
                      <td className="num">{money(l.medical_aid_paid)}</td>
                      <td className="num">{money(l.out_of_pocket)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
