/** One stock take, months later.
 *
 *  A variance is the start of something: an insurance claim, a write-off, or a
 *  conversation with somebody about stock that is not there. It is the record
 *  a pharmacy is most likely to be asked to produce long after the count, and
 *  until now there was no way to reach a closed count at all — the screen
 *  loaded whichever one was open and nothing else, because no endpoint listed
 *  them.
 *
 *  OVER AND SHORT ARE KEPT APART
 *
 *  A count forty over and forty short nets to zero. That is not a clean count,
 *  it is two errors that happen to cancel, and a single "variance" figure
 *  hides exactly the thing worth looking at. The lines are ordered by how far
 *  out they are rather than by name, because the reader is looking for the
 *  worst one and not for a particular medicine.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "@phosphor-icons/react";

import { api, errorText, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";

interface Line {
  product_id: number;
  product: string;
  counted: number;
  expected: number;
  variance: number;
  value: number;
  note: string;
}

interface Take {
  id: number;
  reference: string;
  status: string;
  scope: { category: string; bin: string };
  opened_at: string | null;
  closed_at: string | null;
  counted_lines: number;
  variance_units: number;
  variance_value: number;
  over_units: number;
  short_units: number;
  lines: Line[];
}

export default function StockTakeDetail() {
  const { id } = useParams();
  const [row, setRow] = useState<Take | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRow(null);
    setError("");
    api.get<Take>(`/api/stock-takes/${id}`)
      .then(setRow)
      .catch((e) => setError(errorText(e, "That count could not be loaded.")));
  }, [id]);

  const scope = row
    ? [row.scope.category, row.scope.bin && `bin ${row.scope.bin}`]
        .filter(Boolean).join(" · ") || "the whole catalogue"
    : "";

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Stock take", to: "/stock-take" },
              { label: "This count" }]}
      eyebrow="Stock take"
      title={row ? row.reference : "Count"}
      subtitle={row ? `${row.counted_lines} line(s) counted over ${scope}` : undefined}
      loading={!row && !error}
      error={error}
      actions={
        <Link to="/stock-take" className="btn secondary">
          <ArrowLeft size={13} weight="bold" /> Stock take
        </Link>
      }
      facts={row ? [
        { label: "Lines counted", value: row.counted_lines, hint: scope },
        // Separately, on purpose. See the note at the top of the file.
        { label: "Over", value: row.over_units,
          hint: "more on the shelf than expected",
          tone: row.over_units ? "warn" : undefined },
        { label: "Short", value: row.short_units,
          hint: "missing from the shelf",
          tone: row.short_units ? "bad" : undefined },
        { label: "Worth", value: money(row.variance_value),
          hint: row.variance_value < 0 ? "written off" : "found",
          tone: row.variance_value < 0 ? "bad" : undefined },
      ] : []}
    >
      {row && (
        <>
          <Panel title="The count">
            <dl className="kv">
              <dt>Status</dt>
              <dd><span className="badge muted">{row.status}</span></dd>

              <dt>Covered</dt>
              <dd>{scope}</dd>

              <dt>Opened</dt>
              <dd>{row.opened_at ? fmtDateTime(row.opened_at)
                                 : <span className="muted">not recorded</span>}</dd>

              <dt>Closed</dt>
              <dd>{row.closed_at
                ? fmtDateTime(row.closed_at)
                : <span className="muted">still open, nothing adjusted yet</span>}</dd>
            </dl>
          </Panel>

          <Panel
            title="What each line found"
            count={row.lines.length}
            empty="Nothing was counted on this take."
          >
            <div className="table-wrap">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Medicine</th>
                    <th className="num">Expected</th>
                    <th className="num">Counted</th>
                    <th className="num">Out by</th>
                    <th className="num">Worth</th>
                    <th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {row.lines.map((l) => (
                    <tr key={l.product_id}>
                      <td>
                        <EntityLink to={`/products/${l.product_id}`}>
                          {l.product}
                        </EntityLink>
                      </td>
                      <td className="num">{l.expected}</td>
                      <td className="num">{l.counted}</td>
                      <td className="num">
                        {l.variance === 0
                          ? <span className="muted">—</span>
                          : <span className={l.variance < 0 ? "neg" : "pos"}>
                              {l.variance > 0 ? `+${l.variance}` : l.variance}
                            </span>}
                      </td>
                      <td className="num">
                        {l.value === 0
                          ? <span className="muted">—</span>
                          : <span className={l.value < 0 ? "neg" : undefined}>
                              {money(l.value)}
                            </span>}
                      </td>
                      <td className="muted small wrap">{l.note}</td>
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
