/** The workstation's scanner, in the top bar beside the branch it belongs to.
 *
 *  It sits where it does because that row already answers "where am I and as
 *  whom" — the shop, the theme, the account. What this machine can scan with
 *  is the same kind of fact, and it is true of the whole session rather than
 *  of whatever page happens to be open.
 *
 *  THREE STATES, AND THEY HAD TO BE TELLABLE APART AT A GLANCE
 *
 *  Idle is a quiet outline icon and nothing else: a pharmacy that has a USB
 *  scanner plugged in never needs this and should not be nagged by it.
 *
 *  Waiting shows the code, because that is a thing somebody is actively doing
 *  and has walked to the counter for.
 *
 *  Live is the one that mattered. It used to be a green pill reading "Phone
 *  scanning for Dispensing  Stop", which is eleven words and about a fifth of
 *  the toolbar, permanently, for a fact nobody needs restated. It is now the
 *  icon filled, in the accent colour, with a slow pulse — the universal "this
 *  is on" of every device in a pharmacy — and the words live in the popover
 *  and the tooltip, one tap away.
 */
import { useEffect, useRef, useState } from "react";
import { DeviceMobileCamera, X } from "@phosphor-icons/react";

import { qrSvg } from "../qr";

import { useScannerHub } from "./ScannerHub";

/** Where a member of staff is told to point their phone.
 *
 *  Said as the product's own address rather than read off `location.host`,
 *  which in production is the deployment's hostname — a string nobody in a
 *  pharmacy recognises, would not think to type, and would mistype if they
 *  did. This is the one instruction the product gives out loud to somebody
 *  holding a phone, so it is the product's name.
 *
 *  The address serves the scanner itself, not a redirect, so what loads is a
 *  viewfinder and not the whole application.
 *
 *  THE TRAILING SLASH IS LOAD BEARING, FOR NOW
 *
 *  The static site answers any path it does not recognise with a 301 to
 *  /index.html, and "/scanner" without the slash is one of those: it lands on
 *  the marketing home page, which is exactly what a member of staff does not
 *  want at a counter. "/scanner/" resolves to the directory's own index and
 *  works. The slash comes off the day a redirect rule from /scanner to
 *  /scanner/ is added ahead of that catch-all, which lives in the hosting
 *  dashboard rather than in this repository.
 *
 *  MEASURED, 24 Sept 2026, because it was reported as a phone problem.
 *
 *  It is not one. Both addresses behave identically on a desktop and on a
 *  phone; what differs is that a desktop browser has the address in history
 *  WITH the slash and completes it, while somebody typing it fresh on a
 *  handset does not. So the failure follows whoever is typing, which on a
 *  counter is always the phone.
 *
 *  A file cannot fix it from here. landing/scanner.html was tried on the
 *  reasoning that the host resolves an extensionless address to the .html of
 *  the same name; it does not. With /scanner.html deployed and answering 200,
 *  /scanner still redirected to /index.html, because the catch-all is reached
 *  first. The file was removed rather than left pretending. The landing page
 *  now at least carries a link to the scanner, so somebody who lands there is
 *  one tap away instead of stuck.
 */
const SCANNER_ADDRESS = "rx5000.com/scanner/";

export default function ScannerChip() {
  const hub = useScannerHub();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  // Opened by the act of asking for a code, so nobody presses the button and
  // wonders where the code went.
  const wasAsking = useRef(false);
  useEffect(() => {
    if (hub?.link && !wasAsking.current) setOpen(true);
    wasAsking.current = Boolean(hub?.link);
  }, [hub?.link]);

  useEffect(() => {
    if (!open) return;
    function away(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    function esc(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  if (!hub) return null;

  const { link, live, asking, target, offer, stop } = hub;
  const pending = Boolean(link && !live);
  const symbol = pending && link?.code ? qrSvg(link.code) : "";

  const label = live
    ? `A phone is scanning into ${target || "this workstation"}. Click to stop it.`
    : pending
      ? "Waiting for a phone to scan the code"
      : "Use a phone as a scanner for this workstation";

  return (
    <div className="sc-chip" ref={box}>
      <button
        type="button"
        className={"sc-chip-btn"
          + (live ? " is-live" : "")
          + (pending ? " is-waiting" : "")}
        aria-label={label}
        title={label}
        aria-expanded={open}
        aria-haspopup="dialog"
        disabled={asking}
        onClick={() => {
          if (!link && !asking) { void offer(); return; }
          setOpen((o) => !o);
        }}
      >
        <DeviceMobileCamera size={17} weight={live || pending ? "fill" : "regular"} />
        {/* The pulse is the whole signal at a glance. Stopped for anybody who
            has asked their system not to animate things. */}
        {live && <span className="sc-pulse" aria-hidden="true" />}
        {pending && <span className="sc-wait" aria-hidden="true" />}
      </button>

      {open && link && (
        <div className="sc-pop" role="dialog" aria-label="Phone scanner">
          <div className="sc-pop-head">
            <b>{live ? "Phone scanning" : "Pair a phone"}</b>
            <button type="button" className="sc-pop-x" onClick={() => setOpen(false)}
                    aria-label="Close">
              <X size={15} />
            </button>
          </div>

          {live ? (
            <>
              <p className="muted small">
                Scans land in <b>{target || "whatever is open"}</b>. Move to
                another screen and they follow, the same as the scanner plugged
                into this machine.
              </p>
              <button type="button" className="btn secondary sc-pop-go"
                      onClick={() => { void stop(); setOpen(false); }}>
                Stop using the phone
              </button>
            </>
          ) : (
            <>
              <p className="muted small">
                On the phone open <b>{SCANNER_ADDRESS}</b> and point it at
                this code.
              </p>
              <div className="sc-pop-symbol"
                   aria-label={`Pairing code ${link.code}`}
                   dangerouslySetInnerHTML={{ __html: symbol }} />
              <p className="sc-pop-code">{link.code}</p>
              <p className="muted small sc-pop-or">or type it on the phone</p>
              <button type="button" className="btn ghost sc-pop-go"
                      onClick={() => { void stop(); setOpen(false); }}>
                Cancel
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
