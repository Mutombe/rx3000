import { ArrowsClockwise } from "@phosphor-icons/react";
/** Whether the server is reachable, and what that means for what you may do.
 *
 *  A pharmacy's line goes down. That is the ordinary case this product is sold
 *  against, so the question is not whether to handle it but what the till is
 *  still permitted to do while it is down.
 *
 *  **The answer is: sell, but never dispense.** Selling offline is a solvable
 *  problem — decrement a locally cached stock figure, take the cash, reconcile
 *  on reconnect, and nothing goes wrong that the sync cannot fix. That local
 *  cache and sync queue are not built yet, so today offline means the till
 *  cannot save either; the banner says so rather than promising otherwise.
 *
 *  Dispensing is a different matter and will stay blocked even after offline
 *  selling works, because four of the things it depends on live on the server
 *  and cannot be deferred:
 *
 *  * **Repeats.** Whether repeat 3 of 6 was already collected — possibly at the
 *    other branch, twenty minutes ago. Offline there is no way to know, and
 *    dispensing it again is a real clinical event, not a data conflict.
 *  * **Medical aid.** Eligibility and adjudication are live calls. Offline you
 *    would be handing over medicine on the assumption a scheme will pay.
 *  * **The controlled register.** S5 and S6 entries are a legal record. A gap
 *    in it is a regulatory problem, not a synchronisation problem.
 *  * **Interactions**, against a history that is not local.
 *
 *  A queue-and-reconcile design would paper over all four, and every one of
 *  them fails in a direction that lands on a patient. So the block is real: the
 *  dispensary is closed while the line is down, and the screen says so in those
 *  words rather than failing at the point somebody presses Dispense.
 */
import {
  createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState,
} from "react";
import { apiBase, getToken } from "../api";
import * as catalogue from "../offline/catalogue";
import * as queue from "../offline/queue";
import BusyButton from "./BusyButton";

interface Connection {
  online: boolean;
  /** Never null once a check has run. Null means we have not looked yet. */
  checkedAt: Date | null;
  recheck: () => void;
}

const Ctx = createContext<Connection>({ online: true, checkedAt: null, recheck: () => {} });

export function useConnection() {
  return useContext(Ctx);
}

/** How often to look while connected, and while not.
 *
 *  Faster when down, because the thing everybody wants to know is the moment it
 *  comes back — and slower when up, because a healthy till should not spend its
 *  time asking.
 */
