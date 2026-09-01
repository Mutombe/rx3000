/** One fiscal day: the Z-report, and the chain across it.
 *
 *  The list of days carried four totals and no way to open one, which is the
 *  wrong way round. The totals are a summary of the statutory document; the
 *  document is what a pharmacy is asked for. ZIMRA's own query, and an
 *  auditor's, is about a *day*: which receipts, in what order, at which tax
 *  rates, in which currencies, and whether the chain across them holds.
 *
 *  WHAT IS ON IT AND WHY
 *
 *  Split by currency, because a counter here takes USD and ZiG across the same
 *  day and a single total in one of them answers nothing.
 *
 *  Split by tax treatment, because that is what a return is filed on. Receipts
 *  carrying no VAT are reported as "no VAT charged" rather than as zero-rated
 *  or exempt: those are different things legally, nothing on the receipt
 *  distinguishes them, and picking one would be putting a guess into a filing.
 *
 *  The unfiled receipts first, when there are any. A day closed with receipts
 *  still queued or refused is filed short, and the list of days said nothing
 *  about it — the totals looked complete because they counted every receipt
 *  written, filed or not.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle, Warning, XCircle } from "@phosphor-icons/react";
import { api, errorText, fmtDateTime, money } from "../api";
import RecordPage, { Fact, Panel } from "../components/RecordPage";
import { EntityLink } from "../components/Filters";

interface Receipt {
  id: number; sale_id: number; receipt_counter: number; global_counter: number;
  receipt_type: string; currency_code: string; total: number; vat_amount: number;
  status: string; receipt_hash: string; verification_url: string;
  created_at: string;
}
interface Unfiled {
  id: number; receipt_counter: number; global_counter: number;
  total: number; status: string; response_message: string;
}
interface Day {
  id: number; day_number: number; device_id: string; status: string;
  opened_at: string; closed_at: string | null; submitted_at: string | null;
  response_ref: string; error: string;
  receipt_count: number; sale_count: number; credit_note_count: number;
  total_sales: number; total_vat: number; total_credit_notes: number; net: number;
  by_currency: { currency: string; receipts: number; sales: number;
                 vat: number; credit_notes: number }[];
  by_rate: { label: string; receipts: number; total: number; vat: number }[];
  first_counter: number | null; last_counter: number | null;
  opening_hash: string; closing_hash: string;
  chain_holds: boolean; chain_broken_at: number | null;
  not_filed: Unfiled[];
  receipts: Receipt[];
}

const STATUS_TONE: Record<string, string> = {
  accepted: "ok", submitted: "muted", queued: "warn", rejected: "danger",
};

function shortHash(h: string): string {
  return h ? `${h.slice(0, 12)}…${h.slice(-4)}` : "—";
}

export default function FiscalDay() {
  const { id } = useParams();
  const [day, setDay] = useState<Day | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState("");

  const load = useCallback(() => {
    api.get<Day>(`/api/fiscal/days/${id}`)
      .then((d) => { setDay(d); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "That fiscal day could not be opened.")))
      .finally(() => setLoading(false));
  }, [id]);
  useEffect(load, [load]);

  const open = day?.closed_at === null;
  const facts: Fact[] = day ? [
    { label: "Receipts", value: day.receipt_count,
      hint: day.credit_note_count
        ? `${day.sale_count} sales, ${day.credit_note_count} credit notes`
        : undefined },
    { label: "Net", value: money(day.net),
      hint: day.total_credit_notes
        ? `${money(day.total_sales)} less ${money(day.total_credit_notes)} credited`
        : undefined },
    { label: "VAT", value: money(day.total_vat) },
    { label: "Chain", value: day.chain_holds ? "Holds" : "Broken",
      tone: day.chain_holds ? "ok" : "bad",
      hint: day.chain_holds
        ? "every receipt follows the one before it"
        : `first break at receipt ${day.chain_broken_at}` },
  ] : [];

  return (
    <RecordPage
      trail={[{ to: "/fiscal", label: "Fiscalisation" },
              { label: day ? `Day ${day.day_number}` : "" }]}
      eyebrow="Fiscal day"
      title={day ? `Day ${day.day_number}` : ""}
      subtitle={day ? (
        <>
          opened {fmtDateTime(day.opened_at)}
          {day.closed_at ? <> · closed {fmtDateTime(day.closed_at)}</>
            : <> · <b>still open</b></>}
          {day.device_id && <span className="muted"> · {day.device_id}</span>}
        </>
      ) : undefined}
      facts={facts}
      loading={loading}
      error={failed}
    >
      {day && (
        <>
          {/* A day closed with receipts the authority never took is filed
              short. The totals look complete because they count every receipt
              written, filed or not, so this has to be said, not inferred. */}
          {day.not_filed.length > 0 && (
            <div className={day.closed_at ? "alert error" : "alert warn"}>
              <Warning size={16} weight="fill" />
              <span>
                <b>{day.not_filed.length} receipt
                  {day.not_filed.length === 1 ? " has" : "s have"} not reached
                  the authority.</b>{" "}
                {day.closed_at
                  ? "This day was closed with them outstanding, so what was "
                    + "filed does not match what was sold."
                  : "They are still queued. Flush them before closing the day."}
              </span>
            </div>
          )}

          {!day.chain_holds && (
            <div className="alert error">
              <XCircle size={16} weight="fill" />
              <span>
                <b>The chain breaks at receipt {day.chain_broken_at}.</b> Each
                receipt carries the hash of the one before it, and that is the
                whole evidentiary value of fiscalising: a break means a receipt
                was altered or removed after it was written.
              </span>
            </div>
          )}

          {day.error && (
            <div className="alert error">
              <XCircle size={16} weight="fill" />
              <span><b>The authority refused this day.</b> {day.error}</span>
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="What was taken">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Currency</th><th className="num">Receipts</th>
                    <th className="num">Sales</th><th className="num">VAT</th>
                    <th className="num">Credited</th>
                  </tr>
                </thead>
                <tbody>
                  {day.by_currency.length === 0 ? (
                    <tr><td colSpan={5} className="muted">
                      Nothing was rung up on this day.
                    </td></tr>
                  ) : day.by_currency.map((c) => (
                    <tr key={c.currency}>
                      <td className="mono">{c.currency}</td>
                      <td className="num">{c.receipts}</td>
                      <td className="num">{money(c.sales)}</td>
                      <td className="num muted">{money(c.vat)}</td>
                      <td className="num">
                        {c.credit_notes ? money(c.credit_notes)
                          : <span className="muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            <Panel title="How it is taxed">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Treatment</th><th className="num">Receipts</th>
                    <th className="num">Total</th><th className="num">VAT</th>
                  </tr>
                </thead>
                <tbody>
                  {day.by_rate.map((r) => (
                    <tr key={r.label}>
                      <td>{r.label}</td>
                      <td className="num">{r.receipts}</td>
                      <td className="num">{money(r.total)}</td>
                      <td className="num">
                        {r.vat ? money(r.vat) : <span className="muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {/* Stated rather than guessed at. Zero-rated and exempt are
                  different things in a return, and nothing on a receipt says
                  which one a VAT-free line is. */}
              <p className="muted small">
                Receipts carrying no VAT are reported as charged nothing, not as
                zero-rated or exempt: those are different in a return and
                nothing on the receipt distinguishes them.
              </p>
            </Panel>
          </div>

          <Panel title="What the authority's record should show">
            <dl className="kv">
              <dt>Z-report reference</dt>
              <dd>
                {day.response_ref
                  ? <span className="mono">{day.response_ref}</span>
                  : open ? <span className="muted">the day is still open</span>
                    : <span className="cu-diff">not filed</span>}
              </dd>
              <dt>Filed</dt>
              <dd>{day.submitted_at ? fmtDateTime(day.submitted_at)
                : <span className="muted">—</span>}</dd>
              <dt>Global counters</dt>
              <dd className="mono">
                {day.first_counter === null ? "—"
                  : `${day.first_counter} – ${day.last_counter}`}
              </dd>
              <dt>Opening hash</dt>
              <dd className="mono small" title={day.opening_hash}>
                {shortHash(day.opening_hash)}
              </dd>
              <dt>Closing hash</dt>
              <dd className="mono small" title={day.closing_hash}>
                {shortHash(day.closing_hash)}
              </dd>
            </dl>
          </Panel>

          {day.not_filed.length > 0 && (
            <Panel title="Not filed" count={day.not_filed.length}>
              <table className="dt">
                <thead>
                  <tr>
                    <th className="num">Receipt</th><th className="num">Global</th>
                    <th className="num">Total</th><th>State</th><th>The authority said</th>
                  </tr>
                </thead>
                <tbody>
                  {day.not_filed.map((r) => (
                    <tr key={r.id} className="row-flag">
                      <td className="num mono">{r.receipt_counter}</td>
                      <td className="num mono">{r.global_counter}</td>
                      <td className="num">{money(r.total)}</td>
                      <td>
                        <span className={`badge ${STATUS_TONE[r.status] ?? "muted"}`}>
                          {r.status}
                        </span>
                      </td>
                      <td className="muted small wrap">
                        {r.response_message || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}

          <Panel title="Receipts, in the order they were written"
                 count={day.receipts.length}
                 empty="Nothing was rung up on this day.">
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th className="num">#</th><th className="num">Global</th>
                    <th>When</th><th>Type</th><th className="num">Total</th>
                    <th className="num">VAT</th><th>State</th><th>Sale</th>
                    <th>Hash</th>
                  </tr>
                </thead>
                <tbody>
                  {day.receipts.map((r) => (
                    <tr key={r.id}
                        className={r.receipt_type === "credit_note"
                          ? "row-muted" : undefined}>
                      <td className="num mono">{r.receipt_counter}</td>
                      <td className="num mono">{r.global_counter}</td>
                      <td>{fmtDateTime(r.created_at)}</td>
                      <td>
                        {r.receipt_type === "credit_note"
                          ? <span className="badge warn">credit note</span>
                          : <span className="muted">sale</span>}
                      </td>
                      <td className="num">{money(r.total)}</td>
                      <td className="num muted">
                        {r.vat_amount ? money(r.vat_amount)
                          : <span className="muted">—</span>}
                      </td>
                      <td>
                        <span className={`badge ${STATUS_TONE[r.status] ?? "muted"}`}>
                          {r.status === "accepted" && <CheckCircle size={10} weight="fill" />}
                          {" "}{r.status}
                        </span>
                      </td>
                      <td>
                        <EntityLink kind="sale" id={r.sale_id}>
                          the sale
                        </EntityLink>
                      </td>
                      <td className="mono small" title={r.receipt_hash}>
                        {r.verification_url ? (
                          // The authority's own verification page for this
                          // receipt. It is theirs, not ours, so it is an
                          // ordinary link — no session of ours to carry.
                          <a href={r.verification_url} target="_blank"
                             rel="noreferrer">{shortHash(r.receipt_hash)}</a>
                        ) : shortHash(r.receipt_hash)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <p className="muted small">
            <Link to="/fiscal">Back to fiscalisation</Link> — the trading day,
            the queue, and the chain across the whole register.
          </p>
        </>
      )}
    </RecordPage>
  );
}
