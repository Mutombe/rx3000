/** One till session: who had it, what went through it, and what was short.
 *
 *  The cash office listed sessions and a variance and stopped there. A variance
 *  is a question, not an answer, and the only useful next step is the sales
 *  that went through that till while it was open.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDateTime, money , sentence} from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { Figure, GhostRows } from "../components/Skeleton";
import { useParams } from "react-router-dom";
import Person from "../components/Person";
import Th from "../components/Th";

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
        <EntityLink kind="staff" id={d.user.id}><Person name={d.user.name} /></EntityLink>
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
      {/* The two panel headings, the six field labels and the five column heads
          of the sales table are written here and read the same for every till
          session. Held behind the fetch, a reader waiting on a slow session got
          a bare frame and then the entire body at once. Only the values wait. */}
      <div className="grid cols-2">
        <Panel title="The session">
          <dl className="kv">
            <dt>Cashier</dt>
            <dd>
              <Figure ready={!!d} w="16ch">
                {d && (
                  <EntityLink kind="staff" id={d.user.id}>
                    <Person name={d.user.name} />
                  </EntityLink>
                )}
              </Figure>
            </dd>
            <dt>Counted by</dt>
            <dd>
              <Figure ready={!!d} w="16ch">
                {d && (
                  <EntityLink kind="staff" id={d.counted_by.id}>
                    {d.counted_by.name || "Not recorded"}
                  </EntityLink>
                )}
              </Figure>
            </dd>
            <dt>Opened</dt>
            <dd><Figure ready={!!d} w="16ch">{d && fmtDateTime(d.opened_at)}</Figure></dd>
            <dt>Closed</dt>
            <dd>
              <Figure ready={!!d} w="16ch">
                {d && (d.closed_at
                  ? fmtDateTime(d.closed_at)
                  : <span className="muted">Still open</span>)}
              </Figure>
            </dd>
            <dt>Opening float</dt>
            <dd className="num">
              <Figure ready={!!d} w="9ch">{d && money(d.opening_float)}</Figure>
            </dd>
            <dt>Status</dt>
            <dd>
              <Figure ready={!!d} w="10ch">
                {d && <span className="badge">{sentence(d.status)}</span>}
              </Figure>
            </dd>
          </dl>
        </Panel>

        {/* A session that has not arrived has not told us it was noteless, so
            the reason only appears once the cash-up is actually in hand. */}
        <Panel title="Notes" empty={d ? "Nothing was noted on this cash-up." : undefined}>
          <Figure ready={!!d} w="36ch">
            {d && (d.notes
              ? <p className="prose">{d.notes}</p>
              : <div className="empty"><p>Nothing was noted on this cash-up.</p></div>)}
          </Figure>
        </Panel>
      </div>

      <Panel title="Sales through this till" count={d?.sales.length}
             empty={d ? "Nothing went through this till while it was open." : undefined}
             aside={d && d.sale_count > d.sales.length
               ? <span className="muted small">
                   showing {d.sales.length} of {d.sale_count}
                 </span>
               : undefined}>
        <div className="dt-scroll" style={{ maxHeight: "50vh" }}>
          <table className="dt">
            <thead>
              <tr><Th>Sale</Th><Th>When</Th><Th>Customer</Th><Th>Paid by</Th><Th className="num">Total</Th></tr>
            </thead>
            {!d ? (
              <GhostRows cols={5} rows={3} widths={["60%", "70%", "60%", "50%", "40%"]} />
            ) : (
              <tbody>
                {d.sales.map((s) => (
                  <tr key={s.id}>
                    <td className="mono">
                      <EntityLink kind="sale" id={s.id}>{s.sale_number}</EntityLink>
                    </td>
                    <td>{fmtDateTime(s.created_at)}</td>
                    <td>
                      <EntityLink kind="patient" id={s.patient.id}><Person name={s.patient.name} /></EntityLink>
                    </td>
                    <td>{s.payment_method}</td>
                    <td className="num">{money(s.total)}</td>
                  </tr>
                ))}
              </tbody>
            )}
          </table>
        </div>
      </Panel>
    </RecordPage>
  );
}
