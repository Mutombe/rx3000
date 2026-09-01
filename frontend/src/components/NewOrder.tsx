/** Raise a purchase order by hand.
 *
 *  Procurement could generate orders from reorder levels and could receive
 *  them, and could not raise one. That covers the routine and misses every
 *  reason a pharmacy actually telephones a wholesaler: a patient has asked for
 *  something not stocked, a line ran out between sweeps, a rep quoted a price
 *  worth taking today. The endpoint has been there since orders were written
 *  and no screen called it, so the answer was to raise it on paper and type it
 *  in when it arrived, which is how stock on the shelf comes to have no order
 *  behind it.
 *
 *  The cost defaults to what the product last cost and stays editable, because
 *  the reason for raising an order by hand is often that the price has moved.
 */
import { useEffect, useMemo, useState } from "react";
import { Plus, Trash } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "./BusyButton";
import LookupInput, { LookupItem } from "./LookupInput";
import Select from "./Select";
import { useToast } from "./Toast";

interface Supplier { id: number; name: string }
interface Line {
  product_id: number; name: string; quantity: string; cost: string;
  on_hand: number; reorder_level: number;
}

export default function NewOrder({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  /* The lookup hands back a value, not the record. The products behind the
     last search are kept so the pick can carry its cost, its stock and its
     supplier onto the line — refetching one product to read three fields it
     has just displayed is a round trip for nothing. */
  const [found, setFound] = useState<Record<string, any>>({});
  const toast = useToast();

  useEffect(() => {
    api.get<Supplier[]>("/api/suppliers")
      .then((rows) => {
        setSuppliers(rows);
        // One supplier is not a choice, so it is not presented as one.
        if (rows.length === 1) setSupplierId(String(rows[0].id));
      })
      .catch(() => setSuppliers([]));
  }, []);

  const total = useMemo(
    () => lines.reduce((n, l) => n + (Number(l.quantity) || 0) * (Number(l.cost) || 0), 0),
    [lines]);

  const ready = supplierId !== ""
    && lines.length > 0
    && lines.every((l) => (Number(l.quantity) || 0) > 0);

  function add(product: any) {
    if (lines.some((l) => l.product_id === product.id)) {
      toast.warn(`${product.name} is already on this order.`);
      return;
    }
    setLines((rows) => [...rows, {
      product_id: product.id,
      name: `${product.name} ${product.strength ?? ""}`.trim(),
      // A sensible order is the gap to the reorder quantity, not one of
      // everything — typing the number is the part people get wrong in a hurry.
      quantity: String(Math.max(product.reorder_quantity || 0,
                                (product.reorder_level || 0) - (product.quantity_on_hand || 0),
                                1)),
      cost: String(product.cost_price ?? 0),
      on_hand: product.quantity_on_hand ?? 0,
      reorder_level: product.reorder_level ?? 0,
    }]);
    // If the product knows its supplier and none is chosen yet, take it.
    if (!supplierId && product.supplier_id) setSupplierId(String(product.supplier_id));
  }

  function set(i: number, patch: Partial<Line>) {
    setLines((rows) => rows.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  }

  async function raise() {
    try {
      const order = await api.post<{ order_number: string }>("/api/orders", {
        supplier_id: Number(supplierId),
        notes: notes.trim(),
        items: lines.map((l) => ({
          product_id: l.product_id,
          quantity_ordered: Number(l.quantity) || 0,
          unit_cost: Number(l.cost) || 0,
        })),
      });
      toast.ok(`${order.order_number} raised. Send it when you are ready.`);
      onCreated();
      onClose();
    } catch (e) {
      toast.error(errorText(e, "That order could not be raised."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-full" onClick={(e) => e.stopPropagation()}>
        <h2>New purchase order</h2>
        <p className="muted">
          For what the reorder sweep does not catch: a medicine a patient has
          asked for, a line that ran out today, a price a rep has quoted.
        </p>

        <div className="form-row">
          <div className="field span-5">
            <label>Supplier</label>
            <Select value={supplierId} onChange={setSupplierId}
                    ariaLabel="Supplier"
                    options={[{ value: "", label: "Which wholesaler?" },
                              ...suppliers.map((s) => ({
                                value: String(s.id), label: s.name }))]} />
          </div>
          <div className="field span-7">
            <label>Note <span className="muted">optional</span></label>
            <input value={notes} onChange={(e) => setNotes(e.target.value)}
                   placeholder="For Mrs Ncube — collecting Friday" />
          </div>
        </div>

        <div className="field">
          <label>Add a medicine</label>
          <LookupInput
            value=""
            placeholder="Search the catalogue"
            emptyLabel="Nothing in the catalogue matches that."
            search={async (q): Promise<LookupItem[]> => {
              const rows = await api.get<any[]>(
                `/api/products?q=${encodeURIComponent(q)}&limit=8`);
              setFound(Object.fromEntries(rows.map((r) => [String(r.id), r])));
              return rows.map((r) => ({
                value: String(r.id),
                label: `${r.name} ${r.strength ?? ""}`.trim(),
                hint: `${r.quantity_on_hand} on hand`
                      + (r.cost_price ? ` · last cost ${money(r.cost_price)}` : ""),
              }));
            }}
            onChange={(value) => { const pr = found[value]; if (pr) add(pr); }}
          />
        </div>

        {lines.length === 0 ? (
          <div className="empty">
            <b>Nothing on this order yet</b>
            <p>Search above for what needs ordering.</p>
          </div>
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <th>Medicine</th>
                <th className="num">On hand</th>
                <th className="num">Order</th>
                <th className="num">Unit cost</th>
                <th className="num">Line</th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={l.product_id}>
                  <td>{l.name}</td>
                  <td className="num">
                    {l.on_hand}
                    {l.on_hand <= l.reorder_level && (
                      <div className="muted small">at or below reorder</div>
                    )}
                  </td>
                  <td className="num">
                    <input type="number" min="1" step="1" className="tender-amount"
                           value={l.quantity}
                           onChange={(e) => set(i, { quantity: e.target.value })} />
                  </td>
                  <td className="num">
                    <input type="number" min="0" step="0.01" className="tender-amount"
                           value={l.cost}
                           onChange={(e) => set(i, { cost: e.target.value })} />
                  </td>
                  <td className="num">
                    {money((Number(l.quantity) || 0) * (Number(l.cost) || 0))}
                  </td>
                  <td className="actions">
                    <button className="btn small ghost" title="Take it off"
                            onClick={() => setLines((rows) =>
                              rows.filter((_, n) => n !== i))}>
                      <Trash size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={4}><b>Order value</b></td>
                <td className="num"><b>{money(total)}</b></td>
                <td />
              </tr>
            </tfoot>
          </table>
        )}

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={raise} disabled={!ready}
                      icon={Plus} busyLabel="Raising…">
            Raise the order
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
