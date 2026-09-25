/** Who this medicine went to, script by script.
 *
 *  The product record could say how much had left the shelf and when, and
 *  nothing about who took it. That is the question asked in a recall, in a
 *  dispute about a repeat, and whenever a prescriber rings about a patient:
 *  "when did we last give this to them, and how much". Answering it meant
 *  opening dispensing history and searching, having arrived from the medicine.
 *
 *  Nothing new is computed. The dispensing history endpoint already filters by
 *  product; it was simply never asked from here. A second list built on its
 *  own query would be a second set of rules about what counts as dispensed,
 *  and the two would disagree within a month.
 */
import { useCallback, useEffect, useState } from "react";

import { api, errorText, fmtDateTime, money } from "../api";
import { Refreshable, TableSkeleton } from "./Skeleton";
import { EntityLink, TableSearch, useSearch } from "./Filters";
import { useToast } from "./Toast";
import Person from "./Person";

interface Row {
  id: number;
  dispensed_at: string;
  quantity: number;
  rx_number: string;
  prescription_id: number | null;
  patient_id: number | null;
  patient: string;
  prescriber: string;
  prescriber_id: number | null;
  dispensed_by: string;
  dispensed_by_id: number | null;
  is_repeat: boolean;
  sale_id: number | null;
  sale_number: string;
  outstanding: number;
  price_adjusted?: boolean;
  stock_adjusted?: boolean;
  summary?: string;
}

const PER_PAGE = 25;

export default function ProductDispensings({ productId }: { productId: number }) {
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>([]);
  /* Every time this medicine was handed over. It is read in a recall, in a
     dispute about a repeat, and whenever a prescriber rings about a patient
     — all three are a question about ONE name in a list that only grows. */
  const { q, setQ, shown } = useSearch(rows, (r) =>
    [r.patient, r.rx_number, r.prescriber, r.dispensed_by]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api.get<{ items: Row[]; total: number }>(
      `/api/dispensing/history?product_id=${productId}&page=${page}&per_page=${PER_PAGE}`)
      .then((r) => { setRows(r.items); setTotal(r.total); })
      .catch((e) => toast.error(errorText(e, "That history could not be read.")))
      .finally(() => setLoading(false));
  }, [productId, page, toast]);

  useEffect(load, [load]);

  const pages = Math.max(1, Math.ceil(total / PER_PAGE));

  return (
    <>
      <p className="muted small pd-note">
        Every time this medicine was handed over, newest first. The same record
        the dispensing history screen shows, asked about one line.
      </p>

      <Refreshable
        loading={loading}
        hasData={rows.length > 0}
        skeleton={<TableSkeleton cols={5} rows={6}
                                 widths={["16ch", "22ch", "14ch", "8ch", "18ch"]} />}
      >
        {!loading && rows.length === 0 ? (
          <p className="muted">This medicine has never been dispensed.</p>
        ) : (
          <>
            <div className="dt-scroll">
              <TableSearch value={q} onChange={setQ}
                           placeholder="Find a patient, a script or a prescriber…"
                           shown={shown.length} total={rows.length} />
              <table className="dt">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Patient</th>
                    <th>Script</th>
                    <th className="num">Units</th>
                    <th>Dispensed by</th>
                    <th>Paid</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.id}>
                      <td className="nowrap">{fmtDateTime(r.dispensed_at)}</td>
                      <td>
                        <EntityLink kind="patient" id={r.patient_id}><Person name={r.patient} /></EntityLink>
                        {r.prescriber && (
                          <div className="muted small">
                            <EntityLink kind="prescriber" id={r.prescriber_id}><Person name={r.prescriber} /></EntityLink>
                          </div>
                        )}
                      </td>
                      <td>
                        <EntityLink kind="prescription" id={r.prescription_id}>
                          {r.rx_number}
                        </EntityLink>
                        {r.is_repeat && <div className="muted small">Repeat</div>}
                        {/* The same marks the dispensing history carries, for
                            the same reason: a line somebody repriced by hand
                            is the one asked about weeks later. */}
                        {(r.price_adjusted || r.stock_adjusted) && (
                          <div className="disp-touched" title={r.summary || ""}>
                            {r.price_adjusted && (
                              <span className="badge warn">Price set by hand</span>
                            )}
                            {r.stock_adjusted && (
                              <span className="badge warn">Shelf corrected</span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="num">{r.quantity}</td>
                      <td>
                        <EntityLink kind="staff" id={r.dispensed_by_id}><Person name={r.dispensed_by} /></EntityLink>
                      </td>
                      <td>
                        {r.outstanding > 0.005
                          ? <b>{money(r.outstanding)} owed</b>
                          : r.sale_id
                            ? <EntityLink kind="sale" id={r.sale_id}>{r.sale_number}</EntityLink>
                            : <span className="muted">Not billed</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {pages > 1 && (
              <div className="dt-pager">
                <button type="button" className="btn small ghost"
                        disabled={page <= 1} onClick={() => setPage((n) => n - 1)}>
                  Newer
                </button>
                <span className="muted small">
                  {total.toLocaleString()} dispensing{total === 1 ? "" : "s"},
                  page {page} of {pages}
                </span>
                <button type="button" className="btn small ghost"
                        disabled={page >= pages} onClick={() => setPage((n) => n + 1)}>
                  Older
                </button>
              </div>
            )}
          </>
        )}
      </Refreshable>
    </>
  );
}
