/** Say one thing to a list of people you have just picked out.
 *
 *  WHY THIS IS NOT THE ADHERENCE SCREEN.
 *
 *  Patient Adherence composes to a segment: everybody on a scheme, everybody
 *  with a birthday this month. That is the right shape for a campaign and the
 *  wrong shape for the thing a pharmacy actually needs at four o'clock, which
 *  is "these eleven, the ones I have just been reading about". A segment
 *  cannot express eleven people a pharmacist recognised by eye.
 *
 *  So this takes whoever is ticked, and the ticking is done on the list where
 *  the recognising happens.
 *
 *  WHAT IT REFUSES TO PRETEND.
 *
 *  Somebody with no telephone number cannot be sent an SMS. They are counted
 *  before anything is sent and named after, because "11 sent" when four of
 *  them have no number is the kind of report that gets believed.
 */
import { useState } from "react";
import { PaperPlaneTilt, X } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

export interface Recipient { id: number; name: string; phone: string }

export default function MessageThese({
  people, noun = "patient", onClose, onSent,
}: {
  people: Recipient[];
  /** What these are, for the sentence above the box. */
  noun?: string;
  onClose: () => void;
  /** Called once anything was sent, so a selection can be cleared. */
  onSent?: (sent: number) => void;
}) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const toast = useToast();

  const reachable = people.filter((p) => p.phone?.trim());
  const without = people.length - reachable.length;

  async function send() {
    if (!body.trim()) {
      toast.warn("There is nothing to send yet.");
      return;
    }
    let sent = 0;
    const failed: string[] = [];
    for (const person of reachable) {
      try {
        await api.post("/api/messages", {
          patient_id: person.id,
          channel: "sms",
          subject: subject.trim() || "A message from your pharmacy",
          body: body.trim(),
        });
        sent += 1;
      } catch {
        failed.push(person.name);
      }
    }
    if (failed.length) {
      toast.warn(`${sent} sent. ${failed.length} did not go: `
                 + failed.slice(0, 3).join(", ")
                 + (failed.length > 3 ? ` and ${failed.length - 3} more.` : "."));
    } else {
      toast.ok(`${sent} message${sent === 1 ? "" : "s"} sent.`);
    }
    onSent?.(sent);
    onClose();
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="imp-head">
          <h2>
            Message {reachable.length} {noun}{reachable.length === 1 ? "" : "s"}
          </h2>
          <button className="btn ghost sm" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>

        <p className="muted">
          One SMS each, to the number on their profile. It goes out as it is
          written, so it is worth reading once more before sending.
        </p>
        {without > 0 && (
          <p className="muted">
            {without} of the {people.length} you picked have no number on file
            and are not included. They still have to be reached another way.
          </p>
        )}

        <label className="field">
          What it is about
          <input value={subject} maxLength={80}
                 placeholder="Kept with the message, not sent in the text"
                 onChange={(e) => setSubject(e.target.value)} />
        </label>
        <label className="field">
          The message
          <textarea rows={4} value={body} maxLength={480}
                    placeholder="Good day. The pharmacy will be closed on Monday the 5th."
                    onChange={(e) => setBody(e.target.value)} />
          <span className="field-hint">
            {body.length} of 480 characters. Nothing is added to it, so say who
            it is from.
          </span>
        </label>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Not now</button>
          <BusyButton className="btn primary" onClick={send}
                      disabled={!reachable.length || !body.trim()}
                      icon={PaperPlaneTilt} busyLabel="Sending…">
            Send {reachable.length}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
