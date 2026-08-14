/** Scanning, on a desktop counter and on a phone, through one interface.
 *
 *  These are not the same mechanism wearing one name. A counter scanner is a
 *  *keyboard*: it types the digits and presses Enter, faster than a person can.
 *  A phone is a *camera*: frames go to a decoder and a code falls out. Writing
 *  each screen against both would double every scanning workflow, so both are
 *  reduced here to the same event — a string arrived — and the screens above
 *  never learn which one it came from.
 *
 *  Two decisions worth stating, because both are easy to get wrong:
 *
 *  **Scanning works anywhere on the page, not only in a scan box.** A dispenser
 *  holding a pack in one hand should not have to click into a field first. The
 *  cost is that the keystrokes still land wherever the caret happens to be, so
 *  the burst detector snapshots the focused field before a burst and restores
 *  it after — otherwise a scan taken while a patient's name is half-typed would
 *  quietly corrupt it.
 *
 *  **A person typing fast is not a scan.** The test is a burst of at least six
 *  characters whose gaps are under 35ms, terminated by Enter. 35ms per key is
 *  around 340 words a minute sustained; scanners run at 5–15ms. The margin
 *  between the two is wide enough that neither side of the mistake happens.
 */
import React, {
  useCallback, useEffect, useRef, useState,
} from "react";
import { api } from "../api";
import { useToast } from "./Toast";

/* ------------------------------------------------------------------ types */

export interface ScanResult {
  found: boolean;
  code: string;
  symbology: string;
  matched_on: string;
  quantity_multiplier: number;
  batch_number: string;
  expiry_date: string | null;
  serial: string;
  product: {
    id: number; name: string; category: string; schedule: number;
    strength: string; dosage_form: string; pack_size: string;
    unit_price: number; cost_price: number; barcode: string;
    nappi_code: string; quantity_on_hand: number;
  } | null;
  suggestions: { id: number; name: string; barcode: string }[];
  warnings: string[];
  message?: string;
  open_batches?: {
    id: number; batch_number: string; expiry_date: string | null;
    quantity_remaining: number;
  }[];
  order_line?: {
    id: number; quantity_ordered: number; quantity_received: number;
    outstanding: number; unit_cost: number;
  };
}

export type ScanContext = "pos" | "stock" | "receive";

/* --------------------------------------------------- the wedge (desktop) */

/** How close together keystrokes must be before we believe a machine typed them. */
const MAX_GAP_MS = 35;
/** Shorter bursts are too easy to produce by hand to be worth acting on. */
const MIN_LENGTH = 6;

interface WedgeOptions {
  onScan: (code: string) => void;
  /** Off while a modal owns the keyboard, or the same pack scans twice. */
  enabled?: boolean;
}

