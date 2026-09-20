/** A phone, borrowed as a barcode scanner for one counter.
 *
 *  A pharmacy that has not bought a scanner for every station still has a
 *  camera in everybody's pocket. This is that camera, pointed at a counter.
 *
 *  PUBLIC, AND DELIBERATELY SO
 *
 *  Nobody signs in here. The pairing code shown on the counter's screen IS the
 *  credential: single use, three minutes, and worth nothing once claimed. A
 *  member of staff who had to type their password into a phone at a counter,
 *  in front of a queue, would type it where somebody can watch — which is a
 *  worse trade than a code that expires in three minutes.
 *
 *  WHAT THIS SCREEN NEVER SHOWS
 *
 *  What it scanned. It sends a string and is told "sent". It does not learn
 *  the patient, the medicine or the script, and its token opens nothing else.
 *  That is the whole design: this phone can put a code onto one screen a
 *  pharmacist is looking at, and read nothing.
 *
 *  So the screen says how many it has sent and what the last one looked like,
 *  because a person needs to know a scan registered — and nothing else.
 *
 *  PAIRING IS ITSELF A SCAN
 *
 *  The counter draws its pairing code as a Code 128, because this product can
 *  already draw one and this page can already read one. Point the phone at the
 *  screen and it is paired. Nobody types anything, and the camera that is
 *  about to do the work is the thing that sets it up.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { apiBase, errorText } from "../api";
import { ScanCamera, cameraSupported } from "../components/Scanner";
import { readStored, writeStored } from "../storage";

/** This phone's own client.
 *
 *  Not the shared `api`, and not because of laziness. Every other caller in
 *  this application is a signed-in member of staff whose token the shared
 *  client attaches; this one is nobody, holding a pairing token that goes in
 *  a header of its own, calling three endpoints. Widening the shared client
 *  with a headers argument for a single unauthenticated page would put that
 *  argument in front of every other caller forever.
 */
async function ask<T>(path: string, body?: unknown, token?: string): Promise<T> {
  const r = await fetch(apiBase + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token ? { "X-Scanner": token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const said = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err: any = new Error(said?.detail?.message ?? said?.detail ?? "That did not work.");
    err.status = r.status;
    err.detail = said?.detail;
    throw err;
  }
  return said as T;
}

/** The pairing, kept so a phone that locks its screen comes back to work. */
const HELD = "scanner_pairing";

interface Pairing { token: string; station: string; id: number }

export default function PhoneScanner() {
  const [pairing, setPairing] = useState<Pairing | null>(() => {
    try {
      const raw = readStored(HELD);
      return raw ? (JSON.parse(raw) as Pairing) : null;
    } catch { return null; }
  });
  const [sent, setSent] = useState(0);
  const [last, setLast] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  /** Whether the viewfinder is up. `ScanCamera` is a full screen sheet with
   *  its own Done button, so closing it has to land somewhere rather than
   *  unpairing: an accidental tap should not cost somebody the pairing and a
   *  walk back to the counter. */
  const [scanning, setScanning] = useState(true);
  /** Codes already sent in this burst, so one pack held in front of the lens
   *  does not send forty times. The camera de-dupes over 1.8s; a person
   *  lingering over a box exceeds that. */
  const recent = useRef<Map<string, number>>(new Map());

  const forget = useCallback(() => {
    writeStored(HELD, null);
    setPairing(null);
    setSent(0);
    setLast("");
  }, []);

  // Check the pairing is still live when the page opens. A phone left in a
  // pocket overnight should say so rather than swallowing scans.
  useEffect(() => {
    if (!pairing) return;
    ask<{ status: string; station: string }>("/api/scanner/paired", undefined,
                                            pairing.token)
      .then((said) => {
        if (said.status !== "live") forget();
      })
      .catch(() => forget());
  }, [pairing?.token, forget]);

  async function claim(code: string) {
    setBusy(true);
    setProblem("");
    try {
      const said = await ask<{ token: string; station: string; id: number;
                               message: string }>(
        "/api/scanner/claim",
        { code, device: navigator.userAgent.slice(0, 80) });
      const held = { token: said.token, station: said.station, id: said.id };
      writeStored(HELD, JSON.stringify(held));
      setPairing(held);
      if (navigator.vibrate) navigator.vibrate([40, 60, 40]);
    } catch (e) {
      setProblem(errorText(e, "That code could not be used."));
    } finally {
      setBusy(false);
    }
  }

  async function send(code: string) {
    if (!pairing) return;
    const now = Date.now();
    const when = recent.current.get(code);
    if (when && now - when < 2500) return;
    recent.current.set(code, now);

    setProblem("");
    try {
      await ask("/api/scanner/scan", { code }, pairing.token);
      setSent((n) => n + 1);
      setLast(code);
      if (navigator.vibrate) navigator.vibrate(60);
    } catch (e) {
      const said = errorText(e, "That scan did not reach the counter.");
      setProblem(said);
      // The pairing is the only thing that can be wrong in a way the person
      // holding the phone can fix, so it is said plainly rather than left as
      // a failed scan they will repeat.
      if (/paired/i.test(said)) forget();
    }
  }

  if (!cameraSupported()) {
    return (
      <div className="ph-wrap">
        <div className="ph-card">
          <h1>This phone cannot be used as a scanner</h1>
          <p className="muted">
            The camera is not available to this browser. On a phone that
            usually means the page is not on a secure connection, or the
            browser was refused access to the camera.
          </p>
        </div>
      </div>
    );
  }

  if (!pairing) {
    return (
      <ScanCamera
        continuous
        title="Point this at the counter"
        onScan={(code) => { if (!busy) void claim(code); }}
        onClose={() => { /* there is nothing to close back to */ }}
      >
        <p className="ph-say">
          The screen at the counter is showing a barcode. Scan it and this
          phone becomes a scanner for that station.
        </p>
        {problem && <p className="alert error">{problem}</p>}
      </ScanCamera>
    );
  }

  /** What it sent, and nothing about what it was. A person needs to know the
   *  scan registered; they do not need this phone telling them whose
   *  prescription it is. */
  const tally = (
    <>
      <div className="ph-count">
        <span className="ph-count-n">{sent}</span>
        <span>
          scan{sent === 1 ? "" : "s"} sent to {pairing.station || "the counter"}
        </span>
      </div>
      {last && <p className="muted small ph-last">Last: {last}</p>}
      {problem && <p className="alert error">{problem}</p>}
    </>
  );

  if (scanning) {
    return (
      <ScanCamera
        continuous
        title={`Scanning for ${pairing.station || "the counter"}`}
        onScan={(code) => void send(code)}
        onClose={() => setScanning(false)}
      >
        {tally}
      </ScanCamera>
    );
  }

  return (
    <div className="ph-wrap">
      <div className="ph-card">
        <div className="ph-head">
          <div>
            <span className="ph-live">Paired to</span>
            <h1>{pairing.station || "the counter"}</h1>
          </div>
        </div>
        {tally}
        <button type="button" className="btn" onClick={() => setScanning(true)}>
          Scan
        </button>
        {/* Below the one they want, because unpairing means walking back to
            the counter for a new code. */}
        <button type="button" className="btn secondary" onClick={forget}>
          Stop using this phone as a scanner
        </button>
      </div>
    </div>
  );
}
