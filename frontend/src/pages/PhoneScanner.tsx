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

import { ApiError, apiBase, errorText } from "../api";
import { Check, Copy, Keyboard, Warning } from "@phosphor-icons/react";
import { ScanCamera, beep, cameraSupported } from "../components/Scanner";
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
    // An ApiError, not a plain Error, and that difference was the whole bug.
    //
    // `errorText` unwraps ApiError and Refused and nothing else, so a plain
    // Error fell through to the caller's fallback. The server computes a
    // sentence saying exactly what is wrong — "That code is not one this
    // pharmacy is showing", "That code has expired. Ask the counter for a new
    // one" — and every one of them was replaced, on the screen of the person
    // standing there holding the phone, by "That code could not be used."
    //
    // Software that works out what went wrong and then says something vaguer
    // is worse than software that never worked it out.
    const spoken = said?.detail?.message
      ?? (typeof said?.detail === "string" ? said.detail : "");
    const err = new ApiError(r.status, spoken || "That did not work.");
    (err as ApiError & { detail?: unknown }).detail = said?.detail;
    throw err;
  }
  return said as T;
}

/** The pairing, kept so a phone that locks its screen comes back to work. */
const HELD = "scanner_pairing";

/** What a pairing code looks like: six characters of the server's alphabet.
 *
 *  Kept in step with `ALPHABET` in `services/scanner_link.py`, which leaves
 *  out O, 0, I, 1, B, S and Z because somebody has to read this aloud across
 *  a counter. Checked here only to tell a pairing code apart from the other
 *  things a camera can see; the server decides whether it is a real one.
 */
const PAIRING_SHAPE = /^[ACDEFGHJKLMNPQRTUVWXY2345679]{6}$/;

interface Pairing { token: string; station: string; id: number }

/** One scan this phone has taken, and what became of it. */
interface Shot {
  code: string;
  /** The symbology the camera read it from, where it reported one. */
  format: string;
  at: number;
  state: "sent" | "failed";
  why?: string;
}

/** The decoder's format names, said the way the label says them.
 *
 *  It reports `code_128` and `ean_13`. A dispenser reading a screen at the
 *  shelf should see the name printed in every pharmacy catalogue, not an
 *  enum.
 */
const SYMBOL_NAMES: Record<string, string> = {
  code_128: "Code 128",
  code_39: "Code 39",
  code_93: "Code 93",
  codabar: "Codabar",
  ean_13: "EAN-13",
  ean_8: "EAN-8",
  upc_a: "UPC-A",
  upc_e: "UPC-E",
  itf: "ITF",
  qr_code: "QR",
  data_matrix: "Data Matrix",
  aztec: "Aztec",
  pdf417: "PDF417",
};

function symbolName(raw: string): string {
  if (!raw) return "";
  return SYMBOL_NAMES[raw] ?? raw.replace(/_/g, " ").toUpperCase();
}

