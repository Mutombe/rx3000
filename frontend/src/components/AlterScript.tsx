/** Correct a captured script without voiding it and keying it in again.
 *
 *  A quantity typed as 30 when the prescriber wrote 60, a diagnosis left off a
 *  line that has to carry one to be claimed — these are ordinary, and the only
 *  route was to void the whole script and capture it from scratch, which loses
 *  the Rx number and the register entry with it.
 *
 *  The rule that makes this safe rather than a hole is the server's, and it is
 *  worth repeating on the screen: **what has already been dispensed cannot be
 *  altered.** A line that has left the shelf records something that physically
 *  happened; editing it would make the register disagree with the medicine. So
 *  only the undispensed part is offered, and every correction carries a reason
 *  and a name: a silent edit is indistinguishable from a mistake.
 */
import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import Select from "./Select";
import { CANCELLED, useStepUp } from "./StepUp";
import { useToast } from "./Toast";

interface Line {
  id: number; product_id: number; quantity: number;
  dosage_instructions: string; icd10_code: string; supply_days: number;
  product?: { name: string; strength?: string } | null;
  dispensings?: unknown[];
}

export default function AlterScript({ onClose, onAltered }: {
  onClose: () => void;
  onAltered?: () => void;
}) {
  const [rxNumber, setRxNumber] = useState("");
  const [rx, setRx] = useState<any>(null);
  const [itemId, setItemId] = useState<number | 0>(0);
  const [quantity, setQuantity] = useState("");
  const [dosage, setDosage] = useState("");
  const [supplyDays, setSupplyDays] = useState("");
  const [reason, setReason] = useState("");
  const [searching, setSearching] = useState(false);
  const { guarded, prompt } = useStepUp();
  const toast = useToast();

  const line: Line | undefined = rx?.items?.find((i: Line) => i.id === itemId);

  // Whatever the line holds now, so a correction starts from the current value
  // rather than from empty — retyping a quantity that was already right is how
  // a second mistake gets made while fixing the first.
  useEffect(() => {
    if (!line) return;
    setQuantity(String(line.quantity ?? ""));
    setDosage(line.dosage_instructions ?? "");
    setSupplyDays(String(line.supply_days ?? ""));
  }, [itemId]);

  async function find() {
    const term = rxNumber.trim();
    if (!term) return;
    setSearching(true);
    try {
      const hits = await api.get<any[]>(
        `/api/prescriptions?q=${encodeURIComponent(term)}&limit=1`);
      const found = Array.isArray(hits) ? hits[0] : null;
      if (!found) {
        toast.warn(`No script matches ${term}.`);
        setRx(null);
        return;
      }
      const full = await api.get<any>(`/api/prescriptions/${found.id}`);
      setRx(full);
      setItemId(0);
    } catch (e) {
      toast.error(errorText(e, "That script could not be opened."));
    } finally {
      setSearching(false);
    }
  }

  async function save() {
    if (!rx || !itemId) return;
    try {
      const result = await guarded(
        "script.alter",
        (token) => api.post(`/api/prescriptions/${rx.id}/alter`, {
          item_id: itemId,
          quantity: quantity === "" ? null : Number(quantity),
          dosage_instructions: dosage || null,
          supply_days: supplyDays === "" ? null : Number(supplyDays),
          reason: reason.trim(),
        }, token),
        `Alter ${rx.rx_number}`,
      );
      if (result === CANCELLED) return;
      toast.ok(`${rx.rx_number} corrected.`);
      onAltered?.();
      onClose();
    } catch (e) {
      toast.error(errorText(e, "That correction could not be made."));
    }
  }

  // The server refuses a dispensed line; saying so here means nobody types a
  // correction they are not allowed to make and only finds out on submit.
  const lines: Line[] = (rx?.items ?? []).map((i: Line) => ({
    ...i,
    dispensings: i.dispensings ?? [],
  }));
  const ready = !!itemId && reason.trim().length >= 3;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Alter a script</h2>
        <p className="muted">
          Corrects a captured script without voiding it, so it keeps its Rx
          number and its place in the register. Anything already dispensed
          cannot be changed — that line records something that physically
          happened.
        </p>

        <div className="form-row">
          <div className="field span-8">
            <label>Script number</label>
            <input value={rxNumber} autoFocus
                   onChange={(e) => setRxNumber(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") find(); }}
                   placeholder="e.g. RX-00412" />
          </div>
          <div className="field span-4" style={{ alignSelf: "end" }}>
            <BusyButton className="btn secondary" onClick={find}
                        disabled={!rxNumber.trim()} busyLabel="Looking…">
              Find it
            </BusyButton>
          </div>
        </div>

        {rx && (
          <>
            <div className="field">
              <label>Which line</label>
              <Select
                value={String(itemId || "")}
                onChange={(v) => setItemId(Number(v))}
                options={[{ value: "", label: "Choose the line to correct" },
                          ...lines.map((i) => ({
                            value: String(i.id),
                            label: `${i.product?.name ?? `#${i.product_id}`} ×${i.quantity}`,
                            hint: (i.dispensings?.length ?? 0) > 0
                              ? "already dispensed" : undefined,
                            disabled: (i.dispensings?.length ?? 0) > 0,
                          }))]}
              />
            </div>

            {line && (
              <div className="form-row">
                <div className="field span-3">
                  <label>Quantity</label>
                  <input type="number" min={1} value={quantity}
                         onChange={(e) => setQuantity(e.target.value)} />
                </div>
                <div className="field span-3">
                  <label>Supply days</label>
                  <input type="number" min={1} value={supplyDays}
                         onChange={(e) => setSupplyDays(e.target.value)} />
                </div>
                <div className="field span-6">
                  <label>Directions</label>
                  <input value={dosage} onChange={(e) => setDosage(e.target.value)} />
                </div>
              </div>
            )}

            <div className="field">
              <label>Why</label>
              <input value={reason} onChange={(e) => setReason(e.target.value)}
                     placeholder="e.g. prescriber wrote 60, captured as 30" />
              <span className="field-hint">
                Written into the script with your name. A silent edit is
                indistinguishable from a mistake.
              </span>
            </div>
          </>
        )}

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" disabled={!ready} onClick={save}
                      busyLabel="Correcting…">
            Correct it
          </BusyButton>
        </div>
        {prompt}
      </div>
    </div>
  );
}
