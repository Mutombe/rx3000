/** Borrowing a phone as this counter's scanner.
 *
 *  A pharmacy that has not bought a scanner for every station still has a
 *  camera in everybody's pocket. This is the counter's half: it shows a code,
 *  waits for a phone to take it, and then feeds whatever that phone reads into
 *  the same place a scanner plugged into this machine would have put it.
 *
 *  THE CODE IS A BARCODE
 *
 *  Because the phone is about to use its camera for everything else anyway, so
 *  the setup may as well be the first scan. This product already draws a Code
 *  128 for the script number on every label; that encoder draws this too. A QR
 *  would have meant a second encoder for no gain, and typing a code into a
 *  phone at a counter in front of a queue is the thing worth avoiding.
 *
 *  WHY THIS IS NOT A SECOND SCANNING PATH
 *
 *  `useWedgeScanner` already reduces a counter scanner and a camera to one
 *  event — a string arrived — and the screens above it never learn which. A
 *  phone on the other side of the room is a third way to produce that same
 *  event and nothing more, so it hands the string to the same `onScan` the
 *  wedge does. No screen has to know this exists.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api, apiBase, errorText } from "../api";
import { qrSvg } from "../qr";
import { useToast } from "./Toast";
import { readStored, writeStored } from "../storage";

/** The counter's own pairing, so a reload does not drop the phone. */
const HELD = "scanner_link";

interface Link { id: number; code: string; status: string; station: string;
                 device: string; expires_at: string }

