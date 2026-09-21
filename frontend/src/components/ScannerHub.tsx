/** One scanner for the whole workstation, however it is plugged in.
 *
 *  WHY THIS REPLACED A BUTTON ON EVERY SCREEN
 *
 *  The phone pairing started life as a control mounted on the dispensing
 *  screen, then the till, then receiving, then inventory, then the stock
 *  count. Five copies, five toolbars getting wider, and the obvious next step
 *  was a sixth. That was the wrong shape and it was wrong for a reason worth
 *  writing down:
 *
 *  **A scanner belongs to the workstation, not to the screen.** Nobody puts a
 *  "connect your USB scanner" button on each page, because the scanner is
 *  plugged into the machine and whatever is on screen receives what it types.
 *  A borrowed phone is the same fact with a different cable. So it is paired
 *  once, from the top bar, beside the branch it belongs to — and every screen
 *  simply listens.
 *
 *  HOW THE TWO KINDS OF SCANNER MEET
 *
 *  A counter scanner is a keyboard: it types the digits and presses Enter. A
 *  phone is a camera on the end of a network connection. Both are reduced to
 *  the same event here — a string arrived — and delivered through one
 *  subscription, so a screen is written once and works with either. Adding a
 *  third kind later means teaching this file about it and changing no screen
 *  at all.
 *
 *  WHO RECEIVES A SCAN
 *
 *  The most recently mounted listener, not all of them. Screens come and go
 *  with the route, and a dialog opened on top of a page is the thing the
 *  operator is looking at, so it takes the scan the way it would take the
 *  keyboard. Anything underneath stays subscribed and gets it back when the
 *  thing above closes.
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";

import { api, apiBase, errorText } from "../api";
import { readStored, writeStored } from "../storage";
import { useToast } from "./Toast";
import { useWedgeScanner } from "./Scanner";

/** The counter's own pairing, so a reload does not drop the phone. */
const HELD = "scanner_link";

export interface Link {
  id: number; code: string; status: string; station: string;
  device: string; expires_at: string;
}

interface Listener {
  id: number;
  /** What this screen calls itself, for the indicator to name. */
  station: string;
  handler: (code: string, format?: string) => void;
  enabled: boolean;
}

interface Hub {
  link: Link | null;
  live: boolean;
  asking: boolean;
  /** What the scan would currently land in, or "" when nothing is listening. */
  target: string;
  offer: () => Promise<void>;
  stop: () => Promise<void>;
  subscribe: (l: Listener) => () => void;
  bump: (id: number, patch: Partial<Listener>) => void;
}

const HubContext = createContext<Hub | null>(null);

let nextId = 1;

