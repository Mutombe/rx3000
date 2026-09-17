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
 *
 *  FINDING THE SCRIPT USED TO BE THE DANGEROUS PART.
 *
 *  This asked for an exact Rx number, sent it as `?q=`, and took the first
 *  result. `/api/prescriptions` never declared `q`, so the search was dropped
 *  and the endpoint returned the most recent script in the pharmacy — which
 *  looks identical to a successful lookup. Whatever number was typed, the
 *  screen opened whatever had been captured last, and a correction made there
 *  was applied to the wrong prescription with a reason and a name attached, so
 *  it read afterwards as a deliberate edit nobody had meant to make.
 *
 *  It now searches as you type, the way the medicine field does, and shows the
 *  scripts captured most recently the moment it opens — because the script
 *  being corrected is nearly always one somebody has just keyed in and noticed
 *  a mistake on. You pick a row you can read rather than typing a number you
 *  have to be right about.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarBlank, MagnifyingGlass, Warning } from "@phosphor-icons/react";

import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import { CANCELLED, useStepUp } from "./StepUp";
import { useToast } from "./Toast";

interface Line {
  id: number; product_id: number; quantity: number;
  dosage_instructions: string; icd10_code: string; supply_days: number;
  product?: { name: string; strength?: string } | null;
  dispensings?: unknown[];
}

/** A row of the picker: enough to recognise the script without opening it. */
interface Found {
  id: number;
  rx_number: string;
  draft_ref: string;
  patient: string;
  doctor: string;
  items: number;
  dispensed_count: number;
  alterations: number;
  state: string;
  created_at: string;
}

