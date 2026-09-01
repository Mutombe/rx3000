/** Everything that has been dispensed, and what happened to it afterwards.
 *
 *  There was no such screen. The controlled register covers S5 and S6, the
 *  counter log covers over-the-counter sales, and everything in between — the
 *  ordinary prescription dispensed an hour ago — could only be found by
 *  knowing the patient and opening their record.
 *
 *  The three questions a pharmacy actually asks of it are "what went out this
 *  morning", "did that one get paid for" and "has she collected it", so the
 *  money and the collection sit on the row beside the medicine rather than a
 *  click away. Every name on the row opens the thing it names.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, Printer } from "@phosphor-icons/react";
import { prefetchRoute, api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RowLink from "../components/RowLink";
import LabelSheet from "../components/LabelSheet";
import Pagination, { Paged } from "../components/Pagination";
import Select from "../components/Select";
import { useToast } from "../components/Toast";
import { Refreshable, TableSkeleton } from "../components/Skeleton";

interface Row {
  id: number;
  dispensed_at: string;
  quantity: number;
  schedule: number;
  is_repeat: boolean;
  prescription_id: number | null;
  rx_number: string;
  patient_id: number | null;
  patient: string;
  product_id: number | null;
  product: string;
  prescriber_id: number | null;
  prescriber: string;
  dispensed_by_id: number | null;
  dispensed_by: string;
  pharmacist_initial: string;
  collected_at: string | null;
  collected_name: string;
  sale_id: number | null;
  sale_number: string;
  sale_status: string;
  sale_total: number;
  claim_id: number | null;
  claim_status: string;
  scheme_pays: number;
  outstanding: number;
}

const WINDOWS: [string, string][] = [
  ["0", "Everything"],
  ["1", "Today"],
  ["7", "Last 7 days"],
  ["30", "Last 30 days"],
  ["90", "Last 90 days"],
];

export default function DispensingHistory() {
  const [data, setData] = useState<Paged<Row> | null>(null);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [days, setDays] = useState("30");
  const [schedule, setSchedule] = useState("-1");
  const [unpaid, setUnpaid] = useState(false);
  const [uncollected, setUncollected] = useState(false);
  const [failed, setFailed] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reprint, setReprint] = useState<number | null>(null);
  const toast = useToast();

  const load = useCallback(() => {
    setSpinning(true);
    const params = new URLSearchParams({
      page: String(page), per_page: "25", days, schedule,
      ...(q.trim() ? { q: q.trim() } : {}),
      ...(unpaid ? { unpaid_only: "true" } : {}),
      ...(uncollected ? { uncollected_only: "true" } : {}),
    });
    api.get<Paged<Row>>(`/api/dispensing/history?${params}`)
      .then((r) => { setData(r); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "The history could not be loaded.")))
      // Held briefly so the turn is visible: a spinner that stops on the frame
      // it started reads as a button that did nothing.
      .finally(() => {
        setLoading(false);
        window.setTimeout(() => setSpinning(false), 400);
      });
  }, [page, q, days, schedule, unpaid, uncollected]);

  useEffect(() => { load(); }, [load]);
  // Any filter change starts again at the first page — page 4 of a different
  // question is not a page anybody asked for.
  useEffect(() => { setPage(1); }, [q, days, schedule, unpaid, uncollected]);

  const rows = data?.items ?? [];
  const owing = rows.reduce((sum, r) => sum + r.outstanding, 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dispensing history</h1>
          <div className="sub">
            What has gone out, who checked it, whether it was paid for and
            whether it has been collected
          </div>
        </div>
        <button className="btn secondary" onClick={load}>
          <ArrowClockwise size={15} className={spinning ? "spin" : ""} />
          Refresh
        </button>
      </div>

      <div className="card">
        <div className="filter-bar">
          <input
            type="search" className="filter-search" autoFocus
            placeholder="Script number, patient or medicine…"
            value={q} onChange={(e) => setQ(e.target.value)}
          />
          <span className="filter-dim">
            <Select value={days} onChange={setDays} ariaLabel="Period"
                    options={WINDOWS.map(([v, l]) => ({ value: v, label: l }))} />
          </span>
          <span className="filter-dim">
            <Select
              value={schedule} onChange={setSchedule} ariaLabel="Schedule"
              options={[
                { value: "-1", label: "Any schedule" },
                ...[0, 1, 2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `S${n}` })),
              ]}
            />
          </span>
          <button className={`btn small ${unpaid ? "" : "ghost"}`}
                  onClick={() => setUnpaid(!unpaid)}>
            Not paid for
          </button>
          <button className={`btn small ${uncollected ? "" : "ghost"}`}
                  onClick={() => setUncollected(!uncollected)}>
            Not collected
          </button>
        </div>

        {failed && <div className="alert error">{failed}</div>}

        {!failed && rows.length === 0 && (
          <div className="empty">
            <b>Nothing matches that.</b>
            <p>
              Try a wider period, or clear the filters. A script captured but
              not yet dispensed is on the worklist rather than here — this is
              what has actually left the shelf.
            </p>
          </div>
        )}

        {rows.length > 0 && (
          <>
            {owing > 0.005 && (
              <p className="muted">
                <b>{money(owing)}</b> outstanding on this page.
              </p>
            )}
            <Refreshable
              loading={loading}
              hasData={!!data?.items?.length}
              skeleton={<TableSkeleton cols={7} rows={6}
                widths={["14ch", "12ch", "18ch", "20ch", "6ch", "12ch", "10ch"]} />}
            >
            <table className="dt">
              <thead>
                <tr>
                  <th>When</th><th>Script</th><th>Patient</th><th>Medicine</th>
                  <th className="num">Qty</th><th>Checked by</th>
                  <th>Money</th><th>Collected</th><th className="actions" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <RowLink key={r.id} to={`/dispensings/${r.id}`}
                           prefetch={prefetchRoute}>
                    <td>{fmtDateTime(r.dispensed_at)}</td>
                    <td className="mono">
                      <EntityLink kind="prescription" id={r.prescription_id}>
                        {r.rx_number || "—"}
                      </EntityLink>
                      {r.is_repeat && <div className="muted small">repeat</div>}
                    </td>
                    <td>
                      <EntityLink kind="patient" id={r.patient_id}>{r.patient}</EntityLink>
                      {r.prescriber && (
                        <div className="muted small">
                          <EntityLink kind="prescriber" id={r.prescriber_id}>
                            {r.prescriber}
                          </EntityLink>
                        </div>
                      )}
                    </td>
                    <td>
                      <EntityLink kind="product" id={r.product_id}>{r.product}</EntityLink>
                      {r.schedule >= 3 && (
                        <span className="badge sched">S{r.schedule}</span>
                      )}
                    </td>
                    <td className="num">{r.quantity}</td>
                    <td>
                      <EntityLink kind="staff" id={r.dispensed_by_id}>
                        {r.dispensed_by || r.pharmacist_initial || "—"}
                      </EntityLink>
                    </td>
                    {/* Paid, part paid, or owed, and by whom. The commonest
                        reason for opening this screen at all. */}
                    <td>
                      <EntityLink kind="sale" id={r.sale_id}>
                        {r.sale_number || "—"}
                      </EntityLink>
                      <div className="muted small">
                        {r.outstanding > 0.005
                          ? <b>{money(r.outstanding)} owed</b>
                          : r.sale_status === "paid" ? "paid" : r.sale_status || "—"}
                        {r.claim_id ? (
                          <> · <EntityLink kind="claim" id={r.claim_id}>
                            scheme {money(r.scheme_pays)}
                          </EntityLink></>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      {r.collected_at
                        ? <>{fmtDate(r.collected_at)}
                            {r.collected_name && (
                              <div className="muted small">{r.collected_name}</div>
                            )}</>
                        : <span className="badge warn">on the shelf</span>}
                    </td>
                    <td className="actions">
                      <button
                        className="btn small secondary"
                        disabled={!r.prescription_id}
                        onClick={() => r.prescription_id && setReprint(r.prescription_id)}
                      >
                        <Printer size={13} /> Labels
                      </button>
                    </td>
                  </RowLink>
                ))}
              </tbody>
            </table>
            {data && <Pagination meta={data} onPage={setPage} noun="dispensings" />}
            </Refreshable>
          </>
        )}
      </div>

      {reprint !== null && (
        <LabelSheet rxId={reprint} onClose={() => setReprint(null)} />
      )}
    </>
  );
}
