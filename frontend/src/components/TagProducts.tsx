/** Filing what nobody has filed, by rule, with the answer shown first.
 *
 *  Ten thousand untagged lines is not a list anybody works through by hand. It
 *  is also not a problem you can solve by putting everything in MISC — that
 *  produces a department holding two thousand unrelated things, and the report
 *  it lands on is then wrong in a way nobody can see.
 *
 *  So: a schedule is decisive (S1 and above is a medicine a pharmacist hands
 *  over — that is what the schedule means, not a guess), then the name against
 *  a stated rule table, then the dosage form. Anything the rules cannot place
 *  is **left alone** and listed, worth first, so a pharmacist finishes it.
 *
 *  Two steps always. The preview is the whole department breakdown before
 *  anything is written, because a rule table that files fifteen hundred lines
 *  into the wrong place is worse than one that files none.
 */
import { useState } from "react";
import { CheckCircle, Tag } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "./BusyButton";
import { EntityLink } from "./Filters";
import { useToast } from "./Toast";

interface Plan {
  applied: boolean; considered: number; placed: number;
  unplaced: number; departments: Record<string, number>;
  created: string[]; message: string;
}
interface Unplaced {
  items: {
    id: number; name: string; stock_code: string; schedule: number;
    on_hand: number; value: number;
  }[];
  total: number; showing: number;
}

export default function TagProducts({ onDone }: { onDone?: () => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [left, setLeft] = useState<Unplaced | null>(null);
  const [retag, setRetag] = useState(false);
  const toast = useToast();

  async function preview() {
    try {
      setPlan(await api.post<Plan>("/api/stock-categories/tag",
                                   { apply: false, retag }));
    } catch (e) {
      toast.error(errorText(e, "That could not be worked out."));
    }
  }

  async function apply() {
    try {
      const r = await api.post<Plan>("/api/stock-categories/tag",
                                     { apply: true, retag });
      setPlan(r);
      toast.ok(r.message);
      onDone?.();
    } catch (e) {
      toast.error(errorText(e, "Nothing was filed."));
    }
  }

  async function showLeftovers() {
    try {
      setLeft(await api.get<Unplaced>("/api/stock-categories/unplaced?limit=200"));
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  const sorted = Object.entries(plan?.departments ?? {})
    .sort((a, b) => b[1] - a[1]);

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>File the untagged lines</h3>
          <span className="muted small">
            By schedule first, then by name, then by dosage form. Nothing is
            written until you have read where it would go.
          </span>
        </div>
        <BusyButton className="btn" onClick={preview} icon={Tag}
                    busyLabel="Working it out…">
          Work out where they go
        </BusyButton>
      </div>

      {plan && (
        <>
          <div className="wc-bands" style={{ marginTop: 12 }}>
            <div className="wl-stat">
              <b>{plan.considered.toLocaleString()}</b><span>lines looked at</span>
            </div>
            <div className="wl-stat">
              <b className="tone-ok">{plan.placed.toLocaleString()}</b>
              <span>the rules can file</span>
            </div>
            <div className="wl-stat">
              <b>{plan.unplaced.toLocaleString()}</b>
              <span>they cannot, and will not guess at</span>
            </div>
            <div className="wl-stat">
              <b>{sorted.length}</b><span>departments</span>
            </div>
          </div>

          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th>Department</th>
                  <th className="num">Lines</th>
                  <th>New?</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(([name, n]) => (
                  <tr key={name}>
                    <td><b>{name}</b></td>
                    <td className="num">{n.toLocaleString()}</td>
                    <td>
                      {/* Where the pharmacy already has a department for this,
                          the rules fold into it. Without that, a shop that has
                          used "COSMETICS" for ten years ends up with that and a
                          "Cosmetics & Fragrance" beside it. */}
                      {plan.created.includes(name)
                        ? <span className="badge warn">will be created</span>
                        : <span className="muted small">existing</span>}
                    </td>
                  </tr>
                ))}
                {!sorted.length && (
                  <tr><td colSpan={3} className="muted pad">
                    Nothing to file — every line already has a department.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>

          {plan.unplaced > 0 && (
            <p className="alert warn">
              <span>
                <b>{plan.unplaced.toLocaleString()} lines are left alone.</b> The
                rules cannot tell what they are from the name, the form or the
                schedule, and sweeping them into a catch-all department would
                put unrelated things on the same report and hide that it had
                happened.{" "}
                <button className="btn-link" onClick={showLeftovers}>
                  Show them, most valuable first
                </button>
              </span>
            </p>
          )}

          {plan.applied ? (
            <p className="alert ok">
              <CheckCircle size={16} weight="fill" />
              <span>{plan.message}</span>
            </p>
          ) : (
            <>
              <label className="check" style={{ marginTop: 10 }}>
                <input type="checkbox" checked={retag}
                       onChange={(e) => setRetag(e.target.checked)} />
                <span>
                  Also re-file lines that already have a department.{" "}
                  <span className="muted">
                    Off by default: somebody chose those, and a rule table does
                    not know better than a person who filed a line by hand.
                  </span>
                </span>
              </label>
              <BusyButton className="btn primary" onClick={apply}
                          disabled={!plan.placed} icon={Tag}
                          busyLabel="Filing…">
                {plan.placed
                  ? `File ${plan.placed.toLocaleString()} lines`
                  : "Nothing to file"}
              </BusyButton>
            </>
          )}
        </>
      )}

      {left && (
        <>
          <h4 className="cu-section">
            What the rules would not place — {left.showing.toLocaleString()} of{" "}
            {left.total.toLocaleString()}
          </h4>
          <p className="muted small">
            Worth first, because that is the order in which finishing the job
            pays. Open a line to file it.
          </p>
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th>Product</th><th>Code</th>
                  <th className="num">On hand</th>
                  <th className="num">At cost</th>
                </tr>
              </thead>
              <tbody>
                {left.items.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <EntityLink kind="product" id={p.id}>{p.name}</EntityLink>
                    </td>
                    <td className="mono small">{p.stock_code}</td>
                    <td className="num">{p.on_hand.toLocaleString()}</td>
                    <td className="num mono">{money(p.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
