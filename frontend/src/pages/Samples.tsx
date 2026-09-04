/** The sample register: medicine in the building that is not stock.
 *
 *  A representative leaves a box on the counter. It is medicine, it is here, and
 *  it is not stock — not bought, not sellable, on no invoice. That is exactly why
 *  it disappears from the records, because everything else arrives through a
 *  purchase order and leaves through a till.
 *
 *  Reads as a register rather than a list: a receipt, its movements underneath,
 *  and a balance that descends. Expiring stock that is still held is called out
 *  at the top, because that is the finding an inspector writes down and it is not
 *  something anybody goes looking for.
 */
import { useCallback, useEffect, useState } from "react";
import { CaretDown, CaretRight, Plus, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime } from "../api";
import { useOptimisticList, rowClass } from "../hooks/useOptimisticList";
import BusyButton from "../components/BusyButton";
import Select from "../components/Select";
import { TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { EntityLink } from "../components/Filters";

interface Receipt {
  product_id: number;
  id: number;
  reference: string;
  product: string;
  schedule: number | null;
  supplier_name: string;
  representative: string;
  batch_number: string;
  expiry_date: string | null;
  quantity_received: number;
  quantity_remaining: number;
  received_at: string;
  received_by: string;
  expired: boolean;
  attention: string;
  notes: string;
}

interface Register {
  items: Receipt[];
  total: number;
  open: number;
  units_held: number;
  expired_open: number;
}

interface Movement {
  id: number;
  movement: string;
  label: string;
  quantity: number;
  balance_after: number;
  given_to: string;
  witness: string;
  reason: string;
  by: string;
  created_at: string;
}

const MOVEMENTS = [
  { value: "issued", label: "Given to a patient" },
  { value: "returned", label: "Returned to the representative" },
  { value: "destroyed", label: "Destroyed" },
  { value: "expired", label: "Written off, out of date" },
  { value: "counted", label: "Counted, balance corrected" },
];

export default function Samples() {
  const [reg, setReg] = useState<Register | null>(null);
  const [failed, setFailed] = useState("");
  const [openOnly, setOpenOnly] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [history, setHistory] = useState<Movement[]>([]);
  const [adding, setAdding] = useState(false);
  const toast = useToast();

  // Receive form
  const [products, setProducts] = useState<{ id: number; name: string; strength: string }[]>([]);
  const [form, setForm] = useState({
    product_id: "", quantity: "", supplier_name: "", representative: "",
    batch_number: "", expiry_date: "", notes: "",
  });

  // Movement form
  const [move, setMove] = useState({ movement: "issued", quantity: "", given_to: "", reason: "" });
  const [staff, setStaff] = useState<{ id: number; full_name: string }[]>([]);
  const [witness, setWitness] = useState("");

  /* The receipts, with the one just booked already among them.
   *
   * `reg` keeps the totals; the hook keeps the rows. A placeholder is a row
   * this shop has but the server has not counted yet, so the header figures
   * stay a beat behind on purpose — "open receipts: 12" is the server's count
   * and should not claim 13 before the server agrees. */
  const list = useOptimisticList<Receipt>({
    load: async () => {
      const r = await api.get<Register>(`/api/samples?only_open=${openOnly}`);
      setReg(r);
      setFailed("");
      return r.items ?? [];
    },
    key: (r) => r.id,
  });
  const load = list.reload;

  useEffect(() => {
    // The register is read afresh when the filter changes.
    list.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openOnly]);
  useEffect(() => {
    api.get<any[]>("/api/products?limit=300").then((r) =>
      setProducts((Array.isArray(r) ? r : (r as any).items ?? []).map((p: any) =>
        ({ id: p.id, name: p.name, strength: p.strength ?? "" })))).catch(() => {});
    api.get<any[]>("/api/auth/users").then(setStaff).catch(() => {});
  }, []);

  async function openRow(r: Receipt) {
    if (expanded === r.id) { setExpanded(null); return; }
    setExpanded(r.id);
    setHistory([]);
    setMove({ movement: "issued", quantity: "", given_to: "", reason: "" });
    setWitness("");
    try {
      const h = await api.get<{ movements: Movement[] }>(`/api/samples/${r.id}/history`);
      setHistory(h.movements);
    } catch { /* the row still opens; the form is the point of it */ }
  }

  async function receive() {
    const body = {
      product_id: Number(form.product_id),
      quantity: Number(form.quantity),
      supplier_name: form.supplier_name,
      representative: form.representative,
      batch_number: form.batch_number,
      expiry_date: form.expiry_date || null,
      notes: form.notes,
    };
    // What the row will say while the server is deciding. Named from the
    // picker rather than left blank: a placeholder that says nothing is a
    // grey bar, and a grey bar does not confirm you booked the right product.
    const named = products.find((x) => x.id === body.product_id);
    const draft = {
      ...body,
      product: named ? `${named.name} ${named.strength}`.trim() : "",
      quantity_left: body.quantity,
    } as unknown as Receipt;

    setAdding(false);
    const ok = await list.create(
      draft,
      () => api.post<Receipt>("/api/samples", body),
      "Booked into the register.",
    );
    if (ok) {
      setForm({ product_id: "", quantity: "", supplier_name: "", representative: "",
                batch_number: "", expiry_date: "", notes: "" });
    } else {
      // Reopened holding what they typed. A sample receipt is eight fields off
      // a delivery note, and retyping them because a batch number clashed is
      // the kind of thing that makes people keep the paper register instead.
      setAdding(true);
    }
  }

  async function record(r: Receipt) {
    try {
      await api.post(`/api/samples/${r.id}/movements`, {
        movement: move.movement,
        quantity: Number(move.quantity),
        given_to: move.given_to,
        witness_id: witness ? Number(witness) : null,
        reason: move.reason,
      });
      toast.ok("Recorded.");
      await openRow(r);           // closes
      await openRow(r);           // and reopens with the new movement
      await load();
    } catch (e) {
      toast.error(errorText(e, "That movement was refused. Nothing was saved."));
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Sample register</h1>
          <div className="sub">
            Medicine left by representatives. Not stock, and accountable all the same
          </div>
        </div>
        <button onClick={() => setAdding((a) => !a)}>
          <Plus size={14} weight="bold" /> Book in samples
        </button>
      </div>

      {failed && <div className="alert error">{failed}</div>}

      {/* The finding an inspector writes down, said before anybody has to look
          for it. */}
      {reg && reg.expired_open > 0 && (
        <div className="alert warn">
          <Warning size={15} weight="fill" />{" "}
          <b>{reg.expired_open} receipt{reg.expired_open === 1 ? " is" : "s are"} out of date
          and still on the register.</b>{" "}
          Expired medicine on the shelf is a finding. Write it off with a witness.
        </div>
      )}

      <div className="wc-bands">
        <div className="wl-stat"><b>{reg?.open ?? "—"}</b><span>open receipts</span></div>
        <div className="wl-stat"><b>{reg?.units_held ?? "—"}</b><span>units held</span></div>
        <div className="wl-stat"><b>{reg?.total ?? "—"}</b><span>ever received</span></div>
      </div>

      {adding && (
        <div className="card">
          <h3>Book in what was left</h3>
          <div className="form-grid">
            <label className="field span-2">
              Medicine
              <Select
                value={form.product_id} searchable placeholder="Search the catalogue…"
                onChange={(v) => setForm({ ...form, product_id: v })}
                options={products.map((p) => ({
                  value: String(p.id), label: `${p.name} ${p.strength}`.trim(),
                }))}
              />
            </label>
            <label className="field">
              Quantity
              <input inputMode="numeric" value={form.quantity}
                     onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
            </label>
            <label className="field">
              Batch number
              <input value={form.batch_number}
                     onChange={(e) => setForm({ ...form, batch_number: e.target.value })} />
            </label>
            <label className="field">
              Who left them
              <input placeholder="e.g. Pharmanova Zimbabwe" value={form.supplier_name}
                     onChange={(e) => setForm({ ...form, supplier_name: e.target.value })} />
              <span className="field-hint">
                Required. A sample with no source cannot be returned or queried.
              </span>
            </label>
            <label className="field">
              Representative
              <input placeholder="the person who came in" value={form.representative}
                     onChange={(e) => setForm({ ...form, representative: e.target.value })} />
            </label>
            <label className="field">
              Expiry
              <input type="date" value={form.expiry_date}
                     onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} />
              <span className="field-hint">
                Asked for, not required: it is often only on the blister inside.
              </span>
            </label>
            <label className="field span-2">
              Notes
              <input value={form.notes}
                     onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </label>
          </div>
          <div className="modal-actions">
            <button className="secondary" onClick={() => setAdding(false)}>Cancel</button>
            <BusyButton onClick={receive} busyLabel="Booking in…">Book in</BusyButton>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Register</h3>
          <label className="inline-check">
            <input type="checkbox" checked={openOnly}
                   onChange={(e) => setOpenOnly(e.target.checked)} />
            Only receipts with units left
          </label>
        </div>

        {!reg && !failed && <TableSkeleton cols={6} rows={5} />}
        {reg && list.items.length === 0 && (
          <div className="empty">
            <b>Nothing in the register.</b>
            <p>
              When a representative leaves samples, book them in here. They are
              medicine on your premises that arrived through no purchase order and
              will leave through no till, so this is the only record there will be
              of what came in and where it went.
            </p>
            <button className="btn secondary small" onClick={() => setAdding(true)}>
              Book in samples
            </button>
          </div>
        )}

        {reg && list.items.length > 0 && (
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th /><th>Reference</th><th>Medicine</th><th>From</th>
                  <th>Expiry</th><th className="num">Left</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((r) => (
                  <>
                    <tr key={r.id}
                        className={`row-click ${rowClass(list.stateOf(r))}`.trim()}
                        onClick={() => !list.isPending(r) && openRow(r)}>
                      <td>{expanded === r.id ? <CaretDown size={13} /> : <CaretRight size={13} />}</td>
                      <td className="mono">{r.reference}</td>
                      <td>
                        <EntityLink kind="product" id={r.product_id}>{r.product}</EntityLink>
                        {(r.schedule ?? 0) >= 3 && <span className="badge sched">S{r.schedule}</span>}
                        {r.batch_number && <div className="muted small">batch {r.batch_number}</div>}
                      </td>
                      <td>
                        {r.supplier_name}
                        {r.representative && <div className="muted small">{r.representative}</div>}
                      </td>
                      <td>
                        {r.expiry_date ? fmtDate(r.expiry_date) : <span className="muted">not recorded</span>}
                        {r.attention && <div className="badge danger">{r.attention}</div>}
                      </td>
                      <td className="num">
                        {r.quantity_remaining} <span className="muted">of {r.quantity_received}</span>
                      </td>
                    </tr>
                    {expanded === r.id && (
                      <tr key={`${r.id}-detail`} className="detail-row">
                        <td colSpan={6}>
                          {/* The register underneath the receipt, oldest first,
                              with the balance descending. A balance that does not
                              descend is the thing an inspector notices. */}
                          {history.length > 0 ? (
                            <table className="dt sub">
                              <thead>
                                <tr>
                                  <th>When</th><th>What</th><th className="num">Qty</th>
                                  <th className="num">Balance</th><th>To</th><th>By</th>
                                </tr>
                              </thead>
                              <tbody>
                                {history.map((m) => (
                                  <tr key={m.id}>
                                    <td>{fmtDateTime(m.created_at)}</td>
                                    <td>
                                      {m.label}
                                      {m.reason && <div className="muted small">{m.reason}</div>}
                                    </td>
                                    <td className="num">{m.quantity}</td>
                                    <td className="num">{m.balance_after}</td>
                                    <td>{m.given_to || <span className="muted">—</span>}</td>
                                    <td>
                                      {m.by}
                                      {m.witness && <div className="muted small">witness {m.witness}</div>}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          ) : (
                            <p className="muted">Nothing has moved against this receipt yet.</p>
                          )}

                          <div className="form-grid" style={{ marginTop: 12 }}>
                            <label className="field">
                              Movement
                              <Select value={move.movement} options={MOVEMENTS}
                                      onChange={(v) => setMove({ ...move, movement: v })} />
                            </label>
                            <label className="field">
                              Quantity
                              <input inputMode="numeric" value={move.quantity}
                                     onChange={(e) => setMove({ ...move, quantity: e.target.value })} />
                            </label>
                            {move.movement === "issued" && (
                              <label className="field">
                                Given to
                                <input value={move.given_to}
                                       onChange={(e) => setMove({ ...move, given_to: e.target.value })} />
                                <span className="field-hint">Required. A sample handed over with no name is the one you get asked about.</span>
                              </label>
                            )}
                            {move.movement === "destroyed" && (
                              <label className="field">
                                Witnessed by
                                <Select value={witness} onChange={setWitness}
                                        placeholder="a second person"
                                        options={staff.map((u) => ({
                                          value: String(u.id), label: u.full_name }))} />
                                <span className="field-hint">Required. One person deciding alone is the gap every stock loss goes through.</span>
                              </label>
                            )}
                            <label className="field span-2">
                              Reason
                              <input value={move.reason}
                                     onChange={(e) => setMove({ ...move, reason: e.target.value })} />
                            </label>
                          </div>
                          <BusyButton className="btn small" onClick={() => record(r)}>
                            Record movement
                          </BusyButton>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
