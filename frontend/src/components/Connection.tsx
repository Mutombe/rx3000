/** Whether the server is reachable, and what that means for what you may do.
 *
 *  A pharmacy's line goes down. That is the ordinary case this product is sold
 *  against, so the question is not whether to handle it but what the till is
 *  still permitted to do while it is down.
 *
 *  **The answer is: sell, but do not dispense.** Selling a bottle of shampoo
 *  offline is trivial — decrement stock, take the cash, reconcile on reconnect,
 *  and nothing can go wrong that the sync cannot fix. Dispensing is a different
 *  act, because four of the things it depends on live on the server and cannot
 *  be guessed at:
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
import { apiBase } from "../api";

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
      return ok;
    } catch {
      setOnline(false);
      setCheckedAt(new Date());
      return false;
    }
  }, []);

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
      {!online && <OfflineBanner onRetry={check} />}
      {children}
    </Ctx.Provider>
  );
}

function OfflineBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="conn-banner" role="status">
      <span className="conn-dot" aria-hidden="true" />
      <span>
        <b>No connection to the server.</b> The front shop still works — you can
        sell, take payment and print. Dispensing is unavailable until the line is
        back.
      </span>
      <button className="btn ghost small" onClick={onRetry}>Try again</button>
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
          possibly at another branch — and dispensing it twice is a clinical
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
        The front shop is unaffected. You can keep selling, taking payment and
        printing receipts, and everything reconciles when the line returns.
      </p>
      <div className="conn-actions">
        <button className="small" onClick={recheck}>Check again</button>
        <a className="btn secondary small" href="/pos">Go to the till</a>
      </div>
    </div>
  );
}
