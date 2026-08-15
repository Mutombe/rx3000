import { useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { api, money } from "../api";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import ReportCatalogue from "../components/ReportCatalogue";
import { Patient } from "../types";

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
  const [patientQ, setPatientQ] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [taxReport, setTaxReport] = useState<any>(null);
  const toast = useToast();

  const range = `date_from=${dateFrom}&date_to=${dateTo}`;

  useEffect(() => {
    if (tab === "daily") api.get<any[]>(`/api/reports/daily-totals?${range}`).then(setDaily).catch((e) => toast.error(e.message));
    if (tab === "vat") api.get(`/api/reports/vat?${range}`).then(setVat).catch((e) => toast.error(e.message));
    if (tab === "valuation") api.get(`/api/reports/stock-valuation`).then(setValuation).catch((e) => toast.error(e.message));
  }, [tab, dateFrom, dateTo]);

  useEffect(() => {
    if (patientQ.length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=6`).then(setPatients);
  }, [patientQ]);

  function loadTax(p: Patient) {
    setPatients([]);
    setPatientQ("");
    api.get(`/api/reports/patient/${p.id}/tax`).then(setTaxReport).catch((e) => toast.error(e.message));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Analytics</h1>
          <div className="sub">Automated daily totals, VAT, stock valuation and patient tax statements</div>
        </div>
        <button className="secondary" onClick={() => window.print()}>Print report</button>
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

      {tab === "all" && <ReportCatalogue />}


      {tab === "daily" && (
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
          {daily.length === 0 && <div className="empty">No paid sales in this period</div>}
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
          <div className="card">
            <table>
              <thead><tr><th>Product</th><th className="num">On hand</th><th className="num">Cost</th><th className="num">Value at cost</th><th className="num">Value at retail</th></tr></thead>
              <tbody>
                {valuation.lines.map((l: any, i: number) => (
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
              <h3>{taxReport.patient} — medical expenses, {taxReport.tax_year}</h3>
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