export function usePairedScanner({
  station, onScan,
}: {
  /** What this counter calls itself, so the phone can say what it serves. */
  station: string;
  /** The same handler the wedge scanner uses. A scan is a scan. */
  onScan: (code: string) => void;
}) {
  const toast = useToast();
  const [link, setLink] = useState<Link | null>(null);
  const [live, setLive] = useState(false);
  const [asking, setAsking] = useState(false);
  // Held in a ref as well, so the stream's own closure always calls the
  // current handler rather than the one that existed when it opened.
  const handler = useRef(onScan);
  handler.current = onScan;

  /** Ask for a code to show. */
  const offer = useCallback(async () => {
    setAsking(true);
    try {
      const said = await api.post<Link>("/api/scanner/pair", { station });
      setLink(said);
      writeStored(HELD, String(said.id));
    } catch (e) {
      toast.error(errorText(e, "A pairing code could not be made."));
    } finally {
      setAsking(false);
    }
  }, [station, toast]);

  const stop = useCallback(async () => {
    const id = link?.id;
    setLink(null);
    setLive(false);
    writeStored(HELD, null);
    if (id) {
      try { await api.post(`/api/scanner/close/${id}`, {}); } catch { /* it is going anyway */ }
    }
  }, [link?.id]);

  // PICK THE PHONE BACK UP AFTER A RELOAD.
  //
  // The pairing's id was written to storage with a comment saying it was kept
  // "so a reload does not drop the phone", and then nothing ever read it back.
  // So refreshing the counter screen — or the dispensary tab being closed and
  // reopened, which happens all day — silently abandoned the pairing while the
  // phone carried on scanning into a stream nobody was listening to. Every
  // scan returned "Sent." and none of them arrived.
  //
  // The server is asked what is actually still live rather than trusting the
  // stored id, because the pairing may have been closed from the phone, timed
  // out, or been ended at another counter while this tab was shut.
  useEffect(() => {
    const held = readStored(HELD);
    if (!held) return;
    let dropped = false;
    api.get<{ links: Link[] }>("/api/scanner/links")
      .then(({ links }) => {
        if (dropped) return;
        const mine = links.find((l) => String(l.id) === held);
        if (mine) {
          setLink(mine);
          setLive(mine.status === "live");
        } else {
          // It is gone. Clear the note rather than leaving a dead id behind
          // to be resurrected on the next reload.
          writeStored(HELD, null);
        }
      })
      .catch(() => {
        // Deliberately silent: this is a best-effort resume on mount. The
        // counter works exactly as it always has without it, and the button
        // to pair again is right there.
      });
    return () => { dropped = true; };
  }, []);

  // The stream. Opened once a pairing exists and closed with it.
  //
  // `fetch` rather than `EventSource`, for the reason the assistant's own
  // streaming gives: EventSource cannot carry an Authorization header, and
  // moving the credential into the URL would put a bearer token into every
  // proxy log between here and the server.
  useEffect(() => {
    if (!link?.id) return;
    const stop = new AbortController();
    let shut = false;

    (async () => {
      try {
        const token = readStored("token");
        const r = await fetch(`${apiBase}/api/scanner/stream/${link.id}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: stop.signal,
        });
        if (!r.ok || !r.body) return;
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!shut) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let cut;
          // Frames are separated by a blank line. Anything short of one is
          // half a frame and waits for the rest, which is what makes this
          // safe against a chunk boundary landing mid-message.
          while ((cut = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, cut);
            buffer = buffer.slice(cut + 2);
            const kind = /^event: (.*)$/m.exec(frame)?.[1] ?? "";
            const data = /^data: (.*)$/m.exec(frame)?.[1] ?? "";
            // `open` means the stream is open, which is true while the code
            // is still sitting unclaimed on the screen. Only `paired` means a
            // phone has actually taken it.
            if (kind === "paired") setLive(true);
            if (kind === "closed") { setLive(false); setLink(null); }
            if (kind === "scan") {
              try {
                const said = JSON.parse(data) as { code: string };
                if (said.code) handler.current(said.code);
              } catch { /* a frame we cannot read is not worth a crash */ }
            }
          }
        }
      } catch { /* aborted, or the connection went; the screen says so */ }
    })();

    return () => { shut = true; stop.abort(); };
  }, [link?.id]);

  /** The code, drawn the way the phone will read it.
   *
   *  A QR, not the Code 128 this was built with. Six characters of Code 128
   *  is 121 modules; in a panel this wide that is a bar about two pixels
   *  across, photographed off a glossy monitor by a phone decoding at eight
   *  frames a second. It read sometimes. The same payload as a QR is 21x21,
   *  which is nearly twelve pixels a module in the same space, carries error
   *  correction, and does not care which way up the phone is held.
   */
  const symbol = link && link.status === "pending" && link.code
    ? qrSvg(link.code)
    : "";

  return { link, live, asking, offer, stop, symbol };
}

/** The control itself: a button until somebody wants it, then the code. */
export default function PairedScanner({
  station, onScan,
}: {
  station: string;
  onScan: (code: string) => void;
}) {
  const { link, live, asking, offer, stop, symbol } =
    usePairedScanner({ station, onScan });

  if (!link) {
    return (
      <button type="button" className="btn small secondary ps-open"
              onClick={() => void offer()} disabled={asking}>
        {asking ? "Asking…" : "Use a phone as a scanner"}
      </button>
    );
  }

  if (live) {
    return (
      <span className="ps-live">
        <span className="ps-dot" aria-hidden="true" />
        Phone scanning for {link.station || "this counter"}
        <button type="button" className="btn-link small" onClick={() => void stop()}>
          Stop
        </button>
      </span>
    );
  }

  return (
    <div className="ps-pair">
      <p className="muted small">
        On the phone, open <b>{location.host}/scanner</b> and point it at this
        code. It becomes a scanner for {link.station || "this counter"} until
        you stop it.
      </p>
      <div className="ps-symbol" aria-label={`Pairing code ${link.code}`}
           dangerouslySetInnerHTML={{ __html: symbol }} />
      {/* The characters, large enough to read across a counter. The phone can
          be given them by hand when the camera will not cooperate: a cracked
          lens, a dim shop, a screen with the sun on it. */}
      <p className="ps-code">{link.code}</p>
      <p className="muted small ps-or">
        or type it on the phone
      </p>
      <button type="button" className="btn small ghost" onClick={() => void stop()}>
        Cancel
      </button>
    </div>
  );
}
