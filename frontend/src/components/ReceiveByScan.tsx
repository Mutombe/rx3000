/** Goods receipt, driven by the pack rather than by the order.
 *
 *  Booking a delivery in used to mean reading the order on screen and typing a
 *  batch number and an expiry date for every line. Both of those are printed on
 *  the pack in a DataMatrix, so the receiver was transcribing, by hand, at the
 *  end of a delivery, data a scanner reads perfectly. Transcription is where
 *  wrong expiry dates come from, and a wrong expiry date is a recall you cannot
 *  action and stock that expires on the shelf unnoticed.
 *
 *  So: scan the pack, and the product, batch and expiry are already filled in.
 *  What is left for a person is the one thing the pack cannot tell us — how
 *  many arrived — and even that is prefilled with what is outstanding on the
 *  order, because that is the answer most of the time.
 */
import { useCallback, useRef, useState } from "react";
import { api, errorText  } from "../api";
import { ScanBar, ScanResult } from "./Scanner";
import { useToast } from "./Toast";

interface Props {
  orderId: number;
  orderNumber: string;
  /** Refresh the order once something has been booked in. */
  onReceived: () => void;
}

interface Pending {
  productId: number;
  name: string;
  quantity: string;
  batch: string;
  expiry: string;
  unitCost: string;
  /** Whether the batch and expiry were read off the pack or typed. */
  fromPack: boolean;
  outstanding: number | null;
}

export default function ReceiveByScan({ orderId, orderNumber, onReceived }: Props) {
  const toast = useToast();
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const qtyRef = useRef<HTMLInputElement>(null);

  const onResolved = useCallback((r: ScanResult) => {
    if (!r.found || !r.product) return;   // ScanBar has already said so
    const line = r.order_line;
    setPending({
      productId: r.product.id,
      name: r.product.name,
      // What is left on the order is the likeliest answer. Scanning an outer
      // carton means a case, so the pack multiplier is the floor.
      quantity: String(
        line && line.outstanding > 0
          ? Math.max(line.outstanding, r.quantity_multiplier)
          : r.quantity_multiplier,
      ),
      batch: r.batch_number || "",
      expiry: r.expiry_date || "",
      unitCost: line?.unit_cost ? String(line.unit_cost) : "",
      fromPack: Boolean(r.batch_number || r.expiry_date),
      outstanding: line ? line.outstanding : null,
    });
    // The count is the only field a person still has to think about.
    window.setTimeout(() => qtyRef.current?.select(), 0);
  }, []);

  async function commit() {
    if (!pending) return;
    const quantity = Number(pending.quantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      toast.error("Enter how many units arrived.");
      qtyRef.current?.focus();
      return;
    }
    setBusy(true);
    try {
      const res = await api.post<{ message: string }>(`/api/scan/receive/${orderId}`, {
        product_id: pending.productId,
        quantity,
        batch_number: pending.batch.trim(),
        expiry_date: pending.expiry,
        unit_cost: pending.unitCost ? Number(pending.unitCost) : null,
      });
      toast.ok(res.message);
      setPending(null);
      onReceived();
    } catch (e: any) {
      toast.error(errorText(e, "That line could not be booked in."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h3>Receive by scanning</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Scan each pack as it comes off the delivery for {orderNumber}. Where the pack
        carries a GS1 code, the batch and expiry are read from it.
      </p>

      <ScanBar
        context="receive"
        orderId={orderId}
        onResolved={onResolved}
        placeholder="Scan the pack, or type a code…"
        // The dialog below owns the keyboard once something is waiting to be
        // confirmed; a second scan on top of it would lose the first.
        enabled={!pending}
        autoFocus
      />

      {pending && (
        <div className="scan-catch">
          <div className="scan-catch-head">
            <span className="scan-hit-name">{pending.name}</span>
            {pending.fromPack && <span className="badge ok">batch read from pack</span>}
            {pending.outstanding === 0 && <span className="badge warn">order already complete</span>}
            {pending.outstanding === null && <span className="badge warn">not on this order</span>}
          </div>

          <div className="scan-catch-grid">
            <label>
              <span>Units arrived</span>
              <input
                ref={qtyRef}
                type="number"
                min={1}
                value={pending.quantity}
                onChange={(e) => setPending({ ...pending, quantity: e.target.value })}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
              />
            </label>
            <label>
              <span>Batch</span>
              <input
                className="mono"
                value={pending.batch}
                onChange={(e) => setPending({ ...pending, batch: e.target.value, fromPack: false })}
                placeholder="from the pack"
              />
            </label>
            <label>
              <span>Expiry</span>
              <input
                type="date"
                value={pending.expiry}
                onChange={(e) => setPending({ ...pending, expiry: e.target.value, fromPack: false })}
              />
            </label>
            <label>
              <span>Unit cost</span>
              <input
                type="number"
                step="0.01"
                value={pending.unitCost}
                onChange={(e) => setPending({ ...pending, unitCost: e.target.value })}
                placeholder="unchanged"
              />
            </label>
          </div>

          <div className="scan-catch-actions">
            <button className="secondary small" onClick={() => setPending(null)} disabled={busy}>
              Discard
            </button>
            <button className="small" onClick={commit} disabled={busy}>
              {busy ? "Booking in…" : "Book in"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
