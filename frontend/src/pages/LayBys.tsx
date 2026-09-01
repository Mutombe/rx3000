/** Lay-bys: goods held, paid off over time.
 *
 *  Five endpoints and no screen. Common in Zimbabwe for anything a customer
 *  cannot pay for at once — a nebuliser, a glucometer, a course of an expensive
 *  medicine, and it was unreachable.
 *
 *  Two things about a lay-by that the screen has to keep straight, because
 *  getting either wrong is an accounting error rather than an inconvenience:
 *
 *    The stock leaves the shelf when the lay-by is raised, not when it is paid
 *    off. It is held for that customer and must not be sold twice.
 *
 *    A deposit is money owed back, not money earned. Until the goods go, the
 *    pharmacy is holding the customer's money, which is why cancelling asks
 *    what fee to keep rather than assuming the deposit is forfeit.
 */
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDate, money } from "../api";
import { useConfirm } from "../components/Confirm";
import { useStepUp, CANCELLED } from "../components/StepUp";
import { TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { Patient, Product } from "../types";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import { EntityLink } from "../components/Filters";

type Status = "open" | "completed" | "cancelled";

interface Item { product_id: number; product: string; quantity: number; unit_price: number }
interface Payment { amount: number; method: string; at: string }
interface LayBy {
  id: number; layby_number: string; patient_id: number; patient: string;
  status: string; total: number; paid: number; balance: number;
  minimum_deposit: number; due_date: string | null; created_at: string | null;
  items: Item[]; payments: Payment[];
}
interface Listing { laybys: LayBy[]; total: number; showing: number }

export default function LayBys() {
  const toast = useToast();
  const confirm = useConfirm();
  const { guarded, prompt } = useStepUp();

  const [status, setStatus] = useState<Status>("open");
  const [list, setList] = useState<Listing | null>(null);
  const [busy, setBusy] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  // raising
  const [raising, setRaising] = useState(false);
  const [patientQ, setPatientQ] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [productQ, setProductQ] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [lines, setLines] = useState<{ product: Product; quantity: number }[]>([]);
  const [deposit, setDeposit] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [minPercent, setMinPercent] = useState("20");

  // paying
  const [paying, setPaying] = useState<LayBy | null>(null);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");

  const load = useCallback(() => {
    api.get<Listing>(`/api/laybys?status=${status}`)
      .then(setList)
      .catch((e) => toast.error(errorText(e, "The lay-bys could not be listed.")));
  }, [status, toast]);

  useEffect(load, [load]);

  useEffect(() => {
    if (patientQ.trim().length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=6`)
      .then(setPatients).catch(() => setPatients([]));
  }, [patientQ]);

  useEffect(() => {
    if (productQ.trim().length < 2) { setProducts([]); return; }
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(productQ)}&limit=6`)
      .then(setProducts).catch(() => setProducts([]));
  }, [productQ]);

  const total = lines.reduce((sum, l) => sum + l.product.unit_price * l.quantity, 0);
  const needed = total * (Number(minPercent) || 0) / 100;
  const shortOfMinimum = Number(deposit || 0) < needed - 0.005;

  async function raise(e: React.FormEvent) {
    e.preventDefault();
    if (!patient || lines.length === 0) return;
    setBusy("raise");
    try {
      const made = await api.post<LayBy & { message: string }>("/api/laybys", {
        patient_id: patient.id,
        items: lines.map((l) => ({ product_id: l.product.id, quantity: l.quantity })),
        deposit: Number(deposit) || 0,
        due_date: dueDate || null,
        minimum_deposit_percent: Number(minPercent) || 0,
      });
      toast.ok(made.message);
      setRaising(false);
      setPatient(null); setPatientQ(""); setLines([]); setDeposit("");
      setDueDate(""); setProductQ("");
      setStatus("open");
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  async function pay(e: React.FormEvent) {
    e.preventDefault();
    if (!paying) return;
    const n = Number(amount);
    if (!Number.isFinite(n) || n <= 0) {
      toast.error("Enter the amount the customer is paying.");
      return;
    }
    setBusy("pay");
    try {
      const res = await api.post<LayBy & { message: string }>(
        `/api/laybys/${paying.id}/pay`, { amount: n, method });
      toast.ok(res.message ?? `${money(n)} received.`);
      setPaying(null); setAmount("");
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  async function complete(l: LayBy) {
    const ok = await confirm({
      title: `Hand over ${l.layby_number}?`,
      body: `${l.patient} has paid ${money(l.paid)} of ${money(l.total)}. The goods `
          + `leave with the customer and the lay-by closes.`,
      confirmLabel: "Hand over the goods",
    });
    if (!ok) return;
    setBusy(`complete-${l.id}`);
    try {
      const res = await api.post<{ message: string }>(`/api/laybys/${l.id}/complete`, {});
      toast.ok(res.message ?? `${l.layby_number} completed.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function cancel(l: LayBy) {
    const ok = await confirm({
      title: `Cancel ${l.layby_number}?`,
      body: `${l.patient} has paid ${money(l.paid)}. The goods go back on the shelf `
          + `and the money is refunded, less any fee kept. A cancellation fee is `
          + `asked for next, and it may be zero.`,
      confirmLabel: "Cancel the lay-by",
      destructive: true,
    });
    if (!ok) return;
    // A fee is a judgement about somebody's money, so it is asked for explicitly
    // rather than defaulted to the deposit. Zero is a legitimate answer and the
    // usual one where the customer simply changed their mind.
    const fee = await askFee(l);
    if (fee === null) return;
    setBusy(`cancel-${l.id}`);
    try {
      const res = await guarded(
        "layby.cancel",
        (token) => api.post<{ message: string }>(
          `/api/laybys/${l.id}/cancel?fee=${fee}`, {}, token),
        l.layby_number,
      );
      if (res === CANCELLED) return;
      toast.ok(res.message ?? `${l.layby_number} cancelled.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  const [feeFor, setFeeFor] = useState<LayBy | null>(null);
  const [feeValue, setFeeValue] = useState("0");
  const [feeResolve, setFeeResolve] = useState<((n: number | null) => void) | null>(null);

  function askFee(l: LayBy): Promise<number | null> {
    setFeeFor(l);
    setFeeValue("0");
    return new Promise((resolve) => setFeeResolve(() => resolve));
  }

  return (
    <>
      {prompt}
      <div className="page-head">
        <div>
          <h1>Lay-bys</h1>
          <div className="sub">
            Goods held for a customer and paid off over time. The stock leaves the
            shelf when the lay-by is raised
          </div>
        </div>
        <button className="btn primary" onClick={() => setRaising(true)}>
          Raise a lay-by
        </button>
      </div>

      <div className="pill-tabs">
        {(["open", "completed", "cancelled"] as Status[]).map((s) => (
          <button key={s} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>
            {s[0].toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      <div className="card">
        {!list ? <TableSkeleton cols={5} rows={5} /> : list.laybys.length === 0 ? (
          <div className="empty">No {status} lay-bys.</div>
        ) : (
          <>
            {list.showing < list.total && (
              <p className="muted small">
                The {list.showing} most recent of {list.total}.
              </p>
            )}
            <div className="cu-scroll">
              <table>
                <thead>
                  <tr>
                    <th className="mono">Lay-by</th><th>Customer</th><th>Raised</th><th>Due</th>
                    <th className="num">Total</th><th className="num">Paid</th>
                    <th className="num">Balance</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {list.laybys.map((l) => (
                    // The key belongs on the outermost element a map returns; on
                    // the inner <tr> it is a console warning and a re-render bug
                    // waiting for the list to reorder.
                    <Fragment key={l.id}>
                      <tr className={overdue(l) ? "is-off" : ""}>
                        <td>
                          <button className="btn ghost small"
                            onClick={() => setExpanded(expanded === l.id ? null : l.id)}>
                            {l.layby_number}
                          </button>
                        </td>
                        <td>
                          <EntityLink kind="patient" id={l.patient_id}>
                            <span className="clip" title={l.patient}>{l.patient}</span>
                          </EntityLink>
                        </td>
                        <td>{l.created_at ? fmtDate(l.created_at) : "—"}</td>
                        <td className={overdue(l) ? "cu-diff" : ""}>
                          {l.due_date ? fmtDate(l.due_date) : "—"}
                        </td>
                        <td className="num">{money(l.total)}</td>
                        <td className="num">{money(l.paid)}</td>
                        <td className="num">{money(l.balance)}</td>
                        <td className="num lb-actions">
                          {l.status === "open" && (
                            <>
                              <button className="small" onClick={() => {
                                setPaying(l); setAmount(String(l.balance)); setMethod("cash");
                              }}>
                                Take payment
                              </button>
                              {/* Only once it is paid off. Handing goods over with a
                                  balance outstanding is a decision, not a button. */}
                              {l.balance <= 0.005 && (
                                <button className="small" disabled={busy === `complete-${l.id}`}
                                  onClick={() => complete(l)}>
                                  Hand over
                                </button>
                              )}
                              <button className="small ghost" disabled={busy === `cancel-${l.id}`}
                                onClick={() => cancel(l)}>
                                Cancel
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                      {expanded === l.id && (
                        <tr>
                          <td colSpan={8} className="lb-detail">
                            <div className="lb-cols">
                              <div>
                                <h4>Goods held</h4>
                                <ul>
                                  {l.items.map((i, n) => (
                                    <li key={n}>
                                      {i.quantity} × {i.product}
                                      <span className="muted"> @ {money(i.unit_price)}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                              <div>
                                <h4>Payments</h4>
                                {l.payments.length === 0 ? (
                                  <p className="muted">Nothing paid yet.</p>
                                ) : (
                                  <ul>
                                    {l.payments.map((p, n) => (
                                      <li key={n}>
                                        {money(p.amount)} <span className="muted">
                                          {p.method} · {fmtDate(p.at)}
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                                <p className="muted small">
                                  Minimum deposit agreed: {money(l.minimum_deposit)}
                                </p>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {raising && (
        <div className="modal-backdrop" onClick={() => setRaising(false)}>
          <form className="modal lb-modal" onClick={(e) => e.stopPropagation()} onSubmit={raise}>
            <h2>Raise a lay-by</h2>

            <label>
              Customer
              {patient ? (
                <div className="st-picked">
                  <b>{patient.first_name} {patient.last_name}</b>
                  <button type="button" className="btn ghost small"
                    onClick={() => { setPatient(null); setPatientQ(""); }}>Change</button>
                </div>
              ) : (
                <input value={patientQ} onChange={(e) => setPatientQ(e.target.value)}
                  placeholder="Search by name" autoFocus />
              )}
            </label>
            {!patient && patients.length > 0 && (
              <ul className="st-results">
                {patients.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => { setPatient(p); setPatients([]); }}>
                      {p.first_name} {p.last_name}
                      <span className="muted"> {p.phone}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <label>
              Goods
              <input value={productQ} onChange={(e) => setProductQ(e.target.value)}
                placeholder="Search for a product" />
            </label>
            {products.length > 0 && (
              <ul className="st-results">
                {products.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => {
                      setLines((ls) => ls.some((l) => l.product.id === p.id)
                        ? ls
                        : [...ls, { product: p, quantity: 1 }]);
                      setProductQ(""); setProducts([]);
                    }}>
                      {p.name}<span className="muted"> {money(p.unit_price)}</span>
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
                      <td>{l.product.name}</td>
                      <td className="num">
                        <input type="number" min={1} value={l.quantity} style={{ width: 70 }}
                          onChange={(e) => setLines((ls) => ls.map((x, n) =>
                            n === i ? { ...x, quantity: Math.max(1, Number(e.target.value) || 1) } : x))} />
                      </td>
                      <td className="num">{money(l.product.unit_price * l.quantity)}</td>
                      <td className="num">
                        <IconButton action="remove" onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))} type="button" />
                      </td>
                    </tr>
                  ))}
                  <tr>
                    <td><b>Total</b></td><td />
                    <td className="num"><b>{money(total)}</b></td><td />
                  </tr>
                </tbody>
              </table>
            )}

            <div className="form-row">
              <div className="field">
                <label>Deposit taken now</label>
                <input type="number" step="0.01" min="0" value={deposit}
                  onChange={(e) => setDeposit(e.target.value)} />
              </div>
              <div className="field">
                <label>Minimum deposit</label>
                <div className="gs-input">
                  <input type="number" step="1" min="0" max="100" value={minPercent}
                    onChange={(e) => setMinPercent(e.target.value)} />
                  <span className="gs-unit">%</span>
                </div>
              </div>
              <div className="field">
                <label>Due by <span className="muted">(optional)</span></label>
                <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </div>
            </div>

            {lines.length > 0 && shortOfMinimum && (
              // Said before the server refuses it, because the customer is
              // standing there and the answer is to take more money, not to
              // discover the rule after the fact.
              <p className="alert warn">
                {money(needed)} is the minimum deposit at {minPercent}% of{" "}
                {money(total)}. The pharmacy holds the stock until it is paid off,
                so a lay-by taken for less is stock off the shelf and not sold.
              </p>
            )}

            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setRaising(false)}>
                Cancel
              </button>
              <button type="submit" className="btn primary"
                disabled={busy === "raise" || !patient || lines.length === 0}>
                {busy === "raise" ? "Raising…" : "Raise the lay-by"}
              </button>
            </div>
          </form>
        </div>
      )}

      {paying && (
        <div className="modal-backdrop" onClick={() => setPaying(null)}>
          <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={pay}>
            <h2>Payment on {paying.layby_number}</h2>
            <p className="muted">
              {paying.patient} owes {money(paying.balance)} of {money(paying.total)}.
            </p>
            <label>
              Amount
              <input type="number" step="0.01" min="0.01" max={paying.balance}
                value={amount} autoFocus onChange={(e) => setAmount(e.target.value)} />
            </label>
            <label>
              Method
              <Select
                value={String(method ?? "")}
                onChange={(__value) => setMethod(__value)}
                options={[{ value: "cash", label: "Cash" }, { value: "card", label: "Card" }, { value: "mobile_money", label: "Mobile money" }]}
              />
            </label>
            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setPaying(null)}>Cancel</button>
              <button type="submit" className="btn primary" disabled={busy === "pay"}>
                {busy === "pay" ? "Saving…" : "Take the payment"}
              </button>
            </div>
          </form>
        </div>
      )}

      {feeFor && (
        <div className="modal-backdrop">
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Cancellation fee</h2>
            <p className="muted">
              {feeFor.patient} has paid {money(feeFor.paid)}. Whatever is not kept
              as a fee is refunded. Zero is a normal answer.
            </p>
            <label>
              Fee to keep
              <input type="number" step="0.01" min="0" max={feeFor.paid} value={feeValue}
                autoFocus onChange={(e) => setFeeValue(e.target.value)} />
            </label>
            <p className="muted small">
              Refunding {money(Math.max(0, feeFor.paid - (Number(feeValue) || 0)))}.
            </p>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => {
                feeResolve?.(null); setFeeFor(null); setFeeResolve(null);
              }}>Back</button>
              <button className="btn primary" onClick={() => {
                const n = Math.max(0, Math.min(Number(feeValue) || 0, feeFor.paid));
                feeResolve?.(n); setFeeFor(null); setFeeResolve(null);
              }}>Continue</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function overdue(l: LayBy): boolean {
  if (l.status !== "open" || !l.due_date) return false;
  return new Date(l.due_date) < new Date();
}