export default function PhoneScanner() {
  const [pairing, setPairing] = useState<Pairing | null>(() => {
    try {
      const raw = readStored(HELD);
      return raw ? (JSON.parse(raw) as Pairing) : null;
    } catch { return null; }
  });
  /** What this phone has sent this session, newest first.
   *
   *  A running total alone answers "did that count" and nothing else. When a
   *  scan goes astray — a torn label read as the wrong digits, a pack scanned
   *  twice, a pairing that lapsed mid-shift — the question is always "what did
   *  it actually send", and a number cannot answer it. So each one is kept
   *  with what it read, what symbol it read it from, and whether it arrived.
   *
   *  Kept in memory only, and deliberately. These are script numbers and pack
   *  codes; writing a patient's prescription number into a file on somebody's
   *  own phone is a leak with no upside, because the counter already has every
   *  one of them and is where they belong.
   */
  const [shots, setShots] = useState<Shot[]>([]);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  /** The code somebody read off the counter screen and typed. */
  const [typed, setTyped] = useState("");
  /** Which code was last copied, so the button can confirm it. */
  const [copied, setCopied] = useState("");
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
    setShots([]);
    recent.current.clear();
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
    // IS THIS EVEN A PAIRING CODE?
    //
    // The camera reads thirteen symbologies and fires on whatever it sees
    // first. Point this screen at a dispensing label — the obvious thing to
    // do, since scanning labels is what the phone is FOR — and it read the Rx
    // number off it, posted that to the server as a pairing code, and came
    // back with a refusal that explained nothing.
    //
    // A pairing code is six characters from a known alphabet. Anything else
    // is not a failed pairing, it is somebody scanning the right thing at the
    // wrong moment, and it deserves to be told which.
    const seen = code.trim().toUpperCase();
    if (!PAIRING_SHAPE.test(seen)) {
      setProblem(
        seen.length > 8
          ? "That looks like a label, not a pairing code. The phone is not "
            + "paired to a counter yet: on the counter screen press \"Use a "
            + "phone as a scanner\", then point this at the code it shows."
          : "That is not a pairing code. The code on the counter screen is "
            + "six characters long.");
      if (navigator.vibrate) navigator.vibrate([90, 70, 90]);
      return;
    }
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

  async function send(code: string, format = "") {
    if (!pairing) return;
    const now = Date.now();
    const when = recent.current.get(code);
    if (when && now - when < 2500) return;
    recent.current.set(code, now);

    setProblem("");
    try {
      await ask("/api/scanner/scan", { code }, pairing.token);
      setShots((all) =>
        [{ code, format, at: now, state: "sent" as const }, ...all].slice(0, 50));
    } catch (e) {
      const said = errorText(e, "That scan did not reach the counter.");
      setProblem(said);
      // Kept in the list as a failure rather than dropped. A scan that
      // vanished silently is the thing this whole screen exists to prevent,
      // and "it said it sent forty and the counter has thirty-nine" is not a
      // conversation anybody can have without a list.
      setShots((all) =>
        [{ code, format, at: now, state: "failed" as const, why: said }, ...all].slice(0, 50));
      // A double buzz and a low tone: the operator is looking at the goods,
      // not at the screen, and needs to know this one did not count.
      if (navigator.vibrate) navigator.vibrate([70, 60, 70]);
      beep(false);
      // The pairing is the only thing that can be wrong in a way the person
      // holding the phone can fix, so it is said plainly rather than left as
      // a failed scan they will repeat.
      if (/paired/i.test(said)) forget();
    }
  }

  /** Copy a code out, for the one case where somebody has to read it to a
   *  colleague or paste it into a message. */
  async function copy(code: string) {
    try {
      await navigator.clipboard?.writeText(code);
      setCopied(code);
      window.setTimeout(() => setCopied((c) => (c === code ? "" : c)), 1400);
    } catch {
      // Clipboard access is refused on some phones inside an iframe. The code
      // is on screen and can be read; nothing is lost worth interrupting for.
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
          On the counter screen press <b>Use a phone as a scanner</b>. Point
          this at the code it shows and this phone becomes a scanner for that
          station.
        </p>
        {problem && <p className="alert error">{problem}</p>}

        {/* TYPING IT IN, BECAUSE A CAMERA IS NOT ALWAYS THE ANSWER.
            The counter shows the six characters under the symbol and this
            page had no way to use them: a glossy monitor, a cracked lens or a
            dim shop left somebody with a code they could read perfectly well
            and no way in. Six characters is a few seconds of typing. */}
        <form className="ph-typed" onSubmit={(e) => {
          e.preventDefault();
          if (!busy && typed.trim()) void claim(typed);
        }}>
          <label htmlFor="ph-typed-code">or type the six characters</label>
          <div className="ph-typed-row">
            <input id="ph-typed-code" value={typed} inputMode="text"
                   autoCapitalize="characters" autoCorrect="off"
                   spellCheck={false} maxLength={6} placeholder="A2C4EF"
                   onChange={(e) => setTyped(e.target.value.toUpperCase())} />
            <button type="submit" className="btn primary"
                    disabled={busy || typed.trim().length < 6}>
              {busy ? "Pairing…" : "Pair"}
            </button>
          </div>
        </form>
      </ScanCamera>
    );
  }

  const sent = shots.filter((s) => s.state === "sent").length;

  /** What it sent, and what became of each one.
   *
   *  The count stays the headline because that is what somebody glances at
   *  between packs. The list is underneath for the moment the count and the
   *  counter disagree.
   *
   *  What is deliberately NOT here: what the code meant. The counter knows
   *  that it is Mrs Chirenje's amoxicillin; this phone does not need to, and
   *  a phone that displays patients' medicines is a phone that shows them to
   *  whoever is standing next to it.
   */
  const tally = (
    <>
      <div className="ph-count">
        <span className="ph-count-n">{sent}</span>
        <span>
          scan{sent === 1 ? "" : "s"} sent to {pairing.station || "the counter"}
        </span>
      </div>

      {problem && <p className="alert error ph-problem">{problem}</p>}

      {shots.length > 0 && (
        <ul className="ph-shots">
          {shots.slice(0, 8).map((s) => (
            <li key={`${s.at}-${s.code}`}
                className={s.state === "failed" ? "is-failed" : undefined}>
              <span className="ph-shot-mark" aria-hidden="true">
                {s.state === "sent"
                  ? <Check size={18} weight="bold" />
                  : <Warning size={18} weight="fill" />}
              </span>
              <span className="ph-shot-body">
                <span className="ph-shot-code mono">{s.code}</span>
                <span className="ph-shot-meta">
                  {s.format && <span className="ph-chip">{symbolName(s.format)}</span>}
                  {s.state === "failed"
                    ? <span className="ph-shot-why">{s.why}</span>
                    : <span className="ph-shot-why">
                        {new Date(s.at).toLocaleTimeString([], {
                          hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                      </span>}
                </span>
              </span>
              <button type="button" className="ph-shot-copy"
                      onClick={() => void copy(s.code)}
                      aria-label={`Copy ${s.code}`}>
                {copied === s.code
                  ? <Check size={18} weight="bold" />
                  : <Copy size={18} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );

  if (scanning) {
    return (
      <ScanCamera
        continuous
        title={`Scanning for ${pairing.station || "the counter"}`}
        onScan={(code, format) => void send(code, format)}
        onClose={() => setScanning(false)}
      >
        {tally}
        {/* A LABEL THE CAMERA WILL NOT READ.
            Torn, creased, under shrink wrap, or printed by a ribbon that ran
            out half way: a pharmacy is full of barcodes that no longer scan,
            and the number under the bars is always still legible. Without
            this the only way past one was to walk it to the counter. */}
        <form className="ph-typed ph-typed-inline" onSubmit={(e) => {
          e.preventDefault();
          const value = typed.trim();
          if (!value) return;
          setTyped("");
          void send(value, "");
        }}>
          <label htmlFor="ph-by-hand">
            <Keyboard size={16} /> or type the number under the bars
          </label>
          <div className="ph-typed-row">
            <input id="ph-by-hand" value={typed} inputMode="text"
                   autoCapitalize="characters" autoCorrect="off"
                   spellCheck={false} placeholder="e.g. RX260900015"
                   onChange={(e) => setTyped(e.target.value.toUpperCase())} />
            <button type="submit" className="btn primary"
                    disabled={!typed.trim()}>
              Send
            </button>
          </div>
        </form>
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
