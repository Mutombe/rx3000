/** Look at the labels before they go on the boxes.
 *
 *  The straight-through path after dispensing prints immediately — at a counter
 *  with a queue, a confirmation step is just a key to press. This screen is for
 *  the other case: a reprint, where somebody is deciding how many stickers they
 *  need and for which item, usually because the first attempt smudged or a
 *  repeat came in three boxes.
 *
 *  The preview is a preview, not a second implementation. `printLabels` owns the
 *  printed layout and the millimetre sizing; this only shows what it will
 *  produce. The first version of this file drew its own stickers, which meant
 *  two label designs that would drift apart at the first change — and it typed
 *  its own copy of the label fields, which is how it ended up reading a
 *  `pharmacist` field that does not exist while TypeScript stayed quiet.
 */
import { useEffect, useRef, useState } from "react";
import { api, errorText } from "../api";
import { labelPreviewDoc, printLabels } from "../print";
import { asText } from "../escpos";
import * as roll from "../shellPrinter";
import { canPrintLabels, labelLines, printLabelsOnAgent, probe } from "../deviceAgent";
import type { AgentStatus } from "../deviceAgent";
import type { Label } from "../types";
import { useToast } from "./Toast";
import IconButton from "./IconButton";

export default function LabelSheet({
  rxId, onClose,
}: { rxId: number; onClose: () => void }) {
  const toast = useToast();
  const [labels, setLabels] = useState<Label[] | null>(null);
  const [copies, setCopies] = useState(1);
  const [reason, setReason] = useState("");
  /** How many times these labels have already been printed. */
  const [before, setBefore] = useState(0);

  // The fetch depends on the script and nothing else. Holding the callbacks in a
  // ref rather than in the dependency list means a caller that passes an inline
  // arrow — the normal way to write this — cannot cause a refetch on every
  // render, which with a state update in the handler is an endless request loop.
  // What hardware this till has. Asked once when the dialog opens rather than
  // at print time, so the button can say where the labels are going before
  // somebody presses it.
  const [agent, setAgent] = useState<AgentStatus | null>(null);
  useEffect(() => { probe().then(setAgent).catch(() => setAgent(null)); }, []);

  // Which printers this machine has, and which one this till uses for labels.
  // A per-machine choice, not a per-pharmacy one: the roll is plugged in here
  // and called whatever Windows calls it here, so it is kept on the machine.
  const [printers, setPrinters] = useState<string[]>([]);
  const [picked, setPicked] = useState(roll.chosenPrinter());
  useEffect(() => { roll.listPrinters().then(setPrinters).catch(() => setPrinters([])); }, []);

  const cb = useRef({ onClose, toast });
  cb.current = { onClose, toast };

  useEffect(() => {
    let live = true;
    api.get<Label[]>(`/api/prescriptions/${rxId}/labels`)
      .then((l) => { if (live) setLabels(l); })
      .catch((e) => {
        if (!live) return;
        cb.current.toast.error(errorText(e, "Those labels could not be prepared."));
        cb.current.onClose();
      });
    // How often this script's labels have been run before. A second label for
    // a controlled substance is the easiest way to make one dispensing look
    // like two, so the count is put in front of whoever is about to print
    // another one rather than left in a log nobody opens.
    api.get<{ id: number }[]>(`/api/reprints?prescription_id=${rxId}&kind=label`)
      .then((rows) => { if (live) setBefore(rows.length); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [rxId]);

  if (!labels) {
    return (
      <div className="modal-backdrop" role="presentation">
        <div className="modal"><p className="muted">Preparing labels…</p></div>
      </div>
    );
  }

  if (labels.length === 0) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h2>Nothing to print</h2>
          <p className="muted">
            This script has no dispensed items, so there are no labels for it yet.
          </p>
          <div className="modal-actions">
            <button className="btn primary" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    );
  }

  const agentRoll = canPrintLabels(agent);
  const onRoll = roll.labelsGoStraightToRoll() || agentRoll;
  const rollName = roll.chosenPrinter()
    || agent?.printers?.label?.port || agent?.printers?.receipt?.port || "";

  /** The label roll if this till has one, the browser dialog otherwise.
   *
   *  A failed roll falls back to the dialog rather than losing the label: the
   *  medicine is already in the bag, and a sticker that did not print is a
   *  bag that cannot go out.
   */
  /** The lines this label becomes on a thermal roll. */
  function rollLines(l: Label) {
    return labelLines(l, roll.printerWidth());
  }

  /** Write down that this happened.
   *
   *  The endpoint has recorded reprints since it was written and nothing ever
   *  called it, so every label reprinted in this product so far is unrecorded.
   *  Deliberately not blocking: the medicine is in the bag and the sticker has
   *  to go on it, so a failure to record must never stop a label printing. It
   *  is reported, not swallowed, so a pharmacy is not told a compliance record
   *  exists when it does not.
   */
  async function record() {
    try {
      await api.post("/api/reprints", {
        kind: "label", prescription_id: rxId, reason: reason.trim(),
      });
    } catch {
      toast.warn("The label printed, but the reprint could not be recorded.");
    }
  }

  async function send() {
    // Guarded here rather than relying on where this sits in the file: the
    // dialog renders an empty state while the labels are still loading, and
    // the button is only reachable after they arrive.
    if (!labels || labels.length === 0) { onClose(); return; }
    // The shell first: it needs no separate service on the machine, which is
    // the difference between a pharmacy downloading one thing and two.
    if (roll.labelsGoStraightToRoll()) {
      try {
        for (const l of labels) await roll.printLines(rollLines(l), copies);
        await record();
        toast.ok(`${labels.length * copies} label(s) printed.`);
        onClose();
        return;
      } catch (e) {
        toast.error(errorText(e, "The label printer did not take it — using the print dialog."));
      }
    }
    if (agentRoll) {
      try {
        await printLabelsOnAgent(labels, copies, agent?.printers?.label?.width ?? 32);
        await record();
        toast.ok(`${labels.length * copies} label(s) sent to the roll.`);
        onClose();
        return;
      } catch (e) {
        toast.error(errorText(e, "The label roll did not answer — using the print dialog."));
      }
    }
    printLabels(labels, copies);
    await record();
    onClose();
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal lbl-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Reprint labels</h2>
        <p className="muted">
          {labels.length} item{labels.length === 1 ? "" : "s"} on {labels[0].rx_number}
          {" · "}{labels.length * copies} sticker
          {labels.length * copies === 1 ? "" : "s"} will print.
        </p>

        {before > 0 && (
          <div className="alert warn">
            These labels have been printed {before === 1 ? "once" : `${before} times`}{" "}
            before. Say why this one is needed — a second label is how one
            dispensing comes to look like two.
          </div>
        )}
        <label className="field">
          Why this reprint {before > 0 ? "" : "(optional)"}
          <input value={reason} onChange={(e) => setReason(e.target.value)}
                 placeholder="e.g. the first one smudged" />
        </label>

        {/* The printed markup, in an iframe, at the printed size.

            This drew its own stickers until now — a `.lbl-*` layout beside the
            `.label` one the printer gets. The file's own note at the top warned
            that two designs "would drift apart at the first change", and they
            did: the sticker on screen stopped matching the sticker on the roll,
            which somebody only found by printing one in a pharmacy.

            An iframe rather than an inline fragment because the print
            stylesheet sets rules on `body`, and those would otherwise leak into
            the application. Isolated, this is exactly the document the printer
            is handed. */}
        {/* Two printers, two documents, and the preview shows whichever is
            about to be used.

            A thermal roll cannot print the HTML sticker — it takes text with
            control codes. Showing the designed sticker and then printing lines
            of text is the same lie as before, in the other direction, so when
            the roll is the destination the preview is the text the roll gets,
            in a monospaced block at the roll's own width. */}
        {onRoll ? (
          <div className="lbl-preview">
            {labels.map((l, i) => (
              <pre key={i} className="lbl-roll">{asText(rollLines(l), roll.printerWidth())}</pre>
            ))}
          </div>
        ) : (
          <div className="lbl-preview">
            <iframe
              title="Label preview"
              className="lbl-frame"
              srcDoc={labelPreviewDoc(labels)}
              style={{ height: `${Math.min(labels.length, 6) * 48 + 8}mm` }}
            />
          </div>
        )}

        {/* Only where it can be acted on. A browser tab cannot print without
            a dialog whatever is chosen here, and offering the choice there
            would be a setting that quietly does nothing. */}
        {roll.canPrintDirect() && printers.length > 0 && (
          <label className="lbl-copies">
            Label printer
            <select
              value={picked}
              onChange={(e) => {
                setPicked(e.target.value);
                roll.choosePrinter(e.target.value, roll.printerWidth());
              }}
            >
              <option value="">Ask me each time (print dialog)</option>
              {printers.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>
        )}

        <label className="lbl-copies">
          Copies of each
          <input
            type="number" min={1} max={9} value={copies}
            onChange={(e) =>
              setCopies(Math.max(1, Math.min(9, Number(e.target.value) || 1)))}
          />
        </label>

        <div className="modal-actions">
          {/* Said before the button is pressed, not after. A dispenser who
              expects the label roll and gets a Windows dialog has already
              turned to the printer. */}
          <span className="muted small">
            {onRoll
              ? `To the label roll on this till${rollName ? ` (${rollName})` : ""}`
              : "No label roll on this till — the print dialog will ask"}
          </span>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <IconButton action="print" onClick={send} />
        </div>
      </div>
    </div>
  );
}
