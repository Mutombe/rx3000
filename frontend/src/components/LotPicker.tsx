/** Which lot is going out, and what it costs to change it.
 *
 *  First expiry first out decides this, and it is right almost always. Almost
 *  is what this control is for. A dispenser at the shelf sometimes has a good
 *  reason to hand over a different lot, and there was no way to say so: the
 *  picker took the earliest expiry and nothing else was possible. So the
 *  override happened anyway, off the system, by the dispenser handing over the
 *  pack in their hand while the software recorded a different one. The shelf
 *  figure stayed right in total and every batch number on every record was
 *  wrong, which is worse than either.
 *
 *  A recall is what makes that matter. The one question a recall asks is which
 *  patients got lot ABC1234.
 *
 *  WHY IT IS SHUT BY DEFAULT
 *
 *  Because the rotation is almost always right, and a control that demands a
 *  decision on every dispensing is one that gets clicked through. Shut, it
 *  says which lot is going out. Opened, it offers the others. Choosing the
 *  front one again costs nothing; choosing another asks why and then asks for
 *  a password, which the server decides and this component only relays.
 */
import { useCallback, useEffect, useState } from "react";

import { api, errorText, fmtDate } from "../api";
import { useToast } from "./Toast";

export interface Lot {
  batch_id: number;
  batch_number: string;
  expiry: string;
  remaining: number;
  held: boolean;
  expired: boolean;
  next_out: boolean;
  may_dispense: boolean;
}

export interface LotChoice {
  batch_id: number | null;
  reason: string;
  note: string;
}

/** Nothing chosen: the rotation decides, which is the ordinary case. */
export const ROTATION: LotChoice = { batch_id: null, reason: "", note: "" };

export default function LotPicker({
  productId, productName, value, onChange,
}: {
  productId: number;
  productName?: string;
  value: LotChoice;
  onChange: (next: LotChoice) => void;
}) {
  const toast = useToast();
  const [lots, setLots] = useState<Lot[]>([]);
  const [reasons, setReasons] = useState<{ code: string; says: string }[]>([]);
  const [showing, setShowing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [asked, setAsked] = useState(false);

  const front = lots.find((l) => l.next_out);
  const chosen = lots.find((l) => l.batch_id === value.batch_id);
  /** Departing from the rotation, which is the only case that costs anything. */
  const jumping = !!chosen && !chosen.next_out;

  const load = useCallback(() => {
    if (asked) return;
    setAsked(true);
    setLoading(true);
    api.get<{ lots: Lot[]; reasons: { code: string; says: string }[] }>(
      `/api/stock/lots/${productId}`)
      .then((r) => { setLots(r.lots); setReasons(r.reasons); })
      .catch((e) => toast.error(errorText(e, "The lots could not be read.")))
      .finally(() => setLoading(false));
  }, [asked, productId, toast]);

  // The front lot is worth naming before anybody asks, because it is what is
  // about to happen. The rest are fetched with it: one request, and the list
  // is short.
  useEffect(() => { load(); }, [load]);

  // A product changing under the control means a different shelf entirely.
  useEffect(() => {
    setAsked(false); setLots([]); setShowing(false);
  }, [productId]);

  function pick(lot: Lot) {
    if (!lot.may_dispense) return;
    if (lot.next_out) { onChange(ROTATION); return; }
    onChange({ ...value, batch_id: lot.batch_id });
  }

  if (loading && !lots.length) {
    return <p className="muted small lot-say">Reading the shelf…</p>;
  }
  if (!lots.length) return null;

  return (
    <div className={`lot-pick${jumping ? " jumping" : ""}`}>
      <div className="lot-head">
        <span className="muted small">
          {front
            ? <>Going out: <b>{front.batch_number || "unnamed lot"}</b>
                {front.expiry ? `, expires ${fmtDate(front.expiry)}` : ""}</>
            : "No lot on this shelf may be dispensed."}
        </span>
        {lots.length > 1 && (
          <button type="button" className="btn-link small"
                  onClick={() => setShowing(!showing)}>
            {showing ? "Close" : `Choose another (${lots.length - 1})`}
          </button>
        )}
      </div>

      {showing && (
        <>
          <ul className="lot-list">
            {lots.map((l) => {
              const on = l.next_out ? !value.batch_id : value.batch_id === l.batch_id;
              return (
                <li key={l.batch_id}>
                  <button
                    type="button"
                    className={`lot-row${on ? " on" : ""}`}
                    disabled={!l.may_dispense}
                    onClick={() => pick(l)}
                  >
                    <span className="lot-name">{l.batch_number || "unnamed"}</span>
                    <span className="muted small">
                      {l.expiry ? `expires ${fmtDate(l.expiry)}` : "no expiry recorded"}
                      {" · "}{l.remaining.toLocaleString()} left
                    </span>
                    {l.next_out && <span className="badge ok">rotation</span>}
                    {l.expired && <span className="badge danger">expired</span>}
                    {l.held && <span className="badge warn">held</span>}
                  </button>
                </li>
              );
            })}
          </ul>

          {/* Only once somebody has actually stepped past the rotation. Asking
              why before they have chosen anything is a question about nothing. */}
          {jumping && (
            <div className="lot-why">
              <p className="muted small">
                {chosen?.batch_number} is not the lot the rotation would take.
                {" "}Say why, and a supervisor's password will be asked for.
              </p>
              <div className="lot-reasons">
                {reasons.map((r) => (
                  <button type="button" key={r.code}
                          className={`lot-reason${value.reason === r.code ? " on" : ""}`}
                          onClick={() => onChange({ ...value, reason: r.code })}>
                    {r.says}
                  </button>
                ))}
              </div>
              {/* Required by the server for "other", and the refusal says so.
                  Offered for every reason, because the useful ones are written
                  down rather than chosen. */}
              <input
                className="lot-note"
                value={value.note}
                maxLength={200}
                placeholder={value.reason === "other"
                  ? "Write down what the reason is"
                  : "Anything worth recording (optional)"}
                onChange={(e) => onChange({ ...value, note: e.target.value })}
              />
            </div>
          )}
        </>
      )}

      {/* Said even when the list is shut, because it changes what happens. */}
      {jumping && !showing && (
        <p className="muted small lot-say">
          Taking {chosen?.batch_number} ahead of the rotation
          {productName ? ` for ${productName}` : ""}.
        </p>
      )}
    </div>
  );
}
