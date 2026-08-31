/** Sending a patient their portal link, on whichever thing they actually use.
 *
 *  The link used to be copied silently to the clipboard with a toast saying so,
 *  which asks the person at the counter to remember the patient's number, open
 *  WhatsApp, find the chat and paste — four steps, with a patient standing
 *  there, and the message they eventually send is a bare URL with no
 *  explanation that the patient does not open.
 *
 *  So the message is written here, the number is already in it, and the choice
 *  is one press: WhatsApp, SMS, email, or copy.
 *
 *  **The code is shown separately and copied separately, deliberately.** Sending
 *  a link and its code in one message means one forwarded message opens the
 *  record — which is the whole thing the code exists to prevent. The default
 *  message carries the link; the code is read out, or sent on something else.
 *  Both are here because a pharmacy will sometimes decide otherwise, and it is
 *  their decision to make with a patient in front of them.
 */
import { useState } from "react";
import { Copy, Envelope, Link as LinkIcon, WhatsappLogo, ChatText }
  from "@phosphor-icons/react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

export interface PortalLink {
  token: string; path: string; code: string;
  send_to: string; patient: string;
  expires_in_days: number; share_text: string; message: string;
}

export default function SharePortalLink(
  { link, pharmacy, patientId, onClose, onNewCode }:
  { link: PortalLink; pharmacy: string; patientId: number;
    onClose: () => void; onNewCode: (code: string) => void },
) {
  const [withCode, setWithCode] = useState(false);
  const toast = useToast();

  const url = `${window.location.origin}${link.path}`;
  const base = link.share_text
    .replace("{pharmacy}", pharmacy || "your pharmacy")
    .replace("{link}", url);
  // Two messages, and which one is sent is a decision the pharmacy makes with
  // the patient in front of them.
  const text = withCode ? base
    : base.split("\n\n")[0]
      + "\n\nWe will give you your four-digit code at the counter.";

  const digits = (link.send_to || "").replace(/[^\d]/g, "");
  // Zimbabwe: a local 07… number needs the country code for wa.me.
  const wa = digits.startsWith("0") ? `263${digits.slice(1)}` : digits;

  async function copy(what: string, said: string) {
    try {
      await navigator.clipboard.writeText(what);
      toast.ok(said);
    } catch {
      // Clipboard access is refused on an insecure origin and in some
      // embedded browsers. Said plainly rather than failing silently, because
      // the operator is about to tell a patient the link is on its way.
      toast.warn("This browser would not let us copy. Select the text and "
                 + "copy it by hand.");
    }
  }

  async function newCode() {
    try {
      const r = await api.post<{ code: string; message: string }>(
        `/api/portal-admin/links/patient/${patientId}/new-code`, {});
      onNewCode(r.code);
      toast.ok(r.message);
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Send {link.patient} their link</h2>
        <p className="muted">
          It opens their prescriptions, what is ready and what is due. Good for{" "}
          {link.expires_in_days} days.
        </p>

        {/* The code, large enough to read out over a counter or a telephone. */}
        <div className="share-code">
          <span className="muted small">Their four-digit code</span>
          <b>{link.code || "—"}</b>
          <div className="share-code-actions">
            <button className="btn ghost sm"
              onClick={() => copy(link.code, "Code copied.")}>
              <Copy size={13} /> Copy code
            </button>
            <button className="btn ghost sm" onClick={newCode}>
              New code
            </button>
          </div>
        </div>
        <p className="hint">
          A new code stops the old one working immediately — which is what you
          want when a patient has lost their phone.
        </p>

        <label className="check">
          <input type="checkbox" checked={withCode}
                 onChange={(e) => setWithCode(e.target.checked)} />
          <span>
            Put the code in the message too.{" "}
            <span className="muted">
              Off by default: a link and its code in one message means one
              forwarded message opens the record, which is the thing the code
              exists to prevent.
            </span>
          </span>
        </label>

        <label className="field">
          <span>The message</span>
          <textarea rows={4} value={text} readOnly className="share-text" />
        </label>

        <div className="share-choices">
          <a className="btn primary"
             href={`https://wa.me/${wa}?text=${encodeURIComponent(text)}`}
             target="_blank" rel="noreferrer">
            <WhatsappLogo size={16} weight="fill" /> WhatsApp
          </a>
          {/* `sms:` with a body works on both phone platforms and is ignored
              on a desktop, which is the right failure — the button is simply
              inert rather than opening something wrong. */}
          <a className="btn"
             href={`sms:${link.send_to}?&body=${encodeURIComponent(text)}`}>
            <ChatText size={16} weight="fill" /> SMS
          </a>
          <a className="btn"
             href={`mailto:?subject=${encodeURIComponent("Your pharmacy record")}`
                   + `&body=${encodeURIComponent(text)}`}>
            <Envelope size={16} weight="fill" /> Email
          </a>
          <button className="btn" onClick={() => copy(url, "Link copied.")}>
            <LinkIcon size={16} weight="bold" /> Copy link
          </button>
          <button className="btn" onClick={() => copy(text, "Message copied.")}>
            <Copy size={16} weight="bold" /> Copy message
          </button>
        </div>

        <p className="muted small">
          Sending to <b>{link.send_to || "no number on file"}</b>. Their own
          number, not a shared one — it opens their record.
        </p>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
