/** Write down a promise made at the counter.
 *
 *  Most to-follows are raised by a dispensing that came up short, and that is
 *  the common case and already handled. This is the other one, and it is just
 *  as common: somebody asks for something the shelf does not have, is told it
 *  will be in on Friday, and walks out. Until now that promise lived on
 *  whatever the pharmacy writes it on, which is the paper list this whole
 *  feature exists to replace, so the one way into it that a person actually
 *  uses was the one that was missing.
 *
 *  The date is the point of the record. "We owe her some Ventolin" is a note;
 *  "we told her Friday" is a promise somebody can be held to, and the only
 *  version of it worth keeping.
 */
import { useEffect, useState } from "react";
import { api, errorText, money } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

export default function NewToFollow({ onClose, onPromised }: {
  onClose: () => void;
  onPromised?: () => void;
}) {
  const [productQ, setProductQ] = useState("");
  const [productHits, setProductHits] = useState<any[]>([]);
  const [product, setProduct] = useState<any>(null);
  const [patientQ, setPatientQ] = useState("");
  const [patientHits, setPatientHits] = useState<any[]>([]);
  const [patient, setPatient] = useState<any>(null);
  const [quantity, setQuantity] = useState("1");
  const [promisedFor, setPromisedFor] = useState("");
  const [notes, setNotes] = useState("");
  const toast = useToast();

  useEffect(() => {
    if (productQ.trim().length < 2) { setProductHits([]); return; }
    const t = setTimeout(() => {
      api.get<any>(`/api/products?q=${encodeURIComponent(productQ.trim())}&limit=6`)
        .then((d) => setProductHits(d.items ?? d ?? [])).catch(() => setProductHits([]));
    }, 200);
    return () => clearTimeout(t);
  }, [productQ]);

  useEffect(() => {
    if (patientQ.trim().length < 2) { setPatientHits([]); return; }
    const t = setTimeout(() => {
      api.get<any>(`/api/patients?q=${encodeURIComponent(patientQ.trim())}&limit=6`)
        .then((d) => setPatientHits(d.items ?? d ?? [])).catch(() => setPatientHits([]));
    }, 200);
    return () => clearTimeout(t);
  }, [patientQ]);

  async function save() {
    if (!product) return;
    try {
      await api.post("/api/to-follows", {
        product_id: product.id,
        quantity: Number(quantity) || 1,
        patient_id: patient?.id ?? null,
        promised_for: promisedFor || null,
        notes: notes.trim(),
      });
      toast.ok(`${product.name} owed to ${patient
        ? `${patient.first_name} ${patient.last_name}` : "a customer"}.`);
      onPromised?.();
      onClose();
    } catch (e) {
      toast.error(errorText(e, "That promise could not be recorded."));
    }
  }

  const ready = !!product && (Number(quantity) || 0) > 0;
  const short = product
    && (product.quantity_on_hand ?? 0) < (Number(quantity) || 0);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Owe something to a customer</h2>
        <p className="muted">
          For what was asked for and could not be handed over. This is the list
          somebody works through when the delivery lands.
        </p>

        <div className="field">
          <label>What is owed</label>
          {product ? (
            <div className="product-pick">
              <span>
                <b>{product.name}</b> {product.strength}
                <span className="muted"> · {product.quantity_on_hand ?? 0} on the shelf</span>
              </span>
              <button type="button" className="btn ghost small"
                      onClick={() => setProduct(null)}>Change</button>
            </div>
          ) : (
            <>
              <input type="search" autoFocus value={productQ}
                     onChange={(e) => setProductQ(e.target.value)}
                     placeholder="Search the catalogue…" />
              {productHits.map((p) => (
                <div key={p.id} className="product-pick"
                     onClick={() => { setProduct(p); setProductQ(""); setProductHits([]); }}>
                  <span>{p.name} {p.strength}</span>
                  <span className="muted">
                    {p.quantity_on_hand ?? 0} in stock · {money(p.unit_price ?? 0)}
                  </span>
                </div>
              ))}
            </>
          )}
        </div>

        <div className="form-row">
          <div className="field span-3">
            <label>How many</label>
            <input type="number" min={1} value={quantity}
                   onChange={(e) => setQuantity(e.target.value)} />
          </div>
          <div className="field span-4">
            <label>Promised for</label>
            <input type="date" value={promisedFor}
                   onChange={(e) => setPromisedFor(e.target.value)} />
            <span className="field-hint">
              {promisedFor
                ? "What the customer was told."
                : "“We owe her some” is a note; “we told her Friday” is a promise."}
            </span>
          </div>
          <div className="field span-5">
            <label>Who for <span className="muted">(optional)</span></label>
            {patient ? (
              <div className="product-pick">
                <span>{patient.first_name} {patient.last_name}</span>
                <button type="button" className="btn ghost small"
                        onClick={() => setPatient(null)}>Change</button>
              </div>
            ) : (
              <>
                <input type="search" value={patientQ}
                       onChange={(e) => setPatientQ(e.target.value)}
                       placeholder="Search patients…" />
                {patientHits.map((p) => (
                  <div key={p.id} className="product-pick"
                       onClick={() => { setPatient(p); setPatientQ(""); setPatientHits([]); }}>
                    <span>{p.last_name}, {p.first_name}</span>
                    <span className="muted">{p.phone}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* Recording a debt for something that is in fact on the shelf is
            almost always a mistake at the keyboard, so it is queried rather
            than refused — occasionally the stock figure is the thing that
            is wrong. */}
        {product && !short && (
          <div className="alert warn">
            There are {product.quantity_on_hand ?? 0} of these on the shelf, so
            this may not need to be owed at all — unless the figure is wrong.
          </div>
        )}

        <div className="field">
          <label>Note</label>
          <input value={notes} onChange={(e) => setNotes(e.target.value)}
                 placeholder="e.g. wants the 100s, will collect herself" />
        </div>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" disabled={!ready} onClick={save}
                      busyLabel="Recording…">
            Record it
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