export function useWedgeScanner({ onScan, enabled = true }: WedgeOptions) {
  // Refs throughout: a keystroke handler that re-subscribes on every character
  // would drop the burst it is in the middle of reading.
  const buffer = useRef("");
  const lastKey = useRef(0);
  const restore = useRef<{ el: HTMLInputElement | HTMLTextAreaElement; value: string } | null>(null);
  const handler = useRef(onScan);
  handler.current = onScan;

  useEffect(() => {
    if (!enabled) return;

    function reset() {
      buffer.current = "";
      restore.current = null;
    }

    function onKeyDown(e: KeyboardEvent) {
      const now = performance.now();
      const gap = now - lastKey.current;
      lastKey.current = now;

      if (e.key === "Enter") {
        const code = buffer.current;
        // A trailing Enter only means something if a burst preceded it. Left
        // alone otherwise, so Enter still submits forms normally.
        if (code.length >= MIN_LENGTH) {
          e.preventDefault();
          e.stopPropagation();
          // Put back whatever the scanner typed into an unrelated field.
          const r = restore.current;
          if (r && document.contains(r.el)) {
            r.el.value = r.value;
            r.el.dispatchEvent(new Event("input", { bubbles: true }));
          }
          reset();
          handler.current(code);
          return;
        }
        reset();
        return;
      }

      // Printable characters only. GS (\x1d) arrives from GS1 scanners as a
      // one-character key and is part of the payload, not a control press.
      if (e.key.length !== 1) return;

      if (gap > MAX_GAP_MS) {
        // Too slow to be a machine: this is a new burst, possibly a person.
        buffer.current = e.key;
        const el = document.activeElement as HTMLInputElement | null;
        restore.current =
          el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")
            ? { el, value: el.value }
            : null;
        return;
      }
      buffer.current += e.key;
    }

    // Capture phase: a scan must be recognised before a page-level Enter
    // handler submits a half-filled form with the barcode still in it.
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [enabled]);
}

/* --------------------------------------------------- the camera (phone) */

/** Whether this device can decode from its camera without a download.
 *
 *  Chrome on Android and Edge ship `BarcodeDetector`; Safari and Firefox do
 *  not. Rather than pull in a decoder that costs more than the rest of the
 *  bundle for the minority case, unsupported devices keep the typed field —
 *  which still works, and is what every pharmacy does today anyway.
 */
export function cameraSupported(): boolean {
  return typeof window !== "undefined" && "BarcodeDetector" in window;
}

const FORMATS = [
  "ean_13", "ean_8", "upc_a", "upc_e",
  "code_128", "code_39", "itf",
  "data_matrix", "qr_code",
];

export function ScanCamera({
  onScan, onClose,
}: { onScan: (code: string) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState("");
  const [hint, setHint] = useState("Point the camera at the barcode.");
  const stopped = useRef(false);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let raf = 0;
    stopped.current = false;

    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          // The back camera. Without this a phone opens the selfie camera and
          // the operator has to work out why nothing is decoding.
          video: { facingMode: { ideal: "environment" } },
        });
        const video = videoRef.current;
        if (!video) return;
        video.srcObject = stream;
        await video.play();

        const Detector = (window as any).BarcodeDetector;
        const detector = new Detector({ formats: FORMATS });

        const tick = async () => {
          if (stopped.current) return;
          try {
            const found = await detector.detect(video);
            if (found.length) {
              const value = found[0].rawValue as string;
              if (value) {
                stopped.current = true;
                // Confirm physically. At a counter the operator is looking at
                // the pack, not the screen, and needs to know it took.
                navigator.vibrate?.(60);
                onScan(value);
                return;
              }
            }
          } catch {
            // A frame that will not decode is the normal case, not an error.
          }
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      } catch (e: any) {
        setError(
          e?.name === "NotAllowedError"
            ? "The camera was blocked. Allow camera access for this site, then try again."
            : e?.name === "NotFoundError"
              ? "This device has no camera available."
              : "The camera could not be started on this device.",
        );
      }
    }

    start();
    const slow = window.setTimeout(
      () => setHint("Hold steady, and fill the frame with the barcode."),
      6000,
    );
    return () => {
      stopped.current = true;
      cancelAnimationFrame(raf);
      window.clearTimeout(slow);
      // Releasing every track is what turns the phone's camera light off. Skip
      // it and the light stays on after the sheet closes, which users read —
      // correctly — as the application still watching them.
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [onScan]);

  return (
    <div className="scan-sheet" role="dialog" aria-modal="true" aria-label="Scan a barcode">
      <div className="scan-sheet-head">
        <span>Scan a barcode</span>
        <button className="btn ghost" onClick={onClose} aria-label="Close the scanner">
          Close
        </button>
      </div>
      <div className="scan-stage">
        {error ? (
          <p className="scan-error">{error}</p>
        ) : (
          <>
            <video ref={videoRef} className="scan-video" playsInline muted />
            {/* The frame is the instruction. Nobody reads the sentence. */}
            <div className="scan-reticle" aria-hidden="true" />
          </>
        )}
      </div>
      {!error && <p className="scan-hint">{hint}</p>}
    </div>
  );
}

