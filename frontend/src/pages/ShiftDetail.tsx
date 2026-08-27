/** One till session: who had it, what went through it, and what was short.
 *
 *  The cash office listed sessions and a variance and stopped there. A variance
 *  is a question, not an answer, and the only useful next step is the sales
 *  that went through that till while it was open.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useParams } from "react-router-dom";

interface SaleRow {
  id: number; sale_number: string; created_at: string;
  total: number; payment_method: string;
  patient: { id: number | null; name: string };
}
interface Data {
  id: number;
  user: { id: number | null; name: string };
  counted_by: { id: number | null; name: string };
  status: string; opened_at: string; closed_at: string | null;
  opening_float: number; counted_total: number; expected_total: number;
  variance: number; notes: string;
  sale_count: number; sales_value: number; sales: SaleRow[];
}

export default function ShiftDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/shifts/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That till session could not be opened.")));
  }, [id]);

  const over = (d?.variance ?? 0) > 0.005;
  const short = (d?.variance ?? 0) < -0.005;

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Cash Office", to: "/shifts" },
              { label: d ? fmtDateTime(d.opened_at) : "This session" }]}
      eyebrow="Till session"
      title={d ? fmtDateTime(d.opened_at) : ""}
      subtitle={d && <>
        <EntityLink kind="staff" id={d.user.id}>{d.user.name}</EntityLink>
        {" · "}{d.status}
      </>}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Sales", value: d.sale_count, hint: money(d.sales_value) },
        { label: "Counted", value: money(d.counted_total) },
        { label: "Expected", value: money(d.expected_total) },
        { label: "Variance",
          value: Math.abs(d.variance) < 0.005 ? "balanced" : money(d.variance),
          hint: over ? "over" : short ? "short" : undefined },
      ] : undefined}
    >
      {d && (
        <>
          <div className="grid cols-2">
            <Panel title="The session">
              <dl className="kv">
                <dt>Cashier</dt>
                <dd><EntityLink kind="staff" id={d.user.id}>{d.user.name}</EntityLink></dd>
                <dt>Counted by</dt>
                <dd>
                  <EntityLink kind="staff" id={d.counted_by.id}>
                    {d.counted_by.name || "not recorded"}
                  </EntityLink>
                </dd>
                <dt>Opened</dt><dd>{fmtDateTime(d.opened_at)}</dd>
                <dt>Closed</dt>
                <dd>{d.closed_at ? fmtDateTime(d.closed_at)
                  : <span className="muted">still open</span>}</dd>
                <dt>Opening float</dt><dd className="num">{money(d.opening_float)}</dd>
                <dt>Status</dt><dd><span className="badge">{d.status}</span></dd>
              </dl>
            </Panel>

            <Panel title="Notes" empty="Nothing was noted on this cash-up.">
              {d.notes
                ? <p className="prose">{d.notes}</p>
                : <div className="empty"><p>Nothing was noted on this cash-up.</p></div>}
            </Panel>
          </div>

          <Panel title="Sales through this till" count={d.sales.length}
                 empty="Nothing went through this till while it was open."
                 aside={d.sale_count > d.sales.length
                   ? <span className="muted small">
                       showing {d.sales.length} of {d.sale_count}
                     </span>
                   : undefined}>
            <div className="dt-scroll" style={{ maxHeight: "50vh" }}>
              <table className="dt">
                <thead>
                  <tr><th>Sale</th><th>When</th><th>Customer</th><th>Paid by</th><th className="num">Total</th></tr>
                </thead>
                <tbody>
                  {d.sales.map((s) => (
                    <tr key={s.id}>
                      <td className="mono">
                        <EntityLink kind="sale" id={s.id}>{s.sale_number}</EntityLink>
                      </td>
                      <td>{fmtDateTime(s.created_at)}</td>
                      <td>
                        <EntityLink kind="patient" id={s.patient.id}>
                          {s.patient.name}
                        </EntityLink>
                      </td>
                      <td>{s.payment_method}</td>
                      <td className="num">{money(s.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