export function ScannerProvider({ children }: { children: React.ReactNode }) {
  const toast = useToast();
  const [link, setLink] = useState<Link | null>(null);
  const [live, setLive] = useState(false);
  const [asking, setAsking] = useState(false);
  /** Bumped whenever the listener stack changes, so the indicator re-reads the
   *  target. The stack itself is a ref because a scan arriving must reach the
   *  listener that is mounted NOW, not the one captured at subscribe time. */
  const [, setRevision] = useState(0);
  const listeners = useRef<Listener[]>([]);

  const topMost = useCallback(() => {
    for (let i = listeners.current.length - 1; i >= 0; i--) {
      if (listeners.current[i].enabled) return listeners.current[i];
    }
    return null;
  }, []);

  const deliver = useCallback((code: string, format?: string) => {
    const who = topMost();
    if (who) {
      who.handler(code, format);
      return;
    }
    // Nothing is listening. Said rather than dropped: a scan that disappears
    // is the single most confusing thing a scanner can do, and "you are on a
    // screen that does not take scans" is a complete answer.
    toast.error("Nothing on this screen takes a scan. Open the till, "
                + "dispensing, inventory, a stock count or a delivery.");
  }, [topMost, toast]);

  const subscribe = useCallback((l: Listener) => {
    listeners.current = [...listeners.current, l];
    setRevision((n) => n + 1);
    return () => {
      listeners.current = listeners.current.filter((x) => x.id !== l.id);
      setRevision((n) => n + 1);
    };
  }, []);

  const bump = useCallback((id: number, patch: Partial<Listener>) => {
    let changed = false;
    listeners.current = listeners.current.map((x) => {
      if (x.id !== id) return x;
      if (patch.enabled !== undefined && patch.enabled !== x.enabled) changed = true;
      return { ...x, ...patch };
    });
    if (changed) setRevision((n) => n + 1);
  }, []);

  // THE COUNTER SCANNER, ONCE, HERE.
  //
  // It was mounted on the dispensing screen alone, so a USB scanner did
  // nothing at the till or in the stock room. Listening at the workstation
  // means it reaches whatever is on screen, which is what the hardware
  // already does and what everybody expects of it.
  useWedgeScanner({ onScan: (code) => deliver(code, "wedge") });

  /** Ask for a code to show. */
  const offer = useCallback(async () => {
    setAsking(true);
    try {
      const said = await api.post<Link>(
        "/api/scanner/pair", { station: topMost()?.station || "This counter" });
      setLink(said);
      writeStored(HELD, String(said.id));
    } catch (e) {
      toast.error(errorText(e, "A pairing code could not be made."));
    } finally {
      setAsking(false);
    }
  }, [topMost, toast]);

  const stop = useCallback(async () => {
    const id = link?.id;
    setLink(null);
    setLive(false);
    writeStored(HELD, null);
    if (id) {
      try { await api.post(`/api/scanner/close/${id}`, {}); } catch { /* going anyway */ }
    }
  }, [link?.id]);

  // Pick the phone back up after a reload. The server is asked what is still
  // live rather than trusting the stored id: the pairing may have been closed
  // from the phone, timed out, or ended elsewhere while this tab was shut.
  useEffect(() => {
    const held = readStored(HELD);
    if (!held) return;
    let dropped = false;
    api.get<{ links: Link[] }>("/api/scanner/links")
      .then(({ links }) => {
        if (dropped) return;
        const mine = links.find((l) => String(l.id) === held);
        if (mine) { setLink(mine); setLive(mine.status === "live"); }
        else writeStored(HELD, null);
      })
      .catch(() => {
        // Deliberately silent: a best-effort resume on mount. Pairing again
        // is one tap away and the control says so.
      });
    return () => { dropped = true; };
  }, []);

  // The live deliverer, reached through a ref by the stream below.
  //
  // Not in the stream's dependency list, and that is the whole point. Listed
  // there, any change of identity tore the connection down and opened a new
  // one — and `paired` is emitted once, at the moment the phone claims the
  // code, so a stream that reconnects a second later never sees it. The
  // desktop sat on "Pair a phone" while the phone said it was paired, which
  // is the most confusing possible disagreement between two screens.
  const deliverRef = useRef(deliver);
  deliverRef.current = deliver;

  // The stream. `fetch` rather than `EventSource`, which cannot carry an
  // Authorization header; moving the credential into the URL would put a
  // bearer token into every proxy log between here and the server.
  useEffect(() => {
    if (!link?.id) return;
    const abort = new AbortController();
    let shut = false;

    (async () => {
      try {
        const token = readStored("token");
        const r = await fetch(`${apiBase}/api/scanner/stream/${link.id}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: abort.signal,
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
          // THE KIND IS ON THE SSE `event:` LINE, NOT INSIDE THE JSON.
          //
          // Rewriting this from the original, it read `said.event` out of the
          // parsed data, where there is no such field. Every frame parsed
          // cleanly and matched nothing, so the stream sat there open, healthy
          // and silent: the phone reported itself paired while the counter
          // went on showing "Pair a phone" for ever. A bug that looks like
          // nothing happening is the expensive kind.
          //
          // Frames are separated by a blank line. Anything short of one is
          // half a frame and waits for the rest, which is what makes this safe
          // against a chunk boundary landing mid-message.
          while ((cut = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, cut);
            buffer = buffer.slice(cut + 2);
            const kind = /^event: (.*)$/m.exec(frame)?.[1] ?? "";
            const data = /^data: (.*)$/m.exec(frame)?.[1] ?? "";
            // `open` only means the stream is up, which is true while the code
            // still sits unclaimed on screen. Only `paired` means a phone
            // actually took it.
            if (kind === "paired") setLive(true);
            if (kind === "closed") { setLive(false); setLink(null); writeStored(HELD, null); }
            if (kind === "scan") {
              try {
                const said = JSON.parse(data) as { code?: string };
                if (said.code) deliverRef.current(said.code, "phone");
              } catch { /* a frame we cannot read is not worth a crash */ }
            }
          }
        }
      } catch { /* aborted, or the connection went; the control says so */ }
    })();

    return () => { shut = true; abort.abort(); };
  }, [link?.id]);

  const value = useMemo<Hub>(() => ({
    link, live, asking, target: topMost()?.station ?? "",
    offer, stop, subscribe, bump,
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [link, live, asking, offer, stop, subscribe, bump, topMost, listeners.current.length]);

  return <HubContext.Provider value={value}>{children}</HubContext.Provider>;
}

export function useScannerHub(): Hub | null {
  return useContext(HubContext);
}

/** Take scans on this screen, from whichever scanner the workstation has.
 *
 *  The whole contract a screen needs. It does not learn whether the string
 *  came off a phone, a USB scanner or somebody typing into the box, which is
 *  the point: one handler, written once.
 */
export function useScanFeed(
  station: string,
  handler: (code: string, format?: string) => void,
  enabled = true,
): void {
  const hub = useScannerHub();
  const id = useRef(nextId++).current;
  // The live handler, so a subscription made on mount still calls the current
  // closure rather than the one that existed then.
  const current = useRef(handler);
  current.current = handler;

  useEffect(() => {
    if (!hub) return;
    return hub.subscribe({
      id, station,
      handler: (code, format) => current.current(code, format),
      enabled,
    });
    // Subscribing once per screen: `enabled` and `station` are pushed through
    // `bump` below rather than re-subscribing, which would reorder the stack
    // and hand the scan to the wrong screen every time a dialog toggled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hub, id]);

  useEffect(() => {
    hub?.bump(id, { enabled, station });
  }, [hub, id, enabled, station]);
}