/* ------------------------------------------------------- resolving a scan */

/** Ask the server what a scanned string is. One path for every caller. */
export function useScanResolver(context: ScanContext, extra?: { branch_id?: number; order_id?: number }) {
  const branchId = extra?.branch_id;
  const orderId = extra?.order_id;
  return useCallback(
    (code: string) =>
      api.post<ScanResult>("/api/scan", {
        code, context, branch_id: branchId, order_id: orderId,
      }),
    [context, branchId, orderId],
  );
}

/* ------------------------------------------------------------- the field */

interface ScanBarProps {
  /** Called with a resolved scan. Warnings are already surfaced as toasts. */
  onResolved: (result: ScanResult) => void;
  context: ScanContext;
  branchId?: number;
  orderId?: number;
  placeholder?: string;
  /** Turn off the page-wide listener while a dialog is open. */
  enabled?: boolean;
  autoFocus?: boolean;
  /** Controlled text, for screens that also search as you type. Leave both out
   *  and the field manages its own text. */
  value?: string;
  onValueChange?: (next: string) => void;
  /** For screens with a "focus the scan box" hotkey. */
  inputRef?: React.RefObject<HTMLInputElement>;
}

/** The scan input: a wedge target, a typed fallback, and a camera button.
 *
 *  All three end at the same `onResolved`, so a screen using this handles one
 *  case regardless of how the code was captured.
 */
