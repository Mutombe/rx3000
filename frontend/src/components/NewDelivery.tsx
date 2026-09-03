/** Raise a delivery by hand.
 *
 *  Deliveries reached this system only by arriving already made — something
 *  else raised the waybill and this screen dispatched it. But the request
 *  usually arrives by telephone: a patient who cannot come in, a relative
 *  asking for it to be sent, an account customer who always has it delivered.
 *  The endpoint for it has existed since deliveries were built and nothing
 *  called it, so the answer to "can you send it round" was to open the
 *  database.
 *
 *  Two things the server insists on, said here rather than discovered on
 *  submit: a delivery needs somebody to give it to, and somewhere to take it.
 *  A waybill with no address is a piece of paper.
 *
 *  Attaching the sale is optional but worth doing where there is one — it is
 *  what tells the driver whether the bag holds a controlled substance, which
 *  the server works out for itself and flags for an identity check at the
 *  door. A controlled item leaving the premises never reaches the counter
 *  where that check would normally happen.
 */
import { useEffect, useState } from "react";
import { closeThenSave } from "../hooks/useOptimisticList";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

interface Sale {
  id: number; sale_number: string; total: number; created_at: string;
  patient?: { id: number; first_name: string; last_name: string } | null;
}

export default function NewDelivery({ onClose, onRaised }: {
  onClose: () => void;
  onRaised?: () => void;
}) {
  const [patientQ, setPatientQ] = useState("");
  const [hits, setHits] = useState<any[]>([]);
  const [patient, setPatient] = useState<any>(null);
  const [sales, setSales] = useState<Sale[]>([]);
  const [saleId, setSaleId] = useState<number | 0>(0);
  const [recipient, setRecipient] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [instructions, setInstructions] = useState("");
  const toast = useToast();

  useEffect(() => {
    if (patientQ.trim().length < 2) { setHits([]); return; }
    const t = setTimeout(() => {
      api.get<any[]>(`/api/patients?q=${encodeURIComponent(patientQ.trim())}&limit=6`)
        .then((d: any) => setHits(d.items ?? d ?? [])).catch(() => setHits([]));
    }, 200);
    return () => clearTimeout(t);
  }, [patientQ]);

  /** Their recent sales, so a delivery can be tied to what is actually in the
   *  bag rather than raised against a name and a hope. */
  useEffect(() => {
    if (!patient) { setSales([]); setSaleId(0); return; }
    api.get<Sale[]>(`/api/patients/${patient.id}/sales`)
      .then((rows) => setSales(rows.slice(0, 8))).catch(() => setSales([]));
  }, [patient?.id]);

  function choose(p: any) {
    setPatient(p);
    setHits([]);
    setPatientQ("");
    // Filled from the record, and still editable: medicine goes to a hospital
    // ward or a workplace as often as it goes home.
    setRecipient(`${p.first_name} ${p.last_name}`.trim());
    setAddress(p.address || "");
    setPhone(p.phone || "");
  }

  async function raise() {
    try {
      const to = recipient.trim() || "this patient";
      await closeThenSave(onClose,
        () => api.post("/api/waybills", {
          sale_id: saleId || null,
          patient_id: patient?.id ?? null,
          recipient: recipient.trim(),
          address: address.trim(),
          phone: phone.trim(),
          instructions: instructions.trim(),
        }),
        { toast, ok: `Delivery raised for ${to}.`,
          failed: `No delivery was raised for ${to}. Nothing was saved, so `
                + `the medicine is still on the counter.`,
          after: () => onRaised?.() });
    } catch (e) {
      toast.error(errorText(e, "That delivery could not be raised."));
    }
  }

  const ready = recipient.trim() !== "" && address.trim() !== "";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Raise a delivery</h2>
        <p className="muted">
          For the request that arrives by telephone: somebody who cannot come
          in, a relative asking for it to be sent, an account customer who
          always has it delivered.
        </p>

        <div className="field">
          <label>Who is it for</label>
          {patient ? (
            <div className="product-pick">
              <span>
                <b>{patient.first_name} {patient.last_name}</b>
                {patient.phone && <span className="muted"> · {patient.phone}</span>}
              </span>
              <button type="button" className="btn ghost small"
                      onClick={() => { setPatient(null); setSales([]); setSaleId(0); }}>
                Change
              </button>
            </div>
          ) : (
            <>
              <input type="search" autoFocus value={patientQ}
                     onChange={(e) => setPatientQ(e.target.value)}
                     placeholder="Search the patient register…" />
              {hits.map((p) => (
                <div key={p.id} className="product-pick" onClick={() => choose(p)}>
                  <span>{p.last_name}, {p.first_name}</span>
                  <span className="muted">{p.address || "no address on file"}</span>
                </div>
              ))}
              <span className="field-hint">
                Or leave it and address the delivery by hand below — not every
                recipient is a patient on file.
              </span>
            </>
          )}
        </div>

        {/* What is in the bag. Optional, and worth doing: it is what tells the
            driver whether an identity check is needed at the door. */}
        {sales.length > 0 && (
          <div className="field">
            <label>Against which sale <span className="muted">(optional)</span></label>
            {sales.map((s) => (
              <div key={s.id}
                   className={`product-pick${saleId === s.id ? " is-on" : ""}`}
                   onClick={() => setSaleId(saleId === s.id ? 0 : s.id)}>
                <span className="mono">{s.sale_number}</span>
                <span className="muted">
                  {fmtDate(s.created_at)} · {money(s.total)}
                </span>
              </div>
            ))}
            <span className="field-hint">
              Attaching it lets the system see whether the bag holds a
              controlled substance, which needs an identity check at the door.
            </span>
          </div>
        )}

        <div className="form-row">
          <div className="field span-6">
            <label>Deliver to</label>
            <input value={recipient} onChange={(e) => setRecipient(e.target.value)}
                   placeholder="The name on the door" />
          </div>
          <div className="field span-6">
            <label>Telephone</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)}
                   placeholder="For the driver to ring ahead" />
          </div>
        </div>

        <div className="field">
          <label>Address</label>
          <input value={address} onChange={(e) => setAddress(e.target.value)}
                 placeholder="Where it is going" />
          {!address.trim() && (
            <span className="field-hint">
              A waybill with no address is a piece of paper.
            </span>
          )}
        </div>

        <div className="field">
          <label>Instructions for the driver</label>
          <input value={instructions} onChange={(e) => setInstructions(e.target.value)}
                 placeholder="e.g. gate code, ask for the sister on duty" />
        </div>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" disabled={!ready} onClick={raise}
                      busyLabel="Raising…">
            Raise the delivery
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
