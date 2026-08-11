import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, money } from "../api";
import { Block, TableSkeleton } from "../components/Skeleton";
import { Dashboard as Dash } from "../types";

export default function Dashboard() {
  const [data, setData] = useState<Dash | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Dash>("/api/reports/dashboard").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error)
    return (
      <div className="page">
        {/* A page that could not load says so in place. A toast over a
            blank screen tells nobody what they were looking at. */}
        <div className="alert error">{error}</div>
        <p className="muted pad">
          Nothing was loaded for this record. Check the connection and try again.
        </p>
      </div>
    );
  if (!data)
    return (
      <div aria-busy="true">
        {/* The title and the New Sale button are known before the fetch and are
            rendered for real. Only the pharmacy name in the subtitle comes from
            the response, so only that ghosts — and the till stays one click away
            while the figures load. */}
        <div className="page-head">
          <div>
            <h1>Command Centre</h1>
            <div className="sub"><Block w="26ch" h={12} /></div>
          </div>
          <Link to="/pos" className="btn">New Sale</Link>
        </div>
        <div className="grid cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className={`card stat${i === 0 ? " hero" : ""}`}>
              <div className="label">{["Sales today", "Scripts dispensed today", "Repeats due (7 days)", "Low stock lines"][i]}</div>
              <div className="value"><Block w="55%" h={28} /></div>
              <div className="hint"><Block w="70%" h={11} /></div>
            </div>
          ))}
        </div>
        <div className="card sk-card">
          <Block w="16ch" h={14} />
          <TableSkeleton cols={4} rows={5} />
        </div>
        <div className="card sk-card">
          <Block w="14ch" h={14} />
          <Block w="100%" />
          <Block w="80%" />
        </div>
      </div>
    );

  const max = Math.max(...data.week_sales.map((d) => d.total), 1);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Command Centre</h1>
          <div className="sub">{data.pharmacy_name} — live operational overview</div>
        </div>
        <Link to="/pos" className="btn">New Sale</Link>
      </div>

      <div className="grid cols-4">
        <div className="card stat hero">
          <div className="label">Sales today</div>
          <div className="value accent">{money(data.sales_today_total, data.currency)}</div>
          <div className="hint">{data.sales_today_count} transactions</div>
        </div>
        <div className="card stat">
          <div className="label">Scripts dispensed today</div>
          <div className="value">{data.scripts_today}</div>
          <div className="hint"><Link to="/dispense">Open dispensary →</Link></div>
        </div>
        <div className="card stat">
          <div className="label">Repeats due (7 days)</div>
          <div className="value">{data.repeats_due_count}</div>
          <div className="hint"><Link to="/reminders">Manage reminders →</Link></div>
        </div>
        <div className="card stat">
          <div className="label">Low stock lines</div>
          <div className="value" style={{ color: data.low_stock_count ? "var(--danger)" : undefined }}>
            {data.low_stock_count}
          </div>
          <div className="hint"><Link to="/orders">Generate orders →</Link></div>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 2 }}>
        <div className="card">
          <h3>Sales — last 7 days</h3>
          {data.week_sales.length === 0 ? (
            <div className="empty">No sales yet this week</div>
          ) : (
            <div className="chart-bars" style={{ marginBottom: 26 }}>
              {data.week_sales.map((d) => (
                <div key={d.day} className="bar" style={{ height: `${(d.total / max) * 100}%` }}>
                  <em>{money(d.total, data.currency)}</em>
                  <span>{d.day.slice(5)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <h3>Attention needed</h3>
          <table>
            <tbody>
              <tr>
                <td>Pending dispensary sales awaiting payment</td>
                <td className="num"><span className={`badge ${data.pending_sales ? "warn" : "ok"}`}>{data.pending_sales}</span></td>
              </tr>
              <tr>
                <td>Reminder messages queued for delivery</td>
                <td className="num"><span className={`badge ${data.messages_pending ? "warn" : "ok"}`}>{data.messages_pending}</span></td>
              </tr>
              <tr>
                <td>Stock lines at or below reorder level</td>
                <td className="num"><span className={`badge ${data.low_stock_count ? "danger" : "ok"}`}>{data.low_stock_count}</span></td>
              </tr>
              <tr>
                <td>Repeat prescriptions due within 7 days</td>
                <td className="num"><span className="badge">{data.repeats_due_count}</span></td>
              </tr>
              <tr>
                <td>Batches expiring within 90 days <Link to="/stock">→ review</Link></td>
                <td className="num"><span className={`badge ${data.expiring_soon_count ? "warn" : "ok"}`}>{data.expiring_soon_count}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
