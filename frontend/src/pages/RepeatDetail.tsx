/** One repeat: what it is worth, how it has actually run, and whether it can be filled.
 *
 *  The repeats book listed lines and opened patients. Clicking a repeat took
 *  you to the person holding it, which answers a different question — the one
 *  being asked is about *this line*: how many are left, when it is due, what it
 *  is worth, and whether there is stock to fill it this morning.
 *
 *  Two things here are not on the list and are the reason the page is worth
 *  having:
 *
 *  **What it is worth.** A repeat book is money. A queue that does not say what
 *  a line is worth cannot be worked in the order that pays, and that is the
 *  order a short-staffed shop should work.
 *
 *  **The gap the patient actually keeps.** Two fills 45 days apart on a 30-day
 *  script is somebody running out for a fortnight every month. The script says
 *  30, the behaviour says 45, and nothing anywhere compared the two.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";

interface Detail {
  item_id: number;
  patient: { id: number | null; name: string; phone: string };
  product: { id: number; name: string; form: string; schedule: number;
             unit_price: number } | null;
  prescription: { id: number; number: string; date: string;
                  doctor: string; doctor_id: number | null } | null;
  directions: string; icd10_code: string;
  quantity: number; supply_days: number; interval_days: number;
  auto_refill: boolean;
  allowed: number; used: number; left: number; exhausted: boolean;
  next_due: string | null; overdue_days: number;
  value_per_fill: number; value_remaining: number; value_filled: number;
  on_hand: number; can_supply: boolean;
  average_gap_days: number | null; keeping_up: boolean | null;
  fills: { id: number; quantity: number; dispensed_at: string;
           collected_at: string | null; by: string; is_repeat: boolean }[];
}

export default function RepeatDetail() {
  const { id } = useParams();
  const [r, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Detail>(`/api/repeats/item/${id}`)
      .then(setData)
      .catch((e) => setError(errorText(e)));
  }, [id]);

  const due = r?.next_due ? new Date(r.next_due) : null;
  const dueSoon = !!r && due !== null && !r.overdue_days
    && (due.getTime() - Date.now()) / 86400000 <= 7;

  return (
    <RecordPage
      trail={[{ label: "Repeats", to: "/repeats" },
              { label: r?.product?.name ?? "Repeat" }]}
      eyebrow="Repeat"
      title={r?.product?.name ?? "Repeat"}
      subtitle={r && (
        <>
          For {r.patient.name}
          {r.quantity ? ` · ${r.quantity} every ${r.interval_days || "—"} days` : ""}
          {r.auto_refill && " · auto-refill on"}
        </>
      )}
      loading={!r && !error}
      error={error}
      facts={r ? [
        { label: "Repeats used", value: `${r.used} of ${r.allowed}`,
          hint: r.exhausted ? "none left" : `${r.left} left`,
          tone: r.exhausted ? "warn" : undefined },
        { label: r.overdue_days ? "Overdue since" : "Next due",
          value: r.next_due ? fmtDate(r.next_due) : "—",
          hint: r.overdue_days ? `${r.overdue_days} days`
            : dueSoon ? "this week" : undefined,
          tone: r.overdue_days ? "bad" : dueSoon ? "warn" : undefined },
        { label: "Each fill is worth", value: money(r.value_per_fill),
          hint: `${money(r.value_remaining)} still to come` },
        { label: "In unexpired stock", value: r.on_hand,
          // Unexpired batches, which is what dispensing draws from. The
          // product's own count is what most screens show and the one
          // dispensing does not obey — reading that said "none on hand" for a
          // medicine with 267 usable units.
          hint: r.can_supply ? "enough to fill it" : `${r.quantity} needed`,
          tone: r.can_supply ? undefined : "bad" },
        ...(r.average_gap_days !== null ? [{
          label: "Actually collected every",
          value: `${r.average_gap_days} days`,
          hint: r.interval_days ? `the script says ${r.interval_days}` : undefined,
          tone: r.keeping_up === false ? "bad" : undefined,
        }] : []),
      ] : undefined}
    >
      {r && (
        <>
          {/* Overdue, exhausted and out of stock are three different problems
              with three different answers. Putting them in one grey line is how
              none of them gets acted on. */}
          {r.overdue_days > 0 && (
            <div className="alert error">
              <Warning size={16} weight="fill" />{" "}
              <b>{r.overdue_days} days overdue.</b> {r.patient.name} should have
              collected this on {fmtDate(r.next_due!)}. Worth{" "}
              {money(r.value_per_fill)} to the shop and, more to the point,
              they are not taking it.
              {r.patient.phone && (
                <> Ring <a href={`tel:${r.patient.phone}`}>{r.patient.phone}</a>.</>
              )}
            </div>
          )}
          {r.exhausted && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />{" "}
              Every repeat on this script has been used. The patient needs a new
              one from {r.prescription?.doctor || "their prescriber"} before this
              can be filled again.
            </div>
          )}
          {!r.exhausted && !r.can_supply && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />{" "}
              {r.on_hand} in unexpired stock against {r.quantity} needed. This
              cannot be filled today — order it before the patient arrives
              rather than after.
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="The line">
              <dl className="kv">
                <dt>Medicine</dt>
                <dd>
                  {r.product
                    ? <EntityLink kind="product" id={r.product.id}>
                        {r.product.name}
                      </EntityLink>
                    : "—"}
                  {r.product?.form && (
                    <span className="muted"> · {r.product.form}</span>
                  )}
                  {(r.product?.schedule ?? 0) > 0 && (
                    <span className="badge warn"> S{r.product!.schedule}</span>
                  )}
                </dd>
                <dt>Directions</dt>
                <dd className="wrap">
                  {r.directions || <span className="muted">none recorded</span>}
                </dd>
                <dt>Quantity each time</dt>
                <dd>
                  {r.quantity}
                  {r.supply_days ? ` · ${r.supply_days} days of supply` : ""}
                </dd>
                <dt>Diagnosis</dt>
                <dd className="mono">
                  {r.icd10_code || <span className="muted">none</span>}
                </dd>
                <dt>Patient</dt>
                <dd>
                  {r.patient.id
                    ? <EntityLink kind="patient" id={r.patient.id}>
                        {r.patient.name}
                      </EntityLink>
                    : r.patient.name}
                  {r.patient.phone && (
                    <div className="muted small">
                      <a href={`tel:${r.patient.phone}`}>{r.patient.phone}</a>
                    </div>
                  )}
                </dd>
                <dt>Script</dt>
                <dd>
                  {r.prescription ? (
                    <>
                      <EntityLink kind="prescription" id={r.prescription.id}>
                        {r.prescription.number || `#${r.prescription.id}`}
                      </EntityLink>
                      {r.prescription.date && (
                        <span className="muted"> · {fmtDate(r.prescription.date)}</span>
                      )}
                      {r.prescription.doctor && (
                        <div className="muted small">
                          {r.prescription.doctor_id
                            ? <EntityLink kind="prescriber" id={r.prescription.doctor_id}>
                                {r.prescription.doctor}
                              </EntityLink>
                            : r.prescription.doctor}
                        </div>
                      )}
                    </>
                  ) : <span className="muted">—</span>}
                </dd>
              </dl>
            </Panel>

            <Panel
              title="Is the patient keeping up?"
              aside={<span className="muted small">
                What the script asks for, against what they do
              </span>}
            >
              {r.average_gap_days === null ? (
                <p className="muted">
                  {/* Not "0% adherence". One fill is not a pattern, and a page
                      that invents a judgement from a single data point teaches
                      people to distrust the judgements that are real. */}
                  Filled {r.used === 1 ? "once" : `${r.used} times`}, which is
                  not enough to see a pattern — a gap needs two fills to
                  measure.
                </p>
              ) : (
                <p className={`st-note ${r.keeping_up ? "is-ok" : "is-bad"}`}>
                  {r.keeping_up ? (
                    <>
                      <CheckCircle size={14} weight="fill" /> Collecting every{" "}
                      {r.average_gap_days} days against a {r.interval_days}-day
                      supply. Roughly on time — nothing to chase.
                    </>
                  ) : (
                    <>
                      Running {r.average_gap_days - (r.interval_days || 0)} days
                      late between fills. On a {r.interval_days}-day supply that
                      is the same number of days every month with no medicine,
                      which is a clinical problem before it is a commercial one.
                    </>
                  )}
                </p>
              )}
              <dl className="kv">
                <dt>Taken so far</dt>
                <dd>{money(r.value_filled)} across {r.used} fill(s)</dd>
                <dt>Still to come</dt>
                <dd>{money(r.value_remaining)} over {r.left} fill(s)</dd>
              </dl>
            </Panel>
          </div>

          <Panel
            title="Every fill"
            count={r.fills.length}
            empty="This line has never been dispensed. If the script is old, the patient took it somewhere else."
          >
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Dispensed</th><th className="num">Qty</th>
                    <th>By</th><th>Collected</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {r.fills.map((f) => (
                    <tr key={f.id}>
                      <td>
                        {fmtDateTime(f.dispensed_at)}
                        {f.is_repeat && <span className="badge"> repeat</span>}
                      </td>
                      <td className="num">{f.quantity}</td>
                      <td>{f.by || <span className="muted">—</span>}</td>
                      <td>
                        {f.collected_at
                          ? fmtDate(f.collected_at)
                          : <span className="badge warn">on the shelf</span>}
                      </td>
                      <td className="actions">
                        <Link className="btn ghost sm" to={`/dispensings/${f.id}`}>
                          Open
                        </Link>
                      </td>
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