function when(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

export default function AlterScript({ onClose, onAltered }: {
  onClose: () => void;
  onAltered?: () => void;
}) {
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<Found[]>([]);
  const [looking, setLooking] = useState(false);
  const [cursor, setCursor] = useState(0);

  const [rx, setRx] = useState<any>(null);
  const [opening, setOpening] = useState(false);
  const [itemId, setItemId] = useState<number | 0>(0);
  const [quantity, setQuantity] = useState("");
  const [dosage, setDosage] = useState("");
  const [supplyDays, setSupplyDays] = useState("");
  const [reason, setReason] = useState("");

  const { guarded, prompt } = useStepUp();
  const toast = useToast();
  const searchRef = useRef<HTMLInputElement>(null);

  const line: Line | undefined = rx?.items?.find((i: Line) => i.id === itemId);

  /** The list, live. Empty search means the scripts captured most recently,
   *  which is what somebody coming here to fix a typo is looking for. */
  const load = useCallback(async (q: string) => {
    setLooking(true);
    try {
      const said = await api.get<{ items: Found[] }>(
        `/api/prescriptions/table?per_page=8${q ? `&q=${encodeURIComponent(q)}` : ""}`);
      setHits(said.items ?? []);
      setCursor(0);
    } catch {
      // A picker that cannot load must not trap anybody in the dialog: the
      // list is simply empty and the search can be tried again.
      setHits([]);
    } finally {
      setLooking(false);
    }
  }, []);

  useEffect(() => { void load(""); searchRef.current?.focus(); }, [load]);

  // Debounced, at the same rhythm as the medicine search, so a number typed at
  // speed is one request rather than nine.
  useEffect(() => {
    const t = window.setTimeout(() => { void load(term.trim()); }, 220);
    return () => window.clearTimeout(t);
  }, [term, load]);

  // Whatever the line holds now, so a correction starts from the current value
  // rather than from empty — retyping a quantity that was already right is how
  // a second mistake gets made while fixing the first.
  useEffect(() => {
    if (!line) return;
    setQuantity(String(line.quantity ?? ""));
    setDosage(line.dosage_instructions ?? "");
    setSupplyDays(String(line.supply_days ?? ""));
  }, [itemId]);

  async function open(found: Found) {
    setOpening(true);
    try {
      const full = await api.get<any>(`/api/prescriptions/${found.id}`);
      setRx(full);
      setItemId(0);
      setReason("");
    } catch (e) {
      toast.error(errorText(e, "That script could not be opened."));
    } finally {
      setOpening(false);
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

  const lines: Line[] = (rx?.items ?? []).map((i: Line) => ({
    ...i, dispensings: i.dispensings ?? [],
  }));
  const ready = !!itemId && reason.trim().length >= 3;

  /** Arrow keys move through the list and Enter opens, so a script can be found
   *  and opened without the hand leaving the keyboard — the same way the
   *  medicine lane works. */
  function onSearchKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, hits.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    if (e.key === "Enter" && hits[cursor]) { e.preventDefault(); void open(hits[cursor]); }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide alt-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Alter a script</h2>
        <p className="muted">
          Corrects a captured script without voiding it, so it keeps its Rx
          number and its place in the register. Anything already dispensed
          cannot be changed. That line records something that physically
          happened.
        </p>

        <div className="alt-split">
          {/* FIND IT. Live, and showing the most recent before a key is
              pressed, because the script being corrected is usually the one
              just captured. */}
          <div className="alt-find">
            <div className="alt-search">
              <MagnifyingGlass size={16} />
              <input ref={searchRef} type="search" value={term}
                     onChange={(e) => setTerm(e.target.value)}
                     onKeyDown={onSearchKey}
                     aria-label="Search scripts by number, patient, ID or prescriber"
                     placeholder="Number, patient, ID or prescriber" />
            </div>
            <div className="alt-list-head">
              {term.trim() ? `Matching “${term.trim()}”` : "Captured most recently"}
              {looking && <span className="muted"> · looking</span>}
            </div>
            <ul className="alt-list">
              {hits.map((h, i) => (
                <li key={h.id}>
                  <button type="button"
                          className={`alt-hit${rx?.id === h.id ? " is-open" : ""}`
                            + `${i === cursor ? " is-cursor" : ""}`}
                          onMouseEnter={() => setCursor(i)}
                          onClick={() => void open(h)}>
                    <span className="alt-hit-top">
                      <b>{h.rx_number || h.draft_ref || `#${h.id}`}</b>
                      <span className={`badge ${h.state === "ONHOLD" ? "danger"
                        : h.state === "COLLECTED" ? "muted" : "warn"}`}>{h.state}</span>
                    </span>
                    <span className="alt-hit-who">{h.patient || "no patient on file"}</span>
                    <span className="alt-hit-meta">
                      <CalendarBlank size={12} /> {when(h.created_at)}
                      {" · "}{h.items} line{h.items === 1 ? "" : "s"}
                      {h.dispensed_count > 0 && `, ${h.dispensed_count} dispensed`}
                      {h.alterations > 0 && (
                        <span className="alt-hit-altered"> · altered {h.alterations}×</span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {!looking && hits.length === 0 && (
              <div className="empty alt-empty">
                <b>Nothing matches that</b>
                <p>Search by the Rx number, the patient, their ID or the prescriber.</p>
              </div>
            )}
          </div>

          {/* CORRECT IT. Nothing here until a script is chosen, so the form is
              never a set of boxes with no subject. */}
          <div className="alt-work">
            {!rx ? (
              <div className="empty alt-empty">
                <b>Choose a script on the left</b>
                <p>
                  Its lines appear here. The ones already dispensed are shown
                  and cannot be corrected.
                </p>
              </div>
            ) : (
              <>
                <div className="alt-chosen">
                  <b>{rx.rx_number || rx.draft_ref}</b>
                  <span className="muted">
                    {rx.patient ? ` · ${rx.patient.first_name} ${rx.patient.last_name}` : ""}
                  </span>
                </div>

                {/* The lines as rows rather than a dropdown. A dropdown hides
                    which of them can be corrected behind a click, and that is
                    the one thing worth seeing before choosing. */}
                <div className="alt-lines" role="radiogroup" aria-label="Which line to correct">
                  {lines.map((i) => {
                    const gone = (i.dispensings?.length ?? 0) > 0;
                    return (
                      <button type="button" key={i.id}
                              role="radio" aria-checked={itemId === i.id}
                              disabled={gone || opening}
                              className={`alt-line${itemId === i.id ? " is-picked" : ""}`
                                + `${gone ? " is-gone" : ""}`}
                              title={gone ? "Already dispensed, so it cannot be altered" : undefined}
                              onClick={() => setItemId(i.id)}>
                        <span className="alt-line-name">
                          {i.product?.name ?? `#${i.product_id}`}
                          {i.product?.strength ? ` ${i.product.strength}` : ""}
                        </span>
                        <span className="alt-line-qty">×{i.quantity}</span>
                        {gone && <span className="badge muted">dispensed</span>}
                      </button>
                    );
                  })}
                  {lines.length === 0 && (
                    <p className="muted small">This script has no lines on it.</p>
                  )}
                  {lines.length > 0 && lines.every((i) => (i.dispensings?.length ?? 0) > 0) && (
                    <p className="alt-all-gone">
                      <Warning size={13} weight="fill" /> Every line on this script has
                      been dispensed, so none of it can be altered.
                    </p>
                  )}
                </div>

                {line && (
                  <>
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
              </>
            )}
          </div>
        </div>

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
