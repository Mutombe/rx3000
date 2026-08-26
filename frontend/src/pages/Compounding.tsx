/** Compounding: formulae, what they cost to make, and making them up.
 *
 *  Four endpoints and no screen. A compound is not a product on a shelf — it is
 *  assembled from ingredients when somebody orders it — so without this the
 *  formula book existed and nothing could be made from it.
 *
 *  The thing this screen must not bury is the schedule. A cream containing
 *  Tramadol is a Schedule 5 preparation, whatever the base is, and the server
 *  says so: it returns an effective schedule and where it came from — "Schedule
 *  5, inherited from Tramadol". Compounding a controlled preparation while
 *  believing it is a cream is how a pharmacy ends up with a register that does
 *  not balance and no idea why, so the inherited schedule is stated on the
 *  formula and again before it is prepared.
 *
 *  Cost is shown per batch with the ingredients itemised, because the whole point
 *  of a formula is that the price is derived rather than guessed: ingredients at
 *  cost, plus the compounding fee, for the yield stated.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, money } from "../api";
import { useConfirm } from "../components/Confirm";
import { TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { Product } from "../types";
import Select from "../components/Select";
import IconButton from "../components/IconButton";

interface Ingredient {
  product_id: number; quantity: number; unit: string; note: string;
  product?: Product | null;
}
interface Mixture {
  id: number; code: string; name: string; form: string;
  yield_quantity: number; yield_unit: string; compounding_fee: number;
  shelf_life_days: number; method: string; directions: string;
  active: boolean; ingredients: Ingredient[];
}
interface CostLine {
  product_id: number; name: string; quantity: number; unit: string;
  unit_cost: number; line_cost: number; schedule: number;
  on_hand: number; short: boolean;
}
interface Cost {
  mixture: string; code: string; form: string; batches: number;
  yield_quantity: number; yield_unit: string;
  ingredient_cost: number; compounding_fee: number; total_cost: number;
  effective_schedule: number; schedule_source: string;
  can_prepare: boolean; short_of: string[]; ingredients: CostLine[];
}

export default function Compounding() {
  const toast = useToast();
  const confirm = useConfirm();
  const [mixtures, setMixtures] = useState<Mixture[] | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [cost, setCost] = useState<Cost | null>(null);
  const [batches, setBatches] = useState("1");
  const [busy, setBusy] = useState("");

  // new formula
  const [adding, setAdding] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [form, setForm] = useState("mixture");
  const [yieldQty, setYieldQty] = useState("100");
  const [yieldUnit, setYieldUnit] = useState("ml");
  const [fee, setFee] = useState("0");
  const [shelfLife, setShelfLife] = useState("30");
  const [method, setMethod] = useState("");
  const [directions, setDirections] = useState("");
  const [productQ, setProductQ] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [lines, setLines] = useState<{ product: Product; quantity: string; unit: string }[]>([]);

  const load = useCallback(() => {
    api.get<Mixture[]>("/api/compounding/mixtures")
      .then(setMixtures)
      .catch((e) => toast.error(errorText(e, "The formulae could not be listed.")));
  }, [toast]);

  useEffect(load, [load]);

  useEffect(() => {
    if (productQ.trim().length < 2) { setProducts([]); return; }
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(productQ)}&limit=6`)
      .then(setProducts).catch(() => setProducts([]));
  }, [productQ]);

  const costFor = useCallback((id: number, n: string) => {
    api.get<Cost>(`/api/compounding/mixtures/${id}/cost?batches=${Number(n) || 1}`)
      .then(setCost)
      .catch((e) => toast.error(errorText(e, "The cost could not be worked out.")));
  }, [toast]);

  function open(m: Mixture) {
    if (openId === m.id) { setOpenId(null); setCost(null); return; }
    setOpenId(m.id);
    setCost(null);
    setBatches("1");
    costFor(m.id, "1");
  }

  async function prepare(m: Mixture) {
    if (!cost) return;
    const controlled = cost.effective_schedule >= 5;
    const ok = await confirm({
      title: `Make up ${cost.batches} × ${m.name}?`,
      body: `${cost.ingredients.length} ingredient(s) leave stock at a cost of `
          + `${money(cost.ingredient_cost)}, yielding ${cost.yield_quantity} `
          + `${cost.yield_unit}.`
          // Said at the point of preparing, not only on the formula. Somebody
          // making up a cream needs to know it is a controlled preparation before
          // they make it, not when the register is counted.
          + (controlled
            ? ` This is a Schedule ${cost.effective_schedule} preparation. `
              + `${cost.schedule_source} It must be recorded in the controlled register.`
            : ""),
      confirmLabel: "Make it up",
    });
    if (!ok) return;
    setBusy("prepare");
    try {
      const res = await api.post<{ message?: string }>(
        `/api/compounding/mixtures/${m.id}/prepare?batches=${Number(batches) || 1}`, {});
      toast.ok(res.message ?? `${m.name} made up.`);
      costFor(m.id, batches);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy("create");
    try {
      await api.post("/api/compounding/mixtures", {
        code: code.trim().toUpperCase(), name: name.trim(), form,
        yield_quantity: Number(yieldQty) || 1, yield_unit: yieldUnit.trim(),
        compounding_fee: Number(fee) || 0,
        shelf_life_days: Number(shelfLife) || 30,
        method: method.trim(), directions: directions.trim(),
        ingredients: lines.map((l) => ({
          product_id: l.product.id,
          quantity: Number(l.quantity) || 0,
          unit: l.unit.trim() || "unit",
        })),
      });
      toast.ok(`${name} added to the formula book.`);
      setAdding(false);
      setCode(""); setName(""); setMethod(""); setDirections(""); setLines([]);
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Compounding</h1>
          <div className="sub">
            The formula book: what goes into each preparation, what it costs, and
            making it up
          </div>
        </div>
        <button className="btn primary" onClick={() => setAdding(true)}>
          Add a formula
        </button>
      </div>

      <div className="card">
        {!mixtures ? <TableSkeleton cols={5} rows={4} /> : mixtures.length === 0 ? (
          <div className="empty">
            No formulae yet. A formula records what goes into a preparation, so the
            price and the schedule follow from the ingredients rather than being
            typed in each time.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Code</th><th>Preparation</th><th>Form</th>
                <th className="num">Yield</th><th className="num">Fee</th>
                <th className="num">Ingredients</th><th className="num">Shelf life</th>
              </tr>
            </thead>
            <tbody>
              {mixtures.map((m) => (
                <tr key={m.id} className={openId === m.id ? "is-open" : ""}>
                  <td>
                    <button className="btn ghost small mono" onClick={() => open(m)}>
                      {m.code}
                    </button>
                  </td>
                  <td>{m.name}{!m.active && <span className="badge muted">inactive</span>}</td>
                  <td>{m.form}</td>
                  <td className="num">{m.yield_quantity} {m.yield_unit}</td>
                  <td className="num">{money(m.compounding_fee)}</td>
                  <td className="num">{m.ingredients.length}</td>
                  <td className="num">{m.shelf_life_days} days</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {openId !== null && mixtures && (
        <div className="card">
          {!cost ? <TableSkeleton cols={4} rows={3} /> : (
            <>
              <div className="cu-head">
                <h3 style={{ margin: 0 }}>{cost.mixture}</h3>
                {/* The inherited schedule, stated on the formula. A cream with
                    Tramadol in it is a Schedule 5 preparation. */}
                {cost.effective_schedule > 0 && (
                  <span className={`badge ${cost.effective_schedule >= 5 ? "warn" : "sched"}`}>
                    Schedule {cost.effective_schedule}
                  </span>
                )}
              </div>
              {cost.schedule_source && (
                <p className="muted">{cost.schedule_source}</p>
              )}

              <div className="form-row" style={{ alignItems: "flex-end" }}>
                <div className="field" style={{ maxWidth: 140 }}>
                  <label>Batches</label>
                  <input type="number" min="0.25" step="0.25" value={batches}
                    onChange={(e) => {
                      setBatches(e.target.value);
                      costFor(openId, e.target.value);
                    }} />
                </div>
                <p className="muted">
                  Yields {cost.yield_quantity} {cost.yield_unit}.
                </p>
              </div>

              <table>
                <thead>
                  <tr>
                    <th>Ingredient</th><th className="num">Needed</th>
                    <th className="num">Unit cost</th><th className="num">Line</th>
                    <th className="num">On hand</th><th>Schedule</th>
                  </tr>
                </thead>
                <tbody>
                  {cost.ingredients.map((i) => (
                    <tr key={i.product_id} className={i.short ? "is-off" : ""}>
                      <td><span className="clip" title={i.name}>{i.name}</span></td>
                      <td className="num">{i.quantity} {i.unit}</td>
                      <td className="num">{money(i.unit_cost)}</td>
                      <td className="num">{money(i.line_cost)}</td>
                      <td className={`num${i.short ? " cu-diff" : ""}`}>{i.on_hand}</td>
                      <td>{i.schedule > 0 ? `S${i.schedule}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3}>Ingredients</td>
                    <td className="num">{money(cost.ingredient_cost)}</td>
                    <td colSpan={2} />
                  </tr>
                  <tr>
                    <td colSpan={3}>Compounding fee</td>
                    <td className="num">{money(cost.compounding_fee)}</td>
                    <td colSpan={2} />
                  </tr>
                  <tr>
                    <td colSpan={3}><b>Cost to make</b></td>
                    <td className="num"><b>{money(cost.total_cost)}</b></td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>

              {!cost.can_prepare && (
                <p className="st-note is-bad">
                  Not enough stock to make this up: {cost.short_of.join(", ")}.
                </p>
              )}

              <div className="cu-actions">
                <button
                  className="btn primary"
                  disabled={busy === "prepare" || !cost.can_prepare}
                  onClick={() => prepare(mixtures.find((m) => m.id === openId)!)}
                >
                  {busy === "prepare" ? "Making up…" : "Make it up"}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {adding && (
        <div className="modal-backdrop" onClick={() => setAdding(false)}>
          <form className="modal lb-modal" onClick={(e) => e.stopPropagation()} onSubmit={create}>
            <h2>Add a formula</h2>
            <div className="form-row">
              <div className="field">
                <label>Code</label>
                <input value={code} onChange={(e) => setCode(e.target.value)}
                  placeholder="e.g. CALAMINE" required />
              </div>
              <div className="field">
                <label>Name</label>
                <input value={name} onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Calamine lotion BP" required />
              </div>
            </div>
            <div className="form-row">
              <div className="field">
                <label>Form</label>
                <Select
                  value={String(form ?? "")}
                  onChange={(__value) => setForm(__value)}
                  options={[{ value: "mixture", label: "Mixture" }, { value: "cream", label: "Cream" }, { value: "ointment", label: "Ointment" }, { value: "lotion", label: "Lotion" }, { value: "powder", label: "Powder" }, { value: "capsule", label: "Capsules" }]}
                />
              </div>
              <div className="field">
                <label>Yield</label>
                <input type="number" min="0" step="0.01" value={yieldQty}
                  onChange={(e) => setYieldQty(e.target.value)} />
              </div>
              <div className="field">
                <label>Unit</label>
                <input value={yieldUnit} onChange={(e) => setYieldUnit(e.target.value)} />
              </div>
            </div>
            <div className="form-row">
              <div className="field">
                <label>Compounding fee</label>
                <input type="number" min="0" step="0.01" value={fee}
                  onChange={(e) => setFee(e.target.value)} />
              </div>
              <div className="field">
                <label>Shelf life (days)</label>
                <input type="number" min="1" step="1" value={shelfLife}
                  onChange={(e) => setShelfLife(e.target.value)} />
              </div>
            </div>

            <label>
              Ingredients
              <input value={productQ} onChange={(e) => setProductQ(e.target.value)}
                placeholder="Search for a product" />
            </label>
            {products.length > 0 && (
              <ul className="st-results">
                {products.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => {
                      setLines((ls) => ls.some((l) => l.product.id === p.id) ? ls
                        : [...ls, { product: p, quantity: "1", unit: "unit" }]);
                      setProductQ(""); setProducts([]);
                    }}>
                      {p.name}
                      {p.schedule > 0 && <span className="badge sched">S{p.schedule}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {lines.length > 0 && (
              <table className="lb-lines">
                <tbody>
                  {lines.map((l, i) => (
                    <tr key={l.product.id}>
                      <td>
                        {l.product.name}
                        {/* Shown while the formula is being written, because the
                            preparation inherits the highest schedule in it. */}
                        {l.product.schedule > 0 && (
                          <span className="badge sched">S{l.product.schedule}</span>
                        )}
                      </td>
                      <td className="num">
                        <input type="number" min="0" step="0.01" style={{ width: 80 }}
                          value={l.quantity}
                          onChange={(e) => setLines((ls) => ls.map((x, n) =>
                            n === i ? { ...x, quantity: e.target.value } : x))} />
                      </td>
                      <td>
                        <input style={{ width: 70 }} value={l.unit}
                          onChange={(e) => setLines((ls) => ls.map((x, n) =>
                            n === i ? { ...x, unit: e.target.value } : x))} />
                      </td>
                      <td className="num">
                        <IconButton action="remove" onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))} type="button" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {lines.some((l) => (l.product.schedule ?? 0) >= 5) && (
              <p className="alert warn">
                This formula contains a controlled ingredient, so the preparation
                will be a Schedule {Math.max(...lines.map((l) => l.product.schedule ?? 0))}{" "}
                medicine and must be dispensed and recorded as one.
              </p>
            )}

            <label>
              Method
              <textarea rows={3} value={method} onChange={(e) => setMethod(e.target.value)}
                placeholder="How it is made up. The steps somebody follows at the bench." />
            </label>
            <label>
              Directions for the label
              <textarea rows={2} value={directions}
                onChange={(e) => setDirections(e.target.value)} />
            </label>

            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setAdding(false)}>
                Cancel
              </button>
              <button type="submit" className="btn primary"
                disabled={busy === "create" || lines.length === 0}>
                {busy === "create" ? "Saving…" : "Add the formula"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