const POLL_UP = 30_000;
const POLL_DOWN = 5_000;

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [online, setOnline] = useState(true);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [held, setHeld] = useState(0);
  // A token appearing is not something React re-renders for, so it is
  // sampled on each connection poll — which is frequent enough to pick up
  // a sign-in within seconds and cheap enough not to matter.
  const [signedIn, setSignedIn] = useState(() => Boolean(getToken()));
  const [flushed, setFlushed] = useState(0);
  const timer = useRef<number>();

  const check = useCallback(async () => {
    // The browser's own flag is necessary but not sufficient: a till can be on
    // a healthy LAN with the pharmacy's server switched off, which reads as
    // online to the browser and is useless to us. So the server is asked.
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setOnline(false);
      setCheckedAt(new Date());
      return false;
    }
    try {
      const controller = new AbortController();
      const bail = window.setTimeout(() => controller.abort(), 4000);
      const res = await fetch(`${apiBase}/api/health`, {
        signal: controller.signal,
        cache: "no-store",
      });
      window.clearTimeout(bail);
      const ok = res.ok;
      setOnline(ok);
      setCheckedAt(new Date());
      setSignedIn(Boolean(getToken()));
      return ok;
    } catch {
      setOnline(false);
      setCheckedAt(new Date());
      return false;
    }
  }, []);

  // Refresh the local catalogue while the line is up, so the copy on disk is
  // always from the last good moment. A till that only caches once it notices
  // it is offline has nothing left to cache with.
  const synced = useRef(false);
  useEffect(() => {
    // Not before somebody has signed in. This provider wraps the sign-in page
    // as well as the application, and without the check the till asks for the
    // whole catalogue while unauthenticated — a 401 on every mount, repeated,
    // against a server that is answering perfectly well.
    if (!online || synced.current || !getToken()) return;
    synced.current = true;
    catalogue.sync().catch(() => { synced.current = false; });
  }, [online, signedIn]);

  // Send anything taken while the line was down. Safe to run on every return
  // because a replayed sale is recognised by its reference rather than posted
  // again — see offline/queue.ts, which is where that property is argued for.
  useEffect(() => {
    queue.pendingCount().then(setHeld).catch(() => {});
    // Same reason: a queued sale cannot be posted by a till nobody is signed
    // in to, and trying produces a 401 that looks like a rejected sale.
    if (!online || !getToken()) return;
    let cancelled = false;
    queue.flush()
      .then(async (r) => {
        if (cancelled) return;
        setHeld(r.remaining);
        if (r.posted) setFlushed(r.posted);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [online, signedIn]);

  useEffect(() => {
    let cancelled = false;
    async function loop() {
      if (cancelled) return;
      const ok = await check();
      timer.current = window.setTimeout(loop, ok ? POLL_UP : POLL_DOWN);
    }
    loop();
    // The browser tells us about the obvious cases immediately, so we do not
    // sit out a whole poll interval before noticing.
    const wake = () => check();
    window.addEventListener("online", wake);
    window.addEventListener("offline", wake);
    return () => {
      cancelled = true;
      window.clearTimeout(timer.current);
      window.removeEventListener("online", wake);
      window.removeEventListener("offline", wake);
    };
  }, [check]);

  return (
    <Ctx.Provider value={{ online, checkedAt, recheck: check }}>
      {!online && <OfflineBanner onRetry={check} held={held} />}
      {/* Said once, when it happens, then gone. A till that carries a permanent
          notice about a queue that is empty teaches people to ignore it. */}
      {online && flushed > 0 && (
        <div className="conn-banner is-good" role="status">
          <span>
            {flushed} sale{flushed === 1 ? "" : "s"} taken offline {flushed === 1 ? "has" : "have"} now been sent.
          </span>
          <button className="btn ghost small" onClick={() => setFlushed(0)}>Dismiss</button>
        </div>
      )}
      {children}
    </Ctx.Provider>
  );
}

function OfflineBanner({ onRetry, held }: { onRetry: () => Promise<boolean>; held: number }) {
  return (
    <div className="conn-banner" role="status">
      <span className="conn-dot" aria-hidden="true" />
      <span>
        {/* Every clause here is something the till can actually do. This
            promised the front shop worked before it did, which is the software
            lying to a cashier at the moment they are least able to check, so
            it now changes only when the capability does. */}
        <b>No connection to the server.</b> Cash sales still work and are held on
        this till until the line is back. Card, mobile money and medical aid need
        the server. Dispensing is closed.
        {held > 0 && <> <b>{held} sale{held === 1 ? "" : "s"} waiting.</b></>}
      </span>
      <BusyButton className="btn ghost small" onClick={onRetry} icon={ArrowsClockwise} busyLabel="Trying…">
        Try again
      </BusyButton>
    </div>
  );
}

/** Wraps anything that must not run while the server is unreachable.
 *
 *  Deliberately a gate around the whole screen rather than a check at the point
 *  of pressing Dispense. Letting a pharmacist select a patient, pick a script
 *  and choose a batch before telling them none of it can be completed wastes
 *  their time and, worse, teaches them the message is noise.
 */
export function RequiresConnection({
  children, what = "This",
}: { children: ReactNode; what?: string }) {
  const { online, recheck } = useConnection();
  if (online) return <>{children}</>;

  return (
    <div className="card conn-blocked">
      <h3>{what} is unavailable offline</h3>
      <p>
        The server cannot be reached, so this screen cannot check the things it
        has to check before medicine leaves the counter:
      </p>
      <ul className="conn-reasons">
        <li>
          <b>Repeats.</b> Whether this repeat has already been collected —
          possibly at another branch. And dispensing it twice is a clinical
          event, not a record to tidy up later.
        </li>
        <li>
          <b>Medical aid.</b> Eligibility and the claim are live. Offline we
          would be handing over medicine and hoping the scheme pays.
        </li>
        <li>
          <b>The controlled register.</b> Schedule 5 and 6 entries are a legal
          record, and a gap in it is a regulatory problem.
        </li>
      </ul>
      <p className="muted">
        Dispensing stays unavailable offline by design, even once offline
        selling is supported. The three checks above cannot be made without the
        server, and none of them can safely be deferred.
      </p>
      <div className="conn-actions">
        <button className="small" onClick={recheck}>Check again</button>
      </div>
    </div>
  );
}