export function ScanBar({
  onResolved, context, branchId, orderId,
  placeholder = "Scan a barcode, or type a code or name…",
  enabled = true, autoFocus = false, value, onValueChange, inputRef: externalRef,
}: ScanBarProps) {
  const toast = useToast();
  const resolve = useScanResolver(context, { branch_id: branchId, order_id: orderId });
  const [ownText, setOwnText] = useState("");
  const controlled = value !== undefined;
  const typed = controlled ? value : ownText;
  const setTyped = useCallback(
    (next: string) => {
      if (!controlled) setOwnText(next);
      onValueChange?.(next);
    },
    [controlled, onValueChange],
  );
  const [busy, setBusy] = useState(false);
  const [camera, setCamera] = useState(false);
  const [miss, setMiss] = useState<ScanResult | null>(null);
  const [hunt, setHunt] = useState("");
  const [hits, setHits] = useState<{ id: number; name: string }[]>([]);
  const ownRef = useRef<HTMLInputElement>(null);
  const inputRef = externalRef ?? ownRef;
  // The same pack held in front of a camera decodes many times a second.
  const lastCode = useRef<{ code: string; at: number }>({ code: "", at: 0 });

  const handle = useCallback(
    async (code: string) => {
      const clean = code.trim();
      if (!clean) return;
      const now = Date.now();
      if (lastCode.current.code === clean && now - lastCode.current.at < 1200) return;
      lastCode.current = { code: clean, at: now };

      setBusy(true);
      try {
        const result = await resolve(clean);
        setTyped("");
        // Warnings are advisory — an out-of-stock line or a schedule 5 item is
        // still added, the operator is just told. Errors come back as throws.
        result.warnings?.forEach((w) => toast.warn(w));
        if (!result.found) {
          // A miss is the start of a workflow, not the end of one. Offer to
          // attach the code to a product rather than leaving a dead end.
          setMiss(result);
          if (result.message) toast.error(result.message);
        } else {
          setMiss(null);
        }
        onResolved(result);
      } catch (e: any) {
        toast.error(e?.message || "That scan could not be checked. Try again.");
      } finally {
        setBusy(false);
        inputRef.current?.focus();
      }
    },
    [resolve, onResolved, toast],
  );

  // Looking for the product an unknown code belongs to.
  useEffect(() => {
    if (!miss || hunt.trim().length < 2) { setHits([]); return; }
    let cancelled = false;
    api.get<{ id: number; name: string }[]>(
      `/api/products?q=${encodeURIComponent(hunt.trim())}&limit=6`,
    )
      .then((rows) => { if (!cancelled) setHits(rows); })
      .catch(() => { if (!cancelled) setHits([]); });
    return () => { cancelled = true; };
  }, [hunt, miss]);

  /** Attach the code that just missed to a product the operator picked. */
  async function teach(productId: number) {
    if (!miss) return;
    try {
      const res = await api.post<{ message: string }>("/api/scan/link", {
        code: miss.code, product_id: productId,
      });
      toast.ok(res.message);
      const code = miss.code;
      setMiss(null); setHunt(""); setHits([]);
      // Re-scan it. The operator wanted the product, not the bookkeeping, and
      // this puts them exactly where the successful scan would have.
      handle(code);
    } catch (e: any) {
      toast.error(e?.message || "That code could not be attached.");
    }
  }

  // The camera sheet owns the screen while it is open; a wedge listener
  // underneath it would fire on nothing useful.
  useWedgeScanner({ onScan: handle, enabled: enabled && !camera });

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  return (
    <>
      <div className={`scan-bar${busy ? " is-busy" : ""}`}>
        <span className="scan-icon" aria-hidden="true">
          {/* Deliberately not an emoji: this sits next to Phosphor icons. */}
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
            <path d="M2 5V3.5A1.5 1.5 0 0 1 3.5 2H5M15 2h1.5A1.5 1.5 0 0 1 18 3.5V5M18 15v1.5a1.5 1.5 0 0 1-1.5 1.5H15M5 18H3.5A1.5 1.5 0 0 1 2 16.5V15" strokeLinecap="round" />
            <path d="M5.5 6.5v7M8 6.5v7M10.5 6.5v7M14.5 6.5v7" strokeLinecap="round" />
          </svg>
        </span>
        <input
          ref={inputRef}
          className="scan-input"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handle(typed);
            }
          }}
          placeholder={placeholder}
          // A barcode is a code, not prose. Phones autocapitalising it or
          // offering to correct it is the difference between a scan and a
          // support call.
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          inputMode="search"
          aria-label="Scan or search"
          disabled={busy}
        />
        {cameraSupported() && (
          <button
            type="button"
            className="btn ghost scan-cam-btn"
            onClick={() => setCamera(true)}
            aria-label="Scan with the camera"
            title="Scan with the camera"
          >
            <svg width="17" height="17" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M2.5 6.5A1.5 1.5 0 0 1 4 5h1.8l1-1.6h4.4l1 1.6H16a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 16 16H4a1.5 1.5 0 0 1-1.5-1.5v-8Z" />
              <circle cx="10" cy="10.5" r="2.8" />
            </svg>
          </button>
        )}
      </div>
      {miss && (
        <div className="scan-catch">
          <div className="scan-catch-head">
            <span className="mono">{miss.code}</span>
            <span className="muted">is not on any product yet.</span>
            <button
              type="button"
              className="btn ghost small"
              onClick={() => { setMiss(null); setHunt(""); setHits([]); }}
            >
              Dismiss
            </button>
          </div>
          <p className="muted" style={{ marginTop: 0, fontSize: ".85rem" }}>
            Find the product it belongs to and it will be recognised from now on.
          </p>
          <input
            value={hunt}
            onChange={(e) => setHunt(e.target.value)}
            placeholder="Search by name or ingredient…"
            autoFocus
          />
          <div className="scan-teach-list">
            {(hits.length ? hits : miss.suggestions).map((p) => (
              <button
                key={p.id}
                type="button"
                className="scan-teach-row"
                onClick={() => teach(p.id)}
              >
                <span>{p.name}</span>
                <span className="muted">attach code</span>
              </button>
            ))}
          </div>
        </div>
      )}
      {camera && (
        <ScanCamera
          onClose={() => setCamera(false)}
          onScan={(code) => {
            setCamera(false);
            handle(code);
          }}
        />
      )}
    </>
  );
}
